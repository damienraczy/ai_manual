"""Chargement des exigences de contenu utilisées par le juge LLM.

Les critères sont définis dans `requirements/requirements.yml`, séparément
du code, pour rester ajustables sans modification des prompts ni du
pipeline. Deux niveaux existent : des critères génériques (toutes sections)
et des critères additionnels par grande Partie de la table des matières.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_REQUIREMENTS_PATH = Path(__file__).resolve().parent.parent / "requirements" / "requirements.yml"


class RequirementsError(Exception):
    """Fichier d'exigences introuvable, vide ou mal formé."""


def load_requirements(path: Path = DEFAULT_REQUIREMENTS_PATH) -> dict:
    """Charge le fichier YAML des exigences de contenu.

    Args:
        path: Chemin du fichier `requirements.yml`.

    Returns:
        Le contenu du fichier, avec au moins la clé `"generic"`.

    Raises:
        RequirementsError: Si le fichier est vide ou ne contient pas de
            section `"generic"`.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "generic" not in data:
        raise RequirementsError(f"Fichier d'exigences invalide ou vide : {path}")
    return data


def criteria_for_partie(requirements: dict, partie_titre: str) -> list[dict]:
    """Assemble les critères applicables à une partie donnée du manuel.

    Args:
        requirements: Exigences chargées via `load_requirements`.
        partie_titre: Titre exact de la partie (tel que généré dans la
            table des matières), utilisé comme clé dans `requirements["parties"]`.

    Returns:
        La concaténation des critères génériques et des critères
        spécifiques à cette partie (liste vide si la partie n'a pas de
        critères additionnels déclarés).
    """
    generic = requirements.get("generic", [])
    specific = (requirements.get("parties") or {}).get(partie_titre, [])
    return generic + specific


def blocking_ids(criteria: list[dict]) -> set[str]:
    """Extrait les identifiants des critères de sévérité bloquante.

    Args:
        criteria: Critères à filtrer (voir `criteria_for_partie`).

    Returns:
        L'ensemble des `id` dont `severity` vaut `"bloquant"`.
    """
    return {c["id"] for c in criteria if c.get("severity") == "bloquant"}


def render_criteria(criteria: list[dict]) -> str:
    """Formate une liste de critères en texte lisible pour le prompt du juge.

    Args:
        criteria: Critères à formater (voir `criteria_for_partie`).

    Returns:
        Une liste Markdown, une ligne par critère, au format
        `- [severity] id : description` (id entre backticks).
    """
    return "\n".join(f"- [{c['severity']}] `{c['id']}` : {c['description']}" for c in criteria)
