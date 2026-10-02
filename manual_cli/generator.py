"""Orchestration de la génération du manuel : TOC, rédaction, jugement, mémoire.

Pipeline pour chaque section : rédaction (`model_write`) → jugement
(`model_judge`) → réécriture (`model_rewriter`) si nécessaire, dans la
limite de `max_rewrite` cycles → mise à jour de la mémoire (`model_think`).
`run_write` peut traiter plusieurs sections en parallèle via un
`ThreadPoolExecutor`, en protégeant par verrou les écritures partagées
(manifeste et mémoire).
"""

from __future__ import annotations

import re
import shutil
import string
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from pydantic import model_validator

from .config import AppConfig
from .memory import INITIAL_DIGEST, ensure_budget, load_digest, save_digest, update_digest
from .parsing import call_structured
from .providers import OllamaCloudClient
from .requirements_loader import blocking_ids, criteria_for_partie, render_criteria
from .schemas import GeneratedTocSchema, JudgeVerdict, SousSection, TocSchema
from .sources import Unite, list_source_files, load_index, refresh_index, subject_context
from .sources_assign import ensure_assignment, plan_summary, section_matter
from .state import (
    ManualState,
    SectionState,
    build_manual_state,
    load_state,
    manifest_path,
    render_plan,
    renumber_toc,
    toc_path,
    save_state,
    state_exists,
)
from .subjects import Subject

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SECTION_END_TEMPLATE = "--- Fin de la section {numero} — Dis « continue » pour la suivante ---"
COVERAGE_ID = "couverture_sources"
DISCARD_RE = re.compile(r"<!--\s*écarté\s*\[([^\]]+)\]\s*:\s*(.*?)\s*-->", re.DOTALL)
REWRITE_SOURCES_NOTE = (
    "Si un problème signale un élément de cette matière comme oublié, traite-le à partir d'elle, ou écarte-le "
    "par une ligne `<!-- écarté [identifiant] : motif -->` placée juste avant la ligne de fin. "
    "Conserve les lignes `<!-- écarté … -->` déjà présentes."
)


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


