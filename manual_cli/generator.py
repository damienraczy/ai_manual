"""Orchestration de la génération du manuel : TOC, rédaction, jugement, mémoire.

Pipeline pour chaque section : rédaction (`model_write`) → jugement
(`model_judge`) → réécriture (`model_rewriter`) si nécessaire, dans la
limite de `max_rewrite` cycles → mise à jour de la mémoire (`model_think`).
`run_write` peut traiter plusieurs sections en parallèle via un
`ThreadPoolExecutor`, en protégeant par verrou les écritures partagées
(manifeste et mémoire).
"""

from __future__ import annotations

import string
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from functools import partial
from pathlib import Path

from .config import AppConfig
from .memory import INITIAL_DIGEST, ensure_budget, load_digest, save_digest, update_digest
from .parsing import call_structured
from .providers import OllamaCloudClient
from .requirements_loader import blocking_ids, criteria_for_partie, load_requirements, render_criteria
from .schemas import JudgeVerdict, TocSchema
from .state import ManualState, SectionState, build_manual_state, load_state, save_state, state_exists

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SECTION_END_TEMPLATE = "--- Fin de la section {numero} — Dis « continue » pour la suivante ---"


class GeneratorError(Exception):
    """Erreur d'orchestration de la génération (ex: TOC absente)."""


def _read_prompt(name: str) -> str:
    """Lit le contenu d'un fichier de prompt depuis `prompts/`.

    Args:
        name: Nom du fichier (ex: `"system_prompt.md"`).

    Returns:
        Le contenu texte du fichier.
    """
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _client(cfg: AppConfig, role: str) -> OllamaCloudClient:
    """Construit un client LLM pour un rôle donné.

    Args:
        cfg: Configuration applicative résolue.
        role: Nom du rôle (`"model_write"`, `"model_judge"`, `"model_think"`
            ou `"model_rewriter"`).

    Returns:
        Un client prêt à appeler le modèle associé à ce rôle.
    """
    return OllamaCloudClient(cfg.role(role), role=role)


