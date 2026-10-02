"""Gestion des sujets de manuel : un sujet = un dossier `subjects/<identifiant>/`.

Un sujet décrit *de quoi* parle le manuel (rôle de l'auteur, public, niveau,
ton, plan directeur...) dans un fichier court `subject.yml`. Les prompts
génériques de `prompts/` (format de sortie, marqueur de fin, schéma JSON du
plan) sont communs à tous les sujets et complétés par ces champs. Deux
surcharges facultatives permettent un contrôle total : un `system_prompt.md`
et/ou un `toc_instruction.md` déposés dans le dossier du sujet remplacent
alors le gabarit générique. Un `requirements.yml` facultatif ajoute des
critères de relecture à ceux, communs, de `requirements/requirements.yml`.
"""

from __future__ import annotations

import re
import shutil
import string
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .requirements_loader import DEFAULT_REQUIREMENTS_PATH, load_requirements

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBJECTS_DIR = REPO_ROOT / "subjects"
PROMPTS_DIR = REPO_ROOT / "prompts"

SUBJECT_FILENAME = "subject.yml"
REQUIREMENTS_FILENAME = "requirements.yml"
SYSTEM_PROMPT_FILENAME = "system_prompt.md"
TOC_INSTRUCTION_FILENAME = "toc_instruction.md"
SUBJECT_TEMPLATE_PATH = PROMPTS_DIR / "subject_template.yml"

PLACEHOLDER = "À COMPLÉTER"
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SEVERITIES = ("bloquant", "recommande")

REQUIREMENTS_STUB = """\
# Critères propres à ce sujet, ajoutés aux critères communs (requirements/requirements.yml).
# severity: "bloquant" force une réécriture si non rempli ; "recommande" est signalé sans bloquer.
#
# generic:                 # critères ajoutés à toutes les sections
#   - id: exemple
#     description: "Une phrase décrivant ce que la section doit contenir."
#     severity: recommande
#
# parties:                 # critères par grande partie (clé = titre exact de la partie dans la TOC)
#   Fondamentaux:
#     - id: autre_exemple
#       description: "..."
#       severity: bloquant
"""


class SubjectError(Exception):
    """Sujet introuvable, incomplet ou mal formé."""


class SubjectSpec(BaseModel):
    """Champs du fichier `subject.yml`.

    Attributes:
        titre: Titre du sujet, tel qu'il figurera dans le manuel.
        langue: Langue de rédaction.
        role: Personnage de l'auteur (expertise, références).
        objectif: Ce que le manuel doit apporter.
        public: Lecteurs visés.
        niveau: Niveau atteint (ex. « débutant → expert »).
        ton: Ton de la rédaction.
        plan_directeur: Progression attendue des grandes parties.
        exclusions: Sujets à ne pas traiter (facultatif).
        instructions: Consignes libres supplémentaires (facultatif).
    """

    model_config = ConfigDict(extra="forbid")

    titre: str
    langue: str
    role: str
    objectif: str
    public: str
    niveau: str
    ton: str
    plan_directeur: str
    exclusions: list[str] = []
    instructions: str = ""

    @field_validator("titre", "langue", "role", "objectif", "public", "niveau", "ton", "plan_directeur")
    @classmethod
    def _required_text(cls, value: str) -> str:
        """Refuse un champ obligatoire vide ou encore égal au marqueur du gabarit."""
        if not value.strip():
            raise ValueError("champ obligatoire vide")
        if PLACEHOLDER in value:
            raise ValueError(f"contient encore « {PLACEHOLDER} »")
        return value

    @field_validator("instructions")
    @classmethod
    def _optional_text(cls, value: str) -> str:
        """Refuse le marqueur du gabarit laissé dans un champ facultatif."""
        if PLACEHOLDER in value:
            raise ValueError(f"contient encore « {PLACEHOLDER} »")
        return value

    @field_validator("exclusions")
    @classmethod
    def _exclusions_items(cls, value: list[str]) -> list[str]:
        """Refuse le marqueur du gabarit laissé dans une exclusion."""
        if any(PLACEHOLDER in item for item in value):
            raise ValueError(f"contient encore « {PLACEHOLDER} »")
        return value


