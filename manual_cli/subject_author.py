"""Rédaction assistée des sujets : création, retouche et critères par partie.

Trois opérations pilotées par `model_write`, chacune produisant du JSON
strict validé (voir `parsing.call_structured`) :

- `generate_subject` : crée un sujet complet à partir d'un court descriptif ;
- `refine_subject` : retouche un sujet existant selon une consigne en langage naturel ;
- `propose_partie_criteria` : propose des critères de relecture par grande
  partie, une fois la table des matières générée.

Aucune sortie du modèle n'est écrite sans avoir été validée : un échec
laisse les fichiers existants intacts.
"""

from __future__ import annotations

import re
import shutil
import string
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from .config import AppConfig
from .parsing import call_structured
from .providers import OllamaCloudClient
from .requirements_loader import DEFAULT_REQUIREMENTS_PATH, load_requirements, render_criteria
from .state import load_state, state_exists
from .subjects import (
    PROMPTS_DIR,
    REQUIREMENTS_FILENAME,
    REQUIREMENTS_STUB,
    SUBJECT_FILENAME,
    SUBJECTS_DIR,
    Subject,
    SubjectError,
    SubjectSpec,
    dump_yaml,
    load_subject,
    load_yaml_mapping,
    validate_slug,
)

CRITERION_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class Criterion(BaseModel):
    """Un critère de relecture proposé par le modèle.

    Attributes:
        id: Identifiant en snake_case, unique parmi tous les critères du sujet.
        description: Ce que la section doit contenir, en une phrase.
        severity: `"bloquant"` (force une réécriture) ou `"recommande"`.
    """

    id: str
    description: str
    severity: Literal["bloquant", "recommande"]

    @field_validator("id")
    @classmethod
    def _id_is_snake_case(cls, value: str) -> str:
        """Refuse un identifiant qui ne serait pas en snake_case minuscule."""
        if not re.match(CRITERION_ID_PATTERN, value):
            raise ValueError("identifiant attendu en snake_case (minuscules, chiffres, soulignés)")
        return value

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        """Refuse une description vide."""
        if not value.strip():
            raise ValueError("description vide")
        return value


class SubjectDraft(SubjectSpec):
    """Sujet complet proposé par le modèle, avec ses critères propres.

    Attributes:
        criteres: Critères de relecture propres au sujet (toutes sections).
    """

    criteres: list[Criterion] = []


class PartieCriteria(BaseModel):
    """Critères de relecture proposés par le modèle pour des parties de la TOC.

    Attributes:
        parties: Critères par titre exact de partie.
    """

    parties: dict[str, list[Criterion]] = {}


def _client(cfg: AppConfig) -> OllamaCloudClient:
    """Construit le client LLM du rôle `model_write`.

    Args:
        cfg: Configuration applicative résolue.

    Returns:
        Un client prêt à rédiger le cadrage d'un sujet.
    """
    return OllamaCloudClient(cfg.role("model_write"), role="model_write")


def _render(template_name: str, **values: str) -> str:
    """Remplit un gabarit de `prompts/` avec `string.Template`.

    Args:
        template_name: Nom du fichier de gabarit.
        **values: Valeurs des placeholders.

    Returns:
        Le texte rempli.
    """
    template = string.Template((PROMPTS_DIR / template_name).read_text(encoding="utf-8"))
    return template.substitute(**values)


def _messages(user_content: str) -> list[dict]:
    """Assemble la conversation : prompt système d'éditeur puis consigne.

    Args:
        user_content: Instruction complète de la tâche.

    Returns:
        Les messages à envoyer au modèle.
    """
    system = (PROMPTS_DIR / "author_system_prompt.md").read_text(encoding="utf-8")
    return [{"role": "system", "content": system}, {"role": "user", "content": user_content}]


def _backup(path: Path) -> None:
    """Copie un fichier existant en `<nom>.bak` avant de le réécrire.

    Args:
        path: Fichier à sauvegarder (sans effet s'il n'existe pas).
    """
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + ".bak"))