def generate_toc(cfg: AppConfig, output_dir: Path) -> ManualState:
    """Génère la table des matières et initialise l'état du manuel.

    Appelle `model_write` pour produire la TOC au format JSON strict,
    construit l'état de suivi par section, initialise la mémoire, et écrit
    `00_toc.md` (version lisible) et `manifest.json` (état).

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.

    Returns:
        L'état initial du manuel, une section par chapitre (statut `"pending"`).

    Raises:
        ParsingError: Si le modèle ne produit pas de JSON valide conforme
            au schéma après plusieurs tentatives.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    messages = [
        {"role": "system", "content": _read_prompt("system_prompt.md")},
        {"role": "user", "content": _read_prompt("toc_instruction.md")},
    ]
    toc = call_structured(_client(cfg, "model_write"), messages, TocSchema, max_attempts=3)
    state = build_manual_state(toc)
    save_state(output_dir, state)
    save_digest(output_dir, INITIAL_DIGEST)
    _write_toc_markdown(output_dir, state)
    return state


def _write_toc_markdown(output_dir: Path, state: ManualState) -> None:
    """Écrit une version Markdown lisible de la table des matières.

    Args:
        output_dir: Répertoire de sortie du manuel.
        state: État du manuel contenant la TOC à rendre.
    """
    lines = [f"# {state.titre_manuel}", "", "## Table des matières", ""]
    for partie in state.toc.parties:
        lines.append(f"### Partie {partie.numero}. {partie.titre}")
        lines.append("")
        for chapitre in partie.chapitres:
            lines.append(f"**{chapitre.numero}. {chapitre.titre}**")
            lines.append(f"*{chapitre.description}*")
            for ss in chapitre.sous_sections:
                lines.append(f"- {ss.numero} {ss.titre}")
            lines.append("")
    (output_dir / "00_toc.md").write_text("\n".join(lines), encoding="utf-8")


def _strip_end_marker(text: str, numero: int) -> tuple[str, bool]:
    """Retire le marqueur de fin de section attendu, s'il est présent.

    Le marqueur sert de garde-fou de parsabilité côté prompt (voir
    `prompts/section_instruction.md`) ; il n'a pas vocation à figurer dans
    le manuel final.

    Args:
        text: Texte brut renvoyé par le modèle pour la section.
        numero: Numéro de section attendu dans le marqueur.

    Returns:
        Un tuple `(texte_sans_marqueur, marqueur_present)`. Si le marqueur
        est absent ou porte un numéro différent, le texte est retourné tel
        quel (juste `strip()`) et `marqueur_present` vaut `False`.
    """
    marker = SECTION_END_TEMPLATE.format(numero=numero)
    stripped = text.strip()
    if stripped.endswith(marker):
        return stripped[: -len(marker)].strip(), True
    return stripped, False


def _draft_section(cfg: AppConfig, section: SectionState, digest: str) -> str:
    """Demande au modèle rédacteur un premier jet de section.

    Args:
        cfg: Configuration applicative résolue.
        section: Section à rédiger (titre, sous-sections, etc.).
        digest: Résumé mémoire du manuel déjà rédigé, pour la cohérence.

    Returns:
        Le texte brut renvoyé par le modèle (marqueur de fin inclus).
    """
    template = string.Template(_read_prompt("section_instruction.md"))
    sous_sections = "\n".join(f"- {s}" for s in section.sous_sections)
    instruction = template.substitute(
        numero=section.numero,
        titre=section.titre,
        description=section.description,
        sous_sections=sous_sections,
        digest=digest,
    )
    messages = [
        {"role": "system", "content": _read_prompt("system_prompt.md")},
        {"role": "user", "content": instruction},
    ]
    return _client(cfg, "model_write").chat(messages)


def _judge_section(
    cfg: AppConfig, section: SectionState, section_text: str, requirements: dict
) -> JudgeVerdict:
    """Fait évaluer une section par le modèle juge.

    Applique un garde-fou local : si le juge répond `"accept"` mais liste
    tout de même un problème dont l'identifiant est connu comme bloquant
    (d'après `requirements`), le verdict est forcé à `"revise"` plutôt que
    de faire confiance à la sévérité éventuellement mal renseignée par le modèle.

    Args:
        cfg: Configuration applicative résolue.
        section: Section évaluée (utilisée pour retrouver sa partie).
        section_text: Texte de la section à évaluer.
        requirements: Exigences chargées via `requirements_loader.load_requirements`.

    Returns:
        Le verdict du juge, éventuellement corrigé par le garde-fou local.

    Raises:
        ParsingError: Si le modèle ne produit pas de JSON valide conforme
            au schéma après plusieurs tentatives.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    criteria = criteria_for_partie(requirements, section.partie_titre)
    template = string.Template(_read_prompt("judge_instruction.md"))
    instruction = template.substitute(
        requirements=render_criteria(criteria),
        section_text=section_text,
    )
    verdict = call_structured(
        _client(cfg, "model_judge"), [{"role": "user", "content": instruction}], JudgeVerdict, max_attempts=3
    )

    must_block = blocking_ids(criteria)
    if verdict.verdict == "accept" and any(issue.id in must_block for issue in verdict.issues):
        verdict.verdict = "revise"
    return verdict


def _rewrite_section(cfg: AppConfig, section: SectionState, section_text: str, verdict: JudgeVerdict) -> str:
    """Demande au modèle réécrivain une version corrigée de la section.

    Args:
        cfg: Configuration applicative résolue.
        section: Section concernée (utilisée pour le numéro dans le marqueur de fin).
        section_text: Texte original à corriger.
        verdict: Verdict du juge contenant les problèmes à corriger.

    Returns:
        Le texte brut réécrit par le modèle.
    """
    issues_text = "\n".join(f"- [{i.severity}] `{i.id}` : {i.detail}" for i in verdict.issues)
    issues_text = issues_text or "(aucun détail fourni)"
    template = string.Template(_read_prompt("rewrite_instruction.md"))
    instruction = template.substitute(section_text=section_text, issues=issues_text, numero=section.numero)
    return _client(cfg, "model_rewriter").chat([{"role": "user", "content": instruction}])


def write_section(
    cfg: AppConfig,
    output_dir: Path,
    state: ManualState,
    section: SectionState,
    requirements: dict,
    max_rewrite: int = 2,
    *,
    state_lock: threading.Lock | None = None,
    memory_lock: threading.Lock | None = None,
) -> SectionState:
    """Rédige, fait juger et sauvegarde une section, en gérant les réécritures.

    Boucle rédaction/jugement/réécriture jusqu'à acceptation ou jusqu'à
    épuisement de `max_rewrite` tentatives de réécriture. Une section n'est
    marquée `"done"` que si le juge l'accepte ET que le marqueur de fin
    attendu est bien présent (double garde-fou de parsabilité).

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        state: État complet du manuel (muté en place : statut de `section`).
        section: Section à traiter.
        requirements: Exigences chargées via `requirements_loader.load_requirements`.
        max_rewrite: Nombre maximal de cycles de réécriture après un rejet.
        state_lock: Verrou protégeant l'écriture du manifeste lors d'une
            exécution parallèle (voir `run_write`). `None` en exécution
            séquentielle ou dans les tests unitaires.
        memory_lock: Verrou protégeant la lecture-modification-écriture de
            la mémoire lors d'une exécution parallèle. Mêmes conditions
            d'usage que `state_lock`.

    Returns:
        La `SectionState` mise à jour (statut, nombre de tentatives, dernier verdict).
    """
    digest = load_digest(output_dir)

    text = _draft_section(cfg, section, digest)
    verdict = _judge_section(cfg, section, text, requirements)
    attempts = 1

    while verdict.verdict == "revise" and attempts <= max_rewrite:
        text = _rewrite_section(cfg, section, text, verdict)
        verdict = _judge_section(cfg, section, text, requirements)
        attempts += 1

    final_text, marker_ok = _strip_end_marker(text, section.numero)
    accepted = verdict.verdict == "accept" and marker_ok

    (output_dir / section.filename).write_text(final_text + "\n", encoding="utf-8")

    section.status = "done" if accepted else "failed"
    section.attempts = attempts
    section.last_verdict = verdict.verdict if marker_ok else "revise (marqueur de fin manquant)"
    with state_lock or nullcontext():
        save_state(output_dir, state)

    think_client = _client(cfg, "model_think")
    with memory_lock or nullcontext():
        # Relit le digest le plus récent (potentiellement mis à jour entre-temps par une autre
        # section traitée en parallèle) pour ne pas écraser sa contribution mémoire.
        current_digest = load_digest(output_dir)
        new_digest = update_digest(think_client, current_digest, section.titre, final_text)
        new_digest = ensure_budget(think_client, new_digest)
        save_digest(output_dir, new_digest)

    return section


def run_write(
    cfg: AppConfig,
    output_dir: Path,
    only_numeros: list[int] | None = None,
    max_rewrite: int = 2,
    workers: int = 4,
) -> list[SectionState]:
    """Rédige une sélection de sections, en parallèle si plusieurs sont ciblées.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel (doit déjà contenir un
            manifeste produit par `generate_toc`).
        only_numeros: Numéros de sections à traiter. `None` (par défaut)
            traite toutes les sections dont le statut n'est pas `"done"`.
        max_rewrite: Nombre maximal de cycles de réécriture par section
            après un rejet du juge.
        workers: Nombre de sections traitées en parallèle (borné au nombre
            de sections ciblées).

    Returns:
        La liste des `SectionState` traitées, dans l'ordre des sections
        ciblées (indépendamment de leur ordre réel de complétion).

    Raises:
        GeneratorError: Si aucun manifeste n'existe encore dans `output_dir`.
        KeyError: Si `only_numeros` contient un numéro de section inconnu.
    """
    if not state_exists(output_dir):
        raise GeneratorError("Aucune table des matières générée. Lance d'abord `manual init`.")

    state = load_state(output_dir)
    requirements = load_requirements()

    if only_numeros is not None:
        targets = [state.section_by_numero(n) for n in only_numeros]
    else:
        targets = [s for s in state.sections if s.status != "done"]

    if not targets:
        return []

    state_lock = threading.Lock()
    memory_lock = threading.Lock()
    worker_fn = partial(
        write_section,
        cfg,
        output_dir,
        state,
        requirements=requirements,
        max_rewrite=max_rewrite,
        state_lock=state_lock,
        memory_lock=memory_lock,
    )

    max_workers = max(1, min(workers, len(targets)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(worker_fn, targets))