def generate_toc(cfg: AppConfig, output_dir: Path, subject: Subject) -> ManualState:
    """Génère la table des matières et initialise l'état du manuel.

    Appelle `model_write` avec les prompts du sujet pour produire la TOC au
    format JSON strict, construit l'état de suivi par section (en y
    mémorisant l'identifiant du sujet), initialise la mémoire, et écrit
    `00_toc.md` (version lisible) et `manifest.json` (état).

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        subject: Sujet fournissant le prompt système et l'instruction de plan.

    Returns:
        L'état initial du manuel, une section par chapitre (statut `"pending"`).

    Raises:
        ParsingError: Si le modèle ne produit pas de JSON valide conforme
            au schéma après plusieurs tentatives.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    matter = _matter_for_plan(cfg, output_dir, subject)
    messages = [
        {"role": "system", "content": subject.system_prompt()},
        {"role": "user", "content": "\n\n".join(filter(None, [subject.toc_instruction(), matter]))},
    ]
    toc = call_structured(_client(cfg, "model_write"), messages, GeneratedTocSchema, max_attempts=3)
    state = build_manual_state(toc, subject=subject.slug)
    save_state(output_dir, state)
    save_digest(output_dir, INITIAL_DIGEST)
    _write_toc_markdown(output_dir, state)
    _prepare_sources(cfg, output_dir, subject, state)
    return state


def _describe(sous_section: SousSection) -> str:
    """Formate une sous-section pour un prompt ou le plan lisible.

    Args:
        sous_section: Sous-section à formater.

    Returns:
        `"numero titre — description"`, ou `"numero titre"` si elle n'a pas de
        description (manifeste ancien).
    """
    if not sous_section.description.strip():
        return sous_section.label
    return f"{sous_section.label} — {sous_section.description.strip()}"


def _labels(section: SectionState) -> list[str]:
    """Liste les intitulés `"numero titre"` des sous-sections d'un chapitre, descriptions exclues.

    Args:
        section: Chapitre suivi dans le manifeste.

    Returns:
        Les intitulés, dans l'ordre : c'est ce qui identifie un chapitre déjà rédigé.
    """
    return [ss.label for ss in section.sous_sections]


def _write_toc_markdown(output_dir: Path, state: ManualState) -> None:
    """Écrit une version Markdown lisible de la table des matières.

    Args:
        output_dir: Répertoire de sortie du manuel.
        state: État du manuel contenant la TOC à rendre.
    """
    lines = [f"# {state.titre_manuel}", "", "## Table des matières", ""]

    def entry(label: str, item) -> None:
        lines.append(f"**{label}**")
        lines.append(f"*{item.description}*")
        for ss in item.sous_sections:
            lines.append(f"- {ss.label}")
            if ss.description.strip():
                lines.append(f"  *{ss.description.strip()}*")
        lines.append("")

    if state.toc.introduction is not None:
        entry(state.toc.introduction.titre, state.toc.introduction)
    for partie in state.toc.parties:
        lines.append(f"### Partie {partie.numero}. {partie.titre}")
        lines.append("")
        for chapitre in partie.chapitres:
            entry(f"{chapitre.numero}. {chapitre.titre}", chapitre)
    if state.toc.conclusion is not None:
        entry(state.toc.conclusion.titre, state.toc.conclusion)
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


def _role_note(section: SectionState) -> str:
    """Consigne propre à l'introduction ou à la conclusion (vide pour un chapitre).

    Args:
        section: Section à rédiger.

    Returns:
        Le contenu de `prompts/role_<role>.md`, ou une chaîne vide pour un chapitre.
    """
    if section.role == "chapitre":
        return ""
    return _read_prompt(f"role_{section.role}.md").strip()


def _draft_section(
    cfg: AppConfig,
    section: SectionState,
    digest: str,
    plan: str,
    system_prompt: str,
    *,
    existing_text: str | None = None,
    instruction: str | None = None,
    sources: str = "",
) -> str:
    """Demande au modèle rédacteur un jet de section, neuf ou amorcé par un texte existant.

    Args:
        cfg: Configuration applicative résolue.
        section: Section à rédiger (titre, sous-sections, etc.).
        digest: Résumé mémoire du manuel déjà rédigé, pour la cohérence.
        plan: Plan complet de l'ouvrage (voir `state.render_plan`).
        system_prompt: Prompt système du sujet.
        existing_text: Version actuelle de la section. Si fournie, le jet est
            une amélioration de ce texte (prompt `improve_instruction.md`)
            plutôt qu'une rédaction à partir de rien.
        instruction: Consigne d'amélioration (ignorée sans `existing_text`).
            Vide ou `None` : consigne par défaut `improve_default_instruction.md`.
        sources: Bloc de matière tiré des documents de référence (voir
            `sources_assign.sources_for_section`), vide s'il n'y en a pas.

    Returns:
        Le texte brut renvoyé par le modèle (marqueur de fin inclus).
    """
    sous_sections = "\n".join(f"- {_describe(ss)}" for ss in section.sous_sections)
    values = dict(
        numero=section.numero,
        titre=section.titre,
        intitule=section.intitule,
        role_note=_role_note(section),
        description=section.description,
        sous_sections=sous_sections,
        digest=digest,
        plan=plan,
        sources=sources,
    )
    if existing_text is None:
        template = string.Template(_read_prompt("section_instruction.md"))
        prompt = template.substitute(**values)
    else:
        consigne = (instruction or "").strip() or _read_prompt("improve_default_instruction.md").strip()
        template = string.Template(_read_prompt("improve_instruction.md"))
        prompt = template.substitute(**values, consigne=consigne, contenu_existant=existing_text.strip())
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    return _client(cfg, "model_write").chat(messages)


def _coverage_criterion(must_cover: list[Unite]) -> dict:
    """Critère bloquant exigeant que la matière de l'auteur soit traitée ou écartée explicitement.

    Args:
        must_cover: Unités « À COUVRIR » montrées au rédacteur.

    Returns:
        Un critère au format de `requirements.yml`.
    """
    items = "\n".join(f"  - [{u.id}] {u.enonce.strip()}" for u in must_cover)
    return {
        "id": COVERAGE_ID,
        "severity": "bloquant",
        "description": (
            "Chaque élément ci-dessous, fourni par l'auteur, doit être traité dans la section (idée développée, "
            "référence citée avec ses éléments, thème abordé) ou explicitement écarté par une ligne "
            "`<!-- écarté [identifiant] : motif -->` au motif recevable (hors sujet, douteux). "
            "Signale ici chaque élément ni traité ni écarté, avec son identifiant :\n" + items
        ),
    }


def _extract_discards(text: str) -> tuple[str, list[str]]:
    """Sépare le texte d'un chapitre des écarts déclarés par le rédacteur.

    Args:
        text: Texte final (sans marqueur de fin).

    Returns:
        Le texte sans les commentaires `<!-- écarté [id] : motif -->` et la liste `"id : motif"`.
        Un texte sans écart est renvoyé tel quel.
    """
    found = DISCARD_RE.findall(text)
    if not found:
        return text, []
    return DISCARD_RE.sub("", text).strip(), [f"{i.strip()} : {m.strip()}" for i, m in found]


def _judge_section(
    cfg: AppConfig,
    section: SectionState,
    section_text: str,
    requirements: dict,
    *,
    must_cover: list[Unite] = (),
    system_prompt: str = "",
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
        must_cover: Unités de matière que le texte doit traiter ou écarter ; ajoute le critère
            bloquant `couverture_sources` si la liste n'est pas vide.
        system_prompt: Prompt système donné au rédacteur ; montré au juge pour qu'il puisse
            vérifier le style, la langue et la typographie exigés. Vide : bloc omis.

    Returns:
        Le verdict du juge, éventuellement corrigé par le garde-fou local.

    Raises:
        ParsingError: Si le modèle ne produit pas de JSON valide conforme
            au schéma après plusieurs tentatives.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    criteria = criteria_for_partie(requirements, section.partie_titre)
    if must_cover:
        criteria = [*criteria, _coverage_criterion(list(must_cover))]
    template = string.Template(_read_prompt("judge_instruction.md"))
    rules = (
        f"## Règles de rédaction données au rédacteur\n\n<regles>\n{system_prompt.strip()}\n</regles>"
        if system_prompt.strip()
        else ""
    )
    instruction = template.substitute(
        requirements=render_criteria(criteria),
        section_text=section_text,
        intitule=section.intitule,
        sous_sections="\n".join(f"- {label}" for label in _labels(section)) or "(aucune)",
        regles=rules,
    )
    verdict = call_structured(
        _client(cfg, "model_judge"), [{"role": "user", "content": instruction}], JudgeVerdict, max_attempts=3
    )

    must_block = blocking_ids(criteria)
    if verdict.verdict == "accept" and any(issue.id in must_block for issue in verdict.issues):
        verdict.verdict = "revise"
    return verdict


def _rewrite_section(
    cfg: AppConfig,
    section: SectionState,
    section_text: str,
    verdict: JudgeVerdict,
    sources: str = "",
    system_prompt: str = "",
) -> str:
    """Demande au modèle réécrivain une version corrigée de la section.

    Args:
        cfg: Configuration applicative résolue.
        section: Section concernée (utilisée pour le numéro dans le marqueur de fin).
        section_text: Texte original à corriger.
        verdict: Verdict du juge contenant les problèmes à corriger.
        sources: Bloc de matière des documents de référence, pour que le réécrivain puisse
            traiter les éléments signalés comme oubliés ; vide s'il n'y en a pas.
        system_prompt: Prompt système du sujet (persona, langue, style, typographie) : la version
            réécrite est souvent la version finale, elle doit suivre les mêmes règles. Vide : omis.

    Returns:
        Le texte brut réécrit par le modèle.
    """
    issues_text = "\n".join(f"- [{i.severity}] `{i.id}` : {i.detail}" for i in verdict.issues)
    issues_text = issues_text or "(aucun détail fourni)"
    template = string.Template(_read_prompt("rewrite_instruction.md"))
    instruction = template.substitute(
        section_text=section_text,
        issues=issues_text,
        numero=section.numero,
        sources=f"{sources.strip()}\n\n{REWRITE_SOURCES_NOTE}" if sources.strip() else "",
    )
    messages = [{"role": "system", "content": system_prompt}] if system_prompt.strip() else []
    return _client(cfg, "model_rewriter").chat([*messages, {"role": "user", "content": instruction}])


def _draft_and_review(
    cfg: AppConfig,
    section: SectionState,
    requirements: dict,
    digest: str,
    plan: str,
    system_prompt: str,
    max_rewrite: int,
    *,
    existing_text: str | None = None,
    instruction: str | None = None,
    sources: str = "",
    must_cover: list[Unite] = (),
) -> tuple[str, JudgeVerdict, bool, int]:
    """Boucle rédaction → jugement → réécriture, commune à l'écriture et à l'amélioration.

    Args:
        cfg: Configuration applicative résolue.
        section: Section à traiter.
        requirements: Exigences du sujet (voir `Subject.requirements`).
        digest: Résumé mémoire du manuel déjà rédigé.
        plan: Plan complet de l'ouvrage (voir `state.render_plan`).
        system_prompt: Prompt système du sujet.
        max_rewrite: Nombre maximal de cycles de réécriture après un rejet.
        existing_text: Texte à améliorer (voir `_draft_section`), ou `None`.
        instruction: Consigne d'amélioration (voir `_draft_section`).
        sources: Bloc de matière des documents de référence (voir `_draft_section`).
        must_cover: Unités à traiter ou écarter, exigées par le juge (voir `_judge_section`).

    Returns:
        Un tuple `(texte_final_sans_marqueur, dernier_verdict, marqueur_present, tentatives)`.
    """
    text = _draft_section(
        cfg, section, digest, plan, system_prompt, existing_text=existing_text, instruction=instruction, sources=sources
    )
    verdict = _judge_section(cfg, section, text, requirements, must_cover=must_cover, system_prompt=system_prompt)
    attempts = 1

    while verdict.verdict == "revise" and attempts <= max_rewrite:
        text = _rewrite_section(cfg, section, text, verdict, sources, system_prompt)
        verdict = _judge_section(cfg, section, text, requirements, must_cover=must_cover, system_prompt=system_prompt)
        attempts += 1

    final_text, marker_ok = _strip_end_marker(text, section.numero)
    return final_text, verdict, marker_ok, attempts


def _fold_into_memory(
    cfg: AppConfig,
    output_dir: Path,
    section: SectionState,
    final_text: str,
    memory_lock: threading.Lock | None,
) -> None:
    """Intègre une section terminée dans le résumé mémoire du manuel.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        section: Section qui vient d'être écrite ou améliorée.
        final_text: Texte final de la section (sans marqueur).
        memory_lock: Verrou de la mémoire en exécution parallèle, ou `None`.
    """
    think_client = _client(cfg, "model_think")
    with memory_lock or nullcontext():
        # Relit le digest le plus récent (potentiellement mis à jour entre-temps par une autre
        # section traitée en parallèle) pour ne pas écraser sa contribution mémoire.
        current_digest = load_digest(output_dir)
        new_digest = update_digest(think_client, current_digest, section.titre, final_text)
        new_digest = ensure_budget(think_client, new_digest)
        save_digest(output_dir, new_digest)


def write_section(
    cfg: AppConfig,
    output_dir: Path,
    state: ManualState,
    section: SectionState,
    requirements: dict,
    max_rewrite: int = 2,
    *,
    system_prompt: str,
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
        system_prompt: Prompt système du sujet, envoyé au rédacteur.
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
    matter = section_matter(cfg, output_dir, section)
    final_text, verdict, marker_ok, attempts = _draft_and_review(
        cfg,
        section,
        requirements,
        digest,
        render_plan(state, section.numero),
        system_prompt,
        max_rewrite,
        sources=matter.text,
        must_cover=matter.must_cover,
    )
    accepted = verdict.verdict == "accept" and marker_ok
    final_text, discards = _extract_discards(final_text)
    section.sources_total, section.sources_ecartees = len(matter.must_cover), discards

    (output_dir / section.filename).write_text(final_text + "\n", encoding="utf-8")

    section.status = "done" if accepted else "failed"
    section.attempts = attempts
    section.last_verdict = verdict.verdict if marker_ok else "revise (marqueur de fin manquant)"
    with state_lock or nullcontext():
        save_state(output_dir, state)

    _fold_into_memory(cfg, output_dir, section, final_text, memory_lock)
    return section


@dataclass
class ImproveResult:
    """Résultat de l'amélioration d'une section.

    Attributes:
        section: La section traitée.
        accepted: `True` si la nouvelle version a été acceptée et a remplacé
            l'ancienne.
        path: Fichier de la section si acceptée, sinon fichier de la version
            candidate (`NN_titre.candidate.md`), l'original restant intact.
        backup: Sauvegarde de l'ancienne version (`.bak`) si acceptée, sinon `None`.
    """

    section: SectionState
    accepted: bool
    path: Path
    backup: Path | None


def improve_section(
    cfg: AppConfig,
    output_dir: Path,
    state: ManualState,
    section: SectionState,
    requirements: dict,
    max_rewrite: int = 2,
    *,
    system_prompt: str,
    instruction: str | None = None,
    state_lock: threading.Lock | None = None,
    memory_lock: threading.Lock | None = None,
) -> ImproveResult:
    """Améliore une section existante en s'en servant d'amorce pour une nouvelle génération.

    Même principe que `write_section` (rédaction → jugement → réécriture), mais
    le rédacteur reçoit la version actuelle et une consigne. La nouvelle version
    ne remplace l'ancienne que si elle est acceptée (juge et marqueur de fin) ;
    sinon l'original, le statut et la mémoire restent inchangés et la version
    candidate est écrite à côté.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        state: État complet du manuel (muté en place si acceptée).
        section: Section à améliorer.
        requirements: Exigences du sujet (voir `Subject.requirements`).
        max_rewrite: Nombre maximal de cycles de réécriture après un rejet.
        system_prompt: Prompt système du sujet.
        instruction: Consigne d'amélioration ; vide ou `None` : consigne par défaut.
        state_lock: Verrou du manifeste en exécution parallèle, ou `None`.
        memory_lock: Verrou de la mémoire en exécution parallèle, ou `None`.

    Returns:
        Le résultat de l'amélioration.

    Raises:
        GeneratorError: Si la section n'a pas encore de contenu à améliorer.
    """
    path = output_dir / section.filename
    if not path.is_file():
        raise GeneratorError(
            f"La section {section.numero} n'a pas encore de contenu à améliorer : lance `manual write -s {section.numero}`."
        )
    existing_text = path.read_text(encoding="utf-8")
    digest = load_digest(output_dir)
    matter = section_matter(cfg, output_dir, section)
    final_text, verdict, marker_ok, attempts = _draft_and_review(
        cfg,
        section,
        requirements,
        digest,
        render_plan(state, section.numero),
        system_prompt,
        max_rewrite,
        existing_text=existing_text,
        instruction=instruction,
        sources=matter.text,
        must_cover=matter.must_cover,
    )
    final_text, discards = _extract_discards(final_text)

    if not (verdict.verdict == "accept" and marker_ok):
        candidate = path.with_name(path.name.removesuffix(".md") + ".candidate.md")
        candidate.write_text(final_text + "\n", encoding="utf-8")
        return ImproveResult(section=section, accepted=False, path=candidate, backup=None)

    backup = path.with_name(path.name + ".bak")
    shutil.copyfile(path, backup)
    path.write_text(final_text + "\n", encoding="utf-8")
    section.status = "done"
    section.attempts = attempts
    section.last_verdict = verdict.verdict
    section.sources_total, section.sources_ecartees = len(matter.must_cover), discards
    with state_lock or nullcontext():
        save_state(output_dir, state)
    _fold_into_memory(cfg, output_dir, section, final_text, memory_lock)
    return ImproveResult(section=section, accepted=True, path=path, backup=backup)


def _load_state_for_subject(output_dir: Path, subject: Subject) -> ManualState:
    """Charge le manifeste en vérifiant qu'il correspond au sujet demandé.

    Args:
        output_dir: Répertoire de sortie du manuel.
        subject: Sujet attendu.

    Returns:
        L'état du manuel.

    Raises:
        GeneratorError: Si aucun manifeste n'existe, ou s'il a été généré
            pour un autre sujet (un manifeste sans sujet est accepté).
    """
    if not state_exists(output_dir):
        raise GeneratorError("Aucune table des matières générée. Lance d'abord `manual init`.")
    state = load_state(output_dir)
    if state.subject is not None and state.subject != subject.slug:
        raise GeneratorError(
            f"Ce manuel a été généré pour le sujet {state.subject!r}, pas {subject.slug!r} "
            f"(répertoire {output_dir}). Utilise --subject {state.subject} ou un autre --output."
        )
    return state


def _prepare_sources(cfg: AppConfig, output_dir: Path, subject: Subject, state: ManualState) -> None:
    """Met à jour l'analyse et l'affectation des documents de référence, s'il y en a.

    Sans document (et sans index d'une analyse passée), ne fait rien et ne coûte aucun appel.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        subject: Sujet (contient `sources/`).
        state: État du manuel (plan, pour l'affectation).

    Raises:
        SourcesError: Si un document est illisible ou une carte invalide.
        ParsingError: Si le modèle ne renvoie pas de réponse valide.
    """
    if not list_source_files(subject.directory) and not load_index(output_dir).fichiers:
        return
    refresh_index(cfg, subject.directory, output_dir, subject_context(subject))
    ensure_assignment(cfg, state, load_index(output_dir), output_dir)


def _matter_for_plan(cfg: AppConfig, output_dir: Path, subject: Subject) -> str:
    """Résumé des documents de référence à joindre aux prompts du plan, vide s'il n'y en a pas.

    Analyse d'abord les documents nouveaux ou modifiés (cache par empreinte).

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        subject: Sujet (contient `sources/`).

    Returns:
        Le résumé par thème (voir `sources_assign.plan_summary`), ou une chaîne vide.
    """
    if not list_source_files(subject.directory) and not load_index(output_dir).fichiers:
        return ""
    refresh_index(cfg, subject.directory, output_dir, subject_context(subject))
    return plan_summary(load_index(output_dir), int(cfg.setting("sources", "max_prompt_chars")))


def run_improve(
    cfg: AppConfig,
    output_dir: Path,
    subject: Subject,
    only_numeros: list[int],
    instruction: str | None = None,
    max_rewrite: int = 2,
    workers: int = 4,
) -> list[ImproveResult]:
    """Améliore une sélection de sections, en parallèle si plusieurs sont ciblées.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        subject: Sujet fournissant le prompt système et les critères du juge.
        only_numeros: Numéros des sections à améliorer.
        instruction: Consigne d'amélioration commune ; vide ou `None` : consigne par défaut.
        max_rewrite: Nombre maximal de cycles de réécriture par section.
        workers: Nombre de sections traitées en parallèle.

    Returns:
        Les résultats, dans l'ordre de `only_numeros`.

    Raises:
        GeneratorError: Si aucun manifeste n'existe, s'il est d'un autre sujet,
            ou si une section ciblée n'a pas encore de contenu (vérifié avant
            tout appel au modèle).
        KeyError: Si `only_numeros` contient un numéro de section inconnu.
    """
    state = _load_state_for_subject(output_dir, subject)
    targets = [state.section_by_numero(n) for n in only_numeros]
    empty = [str(s.numero) for s in targets if not (output_dir / s.filename).is_file()]
    if empty:
        raise GeneratorError(
            f"Section(s) sans contenu à améliorer : {', '.join(empty)}. Lance d'abord `manual write -s ...`."
        )
    _prepare_sources(cfg, output_dir, subject, state)

    worker_fn = partial(
        improve_section,
        cfg,
        output_dir,
        state,
        requirements=subject.requirements(),
        max_rewrite=max_rewrite,
        system_prompt=subject.system_prompt(),
        instruction=instruction,
        state_lock=threading.Lock(),
        memory_lock=threading.Lock(),
    )
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets)))) as executor:
        return list(executor.map(worker_fn, targets))


def _toc_preserving_schema(locked: list[SectionState]) -> type[TocSchema]:
    """Construit un schéma de TOC qui impose de conserver les chapitres déjà rédigés.

    Le message de l'erreur de validation est renvoyé au modèle par
    `parsing.call_structured`, qui lui redemande alors une correction.

    Args:
        locked: Sections déjà rédigées, à retrouver à l'identique (numéro,
            titre, sous-sections) dans la table des matières proposée.

    Returns:
        Une sous-classe de `TocSchema` vérifiant en plus la numérotation
        consécutive des chapitres et la présence des chapitres figés.
    """

    class PreservingToc(GeneratedTocSchema):
        @model_validator(mode="after")
        def _keep_written_chapters(self) -> GeneratedTocSchema:
            chapters = [c for partie in self.parties for c in partie.chapitres]
            numeros = sorted(c.numero for c in chapters)
            if numeros != list(range(1, len(numeros) + 1)):
                raise ValueError("Les numéros de chapitres doivent être consécutifs de 1 à N, sans trou ni doublon.")
            by_numero = {c.numero: c for c in chapters}
            problems = []
            for section in locked:
                chapter = by_numero.get(section.numero)
                if chapter is None:
                    problems.append(f"le chapitre {section.numero} « {section.titre} » (déjà rédigé) a disparu")
                    continue
                subs = [ss.label for ss in chapter.sous_sections]
                locked_subs = _labels(section)
                if chapter.titre != section.titre or subs != locked_subs:
                    problems.append(
                        f"le chapitre {section.numero} (déjà rédigé) doit rester « {section.titre} » "
                        f"avec exactement les sous-sections {locked_subs}"
                    )
            if problems:
                raise ValueError(" ; ".join(problems))
            return self

    return PreservingToc


@dataclass
class TocImproveResult:
    """Résultat de l'amélioration de la table des matières.

    Attributes:
        state: État du manuel après amélioration (inchangé si `modified` est faux).
        modified: `True` si la table des matières a été modifiée et réécrite.
        changed: Sections nouvelles ou modifiées, à (re)rédiger.
        removed: Anciennes sections dont le couple (numéro, titre) n'existe plus.
        orphan_files: Fichiers de chapitres existants que la nouvelle table
            n'utilise plus (laissés en place, jamais supprimés).
        orphan_criteria: Titres de parties portant des critères propres au
            sujet qui n'existent plus dans la nouvelle table des matières.
        history_dir: Dossier d'archivage de la version précédente, ou `None`.
    """

    state: ManualState
    modified: bool
    changed: list[SectionState]
    removed: list[SectionState]
    orphan_files: list[str]
    orphan_criteria: list[str]
    history_dir: Path | None


def _archive_toc(output_dir: Path) -> Path:
    """Archive le manifeste et la TOC lisible actuels dans `toc_history/<horodatage>/`.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le dossier d'archive créé (suffixé si l'horodatage existe déjà).
    """
    history_root = output_dir / "toc_history"
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = history_root / base
    counter = 2
    while target.exists():
        target = history_root / f"{base}-{counter}"
        counter += 1
    target.mkdir(parents=True)
    for source in (manifest_path(output_dir), toc_path(output_dir), output_dir / "00_toc.md"):
        if source.is_file():
            shutil.copyfile(source, target / source.name)
    return target


def improve_toc(
    cfg: AppConfig,
    output_dir: Path,
    subject: Subject,
    instruction: str | None = None,
) -> TocImproveResult:
    """Améliore la table des matières en partant de l'actuelle, sans rien perdre.

    Le modèle reçoit la table actuelle, la consigne et la liste des chapitres
    déjà rédigés, qu'il doit conserver à l'identique. Les chapitres inchangés
    gardent leur avancement ; les chapitres nouveaux ou modifiés repassent en
    attente. Les fichiers de chapitres et la mémoire ne sont jamais touchés,
    et la version précédente est archivée dans `toc_history/`.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel (avec son manifeste).
        subject: Sujet fournissant le prompt système.
        instruction: Consigne d'amélioration ; vide ou `None` : consigne par défaut.

    Returns:
        Le résultat, avec le détail des changements.

    Raises:
        GeneratorError: Si aucun manifeste n'existe ou s'il est d'un autre sujet.
        ParsingError: Si le modèle ne produit pas une table valide qui
            respecte les chapitres figés après plusieurs tentatives (rien
            n'est alors modifié).
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    state = _load_state_for_subject(output_dir, subject)
    locked = [s for s in state.sections if s.status == "done" and s.role == "chapitre"]
    locked_text = (
        "\n".join(
            f"- Chapitre {s.numero} « {s.titre} » — sous-sections : {', '.join(_labels(s)) or '(aucune)'}"
            for s in locked
        )
        or "(Aucun chapitre n'est encore rédigé : la table des matières est entièrement modifiable.)"
    )
    consigne = (instruction or "").strip() or _read_prompt("toc_improve_default_instruction.md").strip()
    template = string.Template(_read_prompt("toc_improve_instruction.md"))
    prompt = template.substitute(
        toc_actuelle=state.toc.model_dump_json(indent=2), consigne=consigne, chapitres_figes=locked_text
    )
    messages = [
        {"role": "system", "content": subject.system_prompt()},
        {"role": "user", "content": "\n\n".join(filter(None, [prompt, _matter_for_plan(cfg, output_dir, subject)]))},
    ]
    proposal = call_structured(
        _client(cfg, "model_write"), messages, _toc_preserving_schema(locked), max_attempts=3
    )
    new_toc = renumber_toc(TocSchema.model_validate(proposal.model_dump()))
    if new_toc == state.toc:
        return TocImproveResult(state, False, [], [], [], [], None)

    new_state = build_manual_state(new_toc, subject=state.subject)
    old_by_numero = {s.numero: s for s in state.sections}
    changed = []
    for section in new_state.sections:
        old = old_by_numero.get(section.numero)
        if old is not None and old.titre == section.titre and _labels(old) == _labels(section):
            section.status, section.attempts, section.last_verdict = old.status, old.attempts, old.last_verdict
            section.sources_total, section.sources_ecartees = old.sources_total, old.sources_ecartees
        else:
            changed.append(section)
    kept_keys = {(s.numero, s.titre) for s in new_state.sections}
    removed = [s for s in state.sections if (s.numero, s.titre) not in kept_keys]
    new_filenames = {s.filename for s in new_state.sections}
    orphan_files = [s.filename for s in state.sections if s.filename not in new_filenames and (output_dir / s.filename).is_file()]
    new_titles = {partie.titre for partie in new_toc.parties}
    orphan_criteria = [title for title in subject.requirements()["parties"] if title not in new_titles]

    history_dir = _archive_toc(output_dir)
    save_state(output_dir, new_state)
    _write_toc_markdown(output_dir, new_state)
    _prepare_sources(cfg, output_dir, subject, new_state)
    return TocImproveResult(new_state, True, changed, removed, orphan_files, orphan_criteria, history_dir)


def run_write(
    cfg: AppConfig,
    output_dir: Path,
    subject: Subject,
    only_numeros: list[int] | None = None,
    max_rewrite: int = 2,
    workers: int = 4,
) -> list[SectionState]:
    """Rédige une sélection de sections, en parallèle si plusieurs sont ciblées.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel (doit déjà contenir un
            manifeste produit par `generate_toc`).
        subject: Sujet fournissant le prompt système et les critères du juge.
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
        GeneratorError: Si aucun manifeste n'existe encore dans `output_dir`,
            ou s'il a été généré pour un autre sujet que `subject`.
        KeyError: Si `only_numeros` contient un numéro de section inconnu.
    """
    state = _load_state_for_subject(output_dir, subject)
    _write_toc_markdown(output_dir, state)  # reflète une éventuelle édition manuelle de toc.yml
    requirements = subject.requirements()
    system_prompt = subject.system_prompt()

    if only_numeros is not None:
        targets = [state.section_by_numero(n) for n in only_numeros]
    else:
        targets = [s for s in state.sections if s.status != "done"]

    if not targets:
        return []
    _prepare_sources(cfg, output_dir, subject, state)

    state_lock = threading.Lock()
    memory_lock = threading.Lock()
    worker_fn = partial(
        write_section,
        cfg,
        output_dir,
        state,
        requirements=requirements,
        max_rewrite=max_rewrite,
        system_prompt=system_prompt,
        state_lock=state_lock,
        memory_lock=memory_lock,
    )

    # L'introduction et la conclusion passent après les chapitres : elles s'appuient sur la mémoire du manuel écrit.
    phases = [[t for t in targets if t.role == "chapitre"], [t for t in targets if t.role != "chapitre"]]
    done: dict[int, SectionState] = {}
    for phase in phases:
        if not phase:
            continue
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(phase)))) as executor:
            for section in executor.map(worker_fn, phase):
                done[section.numero] = section
    return [done[t.numero] for t in targets]