class Subject(SubjectSpec):
    """Un sujet chargé depuis son dossier.

    Attributes:
        slug: Identifiant du sujet (nom du dossier, utilisé dans `--subject`).
        directory: Dossier du sujet.
    """

    slug: str
    directory: Path

    def system_prompt(self) -> str:
        """Construit le prompt système du sujet.

        Returns:
            Le contenu de `system_prompt.md` du sujet s'il existe (utilisé
            tel quel), sinon le gabarit générique `prompts/system_prompt.md`
            rempli avec les champs du sujet.
        """
        override = self.directory / SYSTEM_PROMPT_FILENAME
        if override.is_file():
            return override.read_text(encoding="utf-8")
        exclusions_section = ""
        if self.exclusions:
            items = "\n".join(f"- {item}" for item in self.exclusions)
            exclusions_section = f"\n# Hors périmètre\n\n{items}\n"
        instructions_section = ""
        if self.instructions.strip():
            instructions_section = f"\n# Consignes complémentaires\n\n{self.instructions.strip()}\n"
        template = string.Template((PROMPTS_DIR / SYSTEM_PROMPT_FILENAME).read_text(encoding="utf-8"))
        return template.substitute(
            role=self.role.strip(),
            objectif=self.objectif.strip(),
            public=self.public.strip(),
            niveau=self.niveau.strip(),
            ton=self.ton.strip(),
            langue=self.langue.strip(),
            exclusions_section=exclusions_section,
            instructions_section=instructions_section,
        )

    def toc_instruction(self) -> str:
        """Construit l'instruction de génération de la table des matières.

        Returns:
            Le contenu de `toc_instruction.md` du sujet s'il existe (utilisé
            tel quel), sinon le gabarit générique `prompts/toc_instruction.md`
            rempli avec le plan directeur du sujet.
        """
        override = self.directory / TOC_INSTRUCTION_FILENAME
        if override.is_file():
            return override.read_text(encoding="utf-8")
        template = string.Template((PROMPTS_DIR / TOC_INSTRUCTION_FILENAME).read_text(encoding="utf-8"))
        return template.substitute(plan_directeur=self.plan_directeur.strip())

    def requirements(self) -> dict:
        """Assemble les critères de relecture applicables au sujet.

        Returns:
            Les critères communs (`requirements/requirements.yml`) suivis de
            ceux du sujet : clé `"generic"` (liste concaténée) et clé
            `"parties"` (critères par partie, propres au sujet).

        Raises:
            SubjectError: Si le `requirements.yml` du sujet n'est pas un
                dictionnaire, si un critère est mal formé ou si un
                identifiant de critère apparaît deux fois.
        """
        base = load_requirements(DEFAULT_REQUIREMENTS_PATH)
        path = self.directory / REQUIREMENTS_FILENAME
        extra = load_yaml_mapping(path, allow_missing=True)
        extra_generic = extra.get("generic") or []
        _check_criteria(extra_generic, path)
        generic = list(base["generic"]) + extra_generic
        parties = extra.get("parties") or {}
        for partie, criteria in parties.items():
            _check_criteria(criteria, path, where=f"partie « {partie} »")
        seen: set[str] = set()
        for criterion in generic + [c for cs in parties.values() for c in cs]:
            if criterion["id"] in seen:
                raise SubjectError(f"Critère en double « {criterion['id']} » (voir {path}).")
            seen.add(criterion["id"])
        return {**base, "generic": generic, "parties": parties}


def load_yaml_mapping(path: Path, *, allow_missing: bool = False) -> dict:
    """Lit un fichier YAML censé contenir un dictionnaire.

    Args:
        path: Fichier à lire.
        allow_missing: Si vrai, un fichier absent ou vide donne `{}`. Sinon
            l'existence du fichier est vérifiée par l'appelant.

    Returns:
        Le dictionnaire lu.

    Raises:
        SubjectError: Si le fichier n'est pas du YAML valide ou ne contient
            pas un dictionnaire.
    """
    if allow_missing and not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SubjectError(f"YAML invalide dans {path} : {exc}") from exc
    if data is None and allow_missing:
        return {}
    if not isinstance(data, dict):
        raise SubjectError(f"Contenu invalide dans {path} : un dictionnaire YAML est attendu.")
    return data


def _check_criteria(criteria: object, path: Path, where: str = "critères communs") -> None:
    """Vérifie qu'une liste de critères est bien formée.

    Args:
        criteria: Valeur lue dans le YAML (liste de dictionnaires attendue).
        path: Fichier d'origine, pour le message d'erreur.
        where: Localisation lisible du bloc contrôlé.

    Raises:
        SubjectError: Si ce n'est pas une liste de critères ayant `id`,
            `description` et une `severity` connue.
    """
    if not isinstance(criteria, list):
        raise SubjectError(f"{where} : une liste de critères est attendue (voir {path}).")
    for criterion in criteria:
        if not isinstance(criterion, dict) or not {"id", "description", "severity"} <= criterion.keys():
            raise SubjectError(f"{where} : chaque critère doit avoir id, description et severity (voir {path}).")
        if criterion["severity"] not in SEVERITIES:
            raise SubjectError(
                f"{where} : severity « {criterion['severity']} » inconnue pour « {criterion['id']} » "
                f"(attendu : {', '.join(SEVERITIES)})."
            )