def _criteria_dicts(criteria: list[Criterion]) -> list[dict]:
    """Convertit des critères validés en dictionnaires prêts pour le YAML.

    Args:
        criteria: Critères issus d'une réponse du modèle.

    Returns:
        Une liste de dictionnaires `id` / `description` / `severity`.
    """
    return [c.model_dump() for c in criteria]


def _shared_criteria() -> list[dict]:
    """Charge les critères communs à tous les sujets.

    Returns:
        La liste `generic` de `requirements/requirements.yml`.
    """
    return load_requirements(DEFAULT_REQUIREMENTS_PATH)["generic"]


def generate_subject(cfg: AppConfig, slug: str, brief: str, subjects_dir: Path = SUBJECTS_DIR) -> Path:
    """Crée un sujet complet à partir d'un court descriptif.

    Args:
        cfg: Configuration applicative résolue.
        slug: Identifiant du nouveau sujet.
        brief: Descriptif libre du manuel voulu (une ou deux phrases).
        subjects_dir: Dossier contenant les sujets.

    Returns:
        Le dossier créé, avec `subject.yml` et `requirements.yml`.

    Raises:
        SubjectError: Si l'identifiant est invalide ou déjà pris, si le
            descriptif est vide, ou si un critère proposé reprend
            l'identifiant d'un critère commun ou d'un autre critère proposé.
        ParsingError: Si le modèle ne produit pas de sujet valide après
            plusieurs tentatives.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    validate_slug(slug)
    if not brief.strip():
        raise SubjectError("Le brief est vide : décris en une phrase le manuel voulu.")
    directory = subjects_dir / slug
    if directory.exists():
        raise SubjectError(f"Le sujet {slug!r} existe déjà : {directory}")

    shared = _shared_criteria()
    instruction = _render(
        "subject_generate_instruction.md", brief=brief.strip(), criteres_communs=render_criteria(shared)
    )
    draft = call_structured(_client(cfg), _messages(instruction), SubjectDraft, max_attempts=3)

    shared_ids = {c["id"] for c in shared}
    clashing = sorted(c.id for c in draft.criteres if c.id in shared_ids)
    if clashing:
        raise SubjectError(
            f"Le modèle a proposé des critères déjà communs à tous les sujets : {', '.join(clashing)}. Relance la commande."
        )

    ids = [c.id for c in draft.criteres]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SubjectError(f"Le modèle a proposé des critères en double : {', '.join(duplicates)}. Relance la commande.")

    directory.mkdir(parents=True)
    spec = draft.model_dump(exclude={"criteres"})
    (directory / SUBJECT_FILENAME).write_text(dump_yaml(spec), encoding="utf-8")
    requirements_text = (
        dump_yaml({"generic": _criteria_dicts(draft.criteres)}) if draft.criteres else REQUIREMENTS_STUB
    )
    (directory / REQUIREMENTS_FILENAME).write_text(requirements_text, encoding="utf-8")
    return directory


def refine_subject(cfg: AppConfig, slug: str, instruction: str, subjects_dir: Path = SUBJECTS_DIR) -> list[str]:
    """Retouche le `subject.yml` d'un sujet selon une consigne en langage naturel.

    Args:
        cfg: Configuration applicative résolue.
        slug: Identifiant du sujet à retoucher.
        instruction: Consigne de l'auteur (ex. « plus décontracté, sans juridique »).
        subjects_dir: Dossier contenant les sujets.

    Returns:
        Les noms des champs modifiés (liste vide si le modèle n'a rien changé,
        auquel cas aucun fichier n'est touché). L'ancienne version est
        conservée dans `subject.yml.bak`.

    Raises:
        SubjectError: Si le sujet est introuvable ou invalide, ou si la
            consigne est vide.
        ParsingError: Si le modèle ne renvoie pas un sujet valide après
            plusieurs tentatives (le fichier reste alors intact).
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    if not instruction.strip():
        raise SubjectError("La consigne est vide : décris la modification voulue.")
    subject = load_subject(slug, subjects_dir)
    current = subject.model_dump(include=set(SubjectSpec.model_fields))
    prompt = _render("subject_refine_instruction.md", current=dump_yaml(current).rstrip(), instruction=instruction.strip())
    updated = call_structured(_client(cfg), _messages(prompt), SubjectSpec, max_attempts=3).model_dump()

    changed = [name for name in SubjectSpec.model_fields if current[name] != updated[name]]
    if not changed:
        return []
    path = subject.directory / SUBJECT_FILENAME
    _backup(path)
    path.write_text(dump_yaml(updated), encoding="utf-8")
    return changed


def propose_partie_criteria(
    cfg: AppConfig, subject: Subject, output_dir: Path, force: bool = False
) -> dict[str, list[str]]:
    """Propose et enregistre des critères de relecture par partie de la TOC.

    Les critères sont ajoutés au `requirements.yml` du sujet, sous `parties`,
    avec pour clés les titres exacts des parties de la table des matières
    générée dans `output_dir`.

    Args:
        cfg: Configuration applicative résolue.
        subject: Sujet concerné.
        output_dir: Répertoire de sortie contenant le manifeste de ce sujet.
        force: Si vrai, remplace les critères existants des parties
            proposées ; sinon les parties déjà pourvues sont laissées telles quelles.

    Returns:
        Les identifiants de critères ajoutés, par titre de partie (vide si
        rien n'a été ajouté, auquel cas aucun fichier n'est touché).

    Raises:
        SubjectError: Si aucune table des matières n'existe, si elle a été
            générée pour un autre sujet, si le modèle cite une partie
            inconnue ou si un identifiant de critère est déjà pris.
        ParsingError: Si le modèle ne produit pas de JSON valide.
        ProviderError: Si l'appel au modèle échoue définitivement.
    """
    if not state_exists(output_dir):
        raise SubjectError(f"Aucune table des matières dans {output_dir}. Lance d'abord `manual init`.")
    state = load_state(output_dir)
    if state.subject is not None and state.subject != subject.slug:
        raise SubjectError(
            f"La table des matières de {output_dir} a été générée pour le sujet {state.subject!r}, "
            f"pas {subject.slug!r}."
        )

    requirements = subject.requirements()
    titles = [partie.titre for partie in state.toc.parties]
    listing = "\n".join(
        f"- **{partie.titre}** : " + ", ".join(chapitre.titre for chapitre in partie.chapitres)
        for partie in state.toc.parties
    )
    spec_yaml = dump_yaml(subject.model_dump(include=set(SubjectSpec.model_fields))).rstrip()
    prompt = _render(
        "partie_criteria_instruction.md",
        subject_yaml=spec_yaml,
        parties=listing,
        criteres_existants=render_criteria(requirements["generic"]),
    )
    proposal = call_structured(_client(cfg), _messages(prompt), PartieCriteria, max_attempts=3)

    unknown = [title for title in proposal.parties if title not in titles]
    if unknown:
        raise SubjectError(
            f"Le modèle a cité des parties absentes de la table des matières : {', '.join(unknown)}. Relance la commande."
        )
    new = {
        title: criteria
        for title, criteria in proposal.parties.items()
        if criteria and (force or title not in requirements["parties"])
    }
    if not new:
        return {}

    kept = {t: cs for t, cs in requirements["parties"].items() if t not in new}
    taken = {c["id"] for c in requirements["generic"]} | {c["id"] for cs in kept.values() for c in cs}
    for criteria in new.values():
        for criterion in criteria:
            if criterion.id in taken:
                raise SubjectError(f"Identifiant de critère déjà pris : {criterion.id}. Relance la commande.")
            taken.add(criterion.id)

    path = subject.directory / REQUIREMENTS_FILENAME
    document = load_yaml_mapping(path, allow_missing=True)
    document["parties"] = {**(document.get("parties") or {}), **{t: _criteria_dicts(cs) for t, cs in new.items()}}
    _backup(path)
    path.write_text(dump_yaml(document), encoding="utf-8")
    return {title: [c.id for c in criteria] for title, criteria in new.items()}
