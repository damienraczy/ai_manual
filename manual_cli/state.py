"""État persistant du manuel : table des matières aplatie et suivi par section.

`ManualState` est la source de vérité sur l'avancement de la génération. Il
est sérialisé dans `manifest.json` (voir `save_state`/`load_state`) et relu
à chaque commande pour reprendre là où la précédente exécution s'est arrêtée.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from .schemas import TocSchema

MANIFEST_FILENAME = "manifest.json"


def slugify(text: str) -> str:
    """Convertit un texte en identifiant de fichier ASCII, minuscule et à tirets.

    Args:
        text: Texte source (ex: un titre de chapitre).

    Returns:
        Le texte translittéré, en minuscules, avec les caractères non
        alphanumériques remplacés par des tirets simples. Retourne
        `"section"` si le résultat serait vide.
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "section"


class SectionState(BaseModel):
    """Suivi d'avancement d'un chapitre du manuel.

    Attributes:
        numero: Numéro du chapitre (identifiant stable dans le manifeste).
        partie_titre: Titre de la partie à laquelle appartient le chapitre
            (sert à sélectionner les exigences spécifiques du juge).
        titre: Titre du chapitre.
        description: Résumé du chapitre en une phrase.
        sous_sections: Sous-sections attendues, au format `"numero titre"`.
        slug: Identifiant ASCII dérivé du titre, utilisé dans `filename`.
        filename: Nom du fichier Markdown de sortie de ce chapitre.
        status: `"pending"`, `"done"` ou `"failed"`.
        attempts: Nombre de cycles rédaction/jugement effectués.
        last_verdict: Dernier verdict du juge, ou motif d'échec technique.
    """

    numero: int
    partie_titre: str
    titre: str
    description: str
    sous_sections: list[str]
    slug: str
    filename: str
    status: str = "pending"  # pending | done | failed
    attempts: int = 0
    last_verdict: str | None = None


class ManualState(BaseModel):
    """État complet du manuel en cours de génération.

    Attributes:
        titre_manuel: Titre général du manuel.
        toc: Table des matières d'origine, telle que validée par le schéma.
        sections: Suivi d'avancement de chaque chapitre, trié par numéro.
    """

    titre_manuel: str
    toc: TocSchema
    sections: list[SectionState]

    def section_by_numero(self, numero: int) -> SectionState:
        """Retrouve une section par son numéro de chapitre.

        Args:
            numero: Numéro du chapitre recherché.

        Returns:
            La section correspondante.

        Raises:
            KeyError: Si aucune section ne porte ce numéro.
        """
        for s in self.sections:
            if s.numero == numero:
                return s
        raise KeyError(f"Section {numero} introuvable.")


def build_manual_state(toc: TocSchema) -> ManualState:
    """Aplati une table des matières en état de suivi par section.

    Args:
        toc: Table des matières générée par le LLM rédacteur.

    Returns:
        Un `ManualState` avec une `SectionState` par chapitre (statut
        `"pending"`), triées par numéro de chapitre croissant.
    """
    sections: list[SectionState] = []
    for partie in toc.parties:
        for chapitre in partie.chapitres:
            slug = slugify(chapitre.titre)
            filename = f"{chapitre.numero:02d}_{slug}.md"
            sections.append(
                SectionState(
                    numero=chapitre.numero,
                    partie_titre=partie.titre,
                    titre=chapitre.titre,
                    description=chapitre.description,
                    sous_sections=[f"{ss.numero} {ss.titre}" for ss in chapitre.sous_sections],
                    slug=slug,
                    filename=filename,
                )
            )
    sections.sort(key=lambda s: s.numero)
    return ManualState(titre_manuel=toc.titre_manuel, toc=toc, sections=sections)


def manifest_path(output_dir: Path) -> Path:
    """Calcule le chemin du fichier manifeste pour un répertoire de sortie donné.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le chemin `output_dir / "manifest.json"`.
    """
    return output_dir / MANIFEST_FILENAME


def save_state(output_dir: Path, state: ManualState) -> None:
    """Sérialise l'état du manuel dans le fichier manifeste.

    Crée `output_dir` si nécessaire.

    Args:
        output_dir: Répertoire de sortie du manuel.
        state: État à sauvegarder.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path(output_dir).write_text(state.model_dump_json(indent=2), encoding="utf-8")


def load_state(output_dir: Path) -> ManualState:
    """Recharge l'état du manuel depuis le fichier manifeste.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        L'état précédemment sauvegardé.

    Raises:
        FileNotFoundError: Si aucun manifeste n'existe dans `output_dir`.
    """
    return ManualState.model_validate_json(manifest_path(output_dir).read_text(encoding="utf-8"))


def state_exists(output_dir: Path) -> bool:
    """Indique si un manifeste existe déjà pour ce répertoire de sortie.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        `True` si un fichier manifeste existe.
    """
    return manifest_path(output_dir).exists()