class _LiteralDumper(yaml.SafeDumper):
    """Dumper YAML écrivant les textes multilignes en blocs littéraux lisibles (`|`)."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    """Représente une chaîne multiligne en bloc littéral, les autres normalement."""
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_LiteralDumper.add_representer(str, _represent_str)


def dump_yaml(data: dict) -> str:
    """Sérialise un dictionnaire en YAML lisible et éditable à la main.

    Args:
        data: Dictionnaire à écrire.

    Returns:
        Le texte YAML : ordre des clés conservé, accents non échappés,
        textes multilignes en blocs littéraux.
    """
    return yaml.dump(data, Dumper=_LiteralDumper, allow_unicode=True, sort_keys=False, width=100)


def validate_slug(slug: str) -> None:
    """Vérifie qu'un identifiant de sujet est utilisable comme nom de dossier.

    Args:
        slug: Identifiant à contrôler.

    Raises:
        SubjectError: S'il n'est pas composé de minuscules, chiffres et
            tirets, ou s'il commence par un tiret.
    """
    if not SLUG_PATTERN.match(slug):
        raise SubjectError(
            f"Identifiant invalide : {slug!r} (minuscules, chiffres et tirets ; ne commence pas par un tiret)."
        )


def list_subjects(subjects_dir: Path = SUBJECTS_DIR) -> list[str]:
    """Liste les identifiants de sujets disponibles.

    Args:
        subjects_dir: Dossier contenant un sous-dossier par sujet.

    Returns:
        Les noms de sous-dossiers contenant un `subject.yml`, triés.
    """
    if not subjects_dir.is_dir():
        return []
    return sorted(p.name for p in subjects_dir.iterdir() if (p / SUBJECT_FILENAME).is_file())


def resolve_slug(requested: str | None, subjects_dir: Path = SUBJECTS_DIR) -> str:
    """Détermine le sujet à utiliser.

    Args:
        requested: Identifiant passé par `--subject`, ou `None`.
        subjects_dir: Dossier contenant les sujets.

    Returns:
        `requested` s'il existe ; à défaut, l'unique sujet disponible.

    Raises:
        SubjectError: Si l'identifiant est inconnu, s'il n'y a aucun sujet,
            ou si plusieurs existent sans choix explicite.
    """
    available = list_subjects(subjects_dir)
    if requested is not None:
        if requested not in available:
            listing = ", ".join(available) or "aucun"
            raise SubjectError(f"Sujet inconnu : {requested!r}. Disponibles : {listing}.")
        return requested
    if not available:
        raise SubjectError("Aucun sujet disponible. Crée-en un avec `manual subject new <identifiant>`.")
    if len(available) > 1:
        raise SubjectError(f"Plusieurs sujets disponibles : précise --subject parmi {', '.join(available)}.")
    return available[0]


def load_subject(slug: str, subjects_dir: Path = SUBJECTS_DIR) -> Subject:
    """Charge et valide un sujet.

    Args:
        slug: Identifiant du sujet (nom de son dossier).
        subjects_dir: Dossier contenant les sujets.

    Returns:
        Le sujet chargé.

    Raises:
        SubjectError: Si le dossier ou `subject.yml` est introuvable, si le
            YAML est invalide, si un champ obligatoire manque, est vide ou
            porte encore le marqueur « À COMPLÉTER », ou si un champ est
            inconnu.
    """
    directory = subjects_dir / slug
    path = directory / SUBJECT_FILENAME
    if not path.is_file():
        raise SubjectError(f"Sujet {slug!r} introuvable : {path} n'existe pas.")
    data = load_yaml_mapping(path)
    try:
        spec = SubjectSpec.model_validate(data)
    except ValidationError as exc:
        details = "\n".join(f"  - {'.'.join(str(p) for p in e['loc'])} : {e['msg'].removeprefix('Value error, ')}" for e in exc.errors())
        raise SubjectError(f"Sujet {slug!r} invalide ({path}) :\n{details}") from exc
    return Subject(**spec.model_dump(), slug=slug, directory=directory)


def scaffold_subject(slug: str, subjects_dir: Path = SUBJECTS_DIR) -> Path:
    """Crée le squelette d'un nouveau sujet à remplir.

    Args:
        slug: Identifiant du nouveau sujet (minuscules, chiffres, tirets).
        subjects_dir: Dossier contenant les sujets.

    Returns:
        Le dossier créé, contenant `subject.yml` (champs « À COMPLÉTER ») et
        un `requirements.yml` documenté.

    Raises:
        SubjectError: Si l'identifiant est invalide ou si le sujet existe déjà.
    """
    validate_slug(slug)
    directory = subjects_dir / slug
    if directory.exists():
        raise SubjectError(f"Le sujet {slug!r} existe déjà : {directory}")
    directory.mkdir(parents=True)
    shutil.copyfile(SUBJECT_TEMPLATE_PATH, directory / SUBJECT_FILENAME)
    (directory / REQUIREMENTS_FILENAME).write_text(REQUIREMENTS_STUB, encoding="utf-8")
    return directory


def delete_subject(slug: str, subjects_dir: Path = SUBJECTS_DIR) -> Path:
    """Supprime définitivement le dossier d'un sujet.

    Un sujet incomplet ou invalide peut être supprimé : seule la présence de
    son `subject.yml` est exigée. Le manuel déjà généré (`output/<slug>/`)
    n'est pas touché ici.

    Args:
        slug: Identifiant du sujet à supprimer.
        subjects_dir: Dossier contenant les sujets.

    Returns:
        Le dossier supprimé.

    Raises:
        SubjectError: Si l'identifiant ne désigne pas un sujet existant.
    """
    resolve_slug(slug, subjects_dir)
    directory = subjects_dir / slug
    shutil.rmtree(directory)
    return directory
