"""Schémas Pydantic pour les sorties JSON strictes attendues des LLM.

Deux formes de réponse structurée sont utilisées dans le pipeline :
`TocSchema` (table des matières générée une seule fois) et `JudgeVerdict`
(verdict du juge après chaque rédaction de section). Les deux sont validées
via `manual_cli.parsing.call_structured`, qui redemande une correction au
modèle en cas d'échec de validation.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class SousSection(BaseModel):
    """Une sous-section de la table des matières (ex: « 1.1 »).

    Attributes:
        numero: Numéro hiérarchique de la sous-section (ex: `"1.1"`).
        titre: Titre de la sous-section.
    """

    numero: str
    titre: str


class Chapitre(BaseModel):
    """Un chapitre de la table des matières, unité de rédaction du manuel.

    Attributes:
        numero: Numéro du chapitre, unique et séquentiel sur tout le manuel.
        titre: Titre du chapitre.
        description: Résumé du chapitre en une phrase.
        sous_sections: Sous-sections attendues dans le chapitre.
    """

    numero: int
    titre: str
    description: str
    sous_sections: list[SousSection]


class Partie(BaseModel):
    """Une grande partie du manuel, regroupant plusieurs chapitres.

    Attributes:
        numero: Numéro romain de la partie (ex: `"I"`).
        titre: Titre de la partie (sert aussi de clé pour les exigences
            spécifiques dans `requirements.yml`).
        chapitres: Chapitres appartenant à cette partie.
    """

    numero: str
    titre: str
    chapitres: list[Chapitre]


class TocSchema(BaseModel):
    """Table des matières complète du manuel, telle que générée par le LLM rédacteur.

    Attributes:
        titre_manuel: Titre général du manuel.
        parties: Parties composant le manuel (au moins une).
    """

    titre_manuel: str
    parties: list[Partie]

    @field_validator("parties")
    @classmethod
    def non_empty(cls, v: list[Partie]) -> list[Partie]:
        """Vérifie qu'au moins une partie est présente.

        Args:
            v: Liste des parties à valider.

        Returns:
            La liste inchangée si elle n'est pas vide.

        Raises:
            ValueError: Si la liste de parties est vide.
        """
        if not v:
            raise ValueError("La table des matières ne contient aucune partie.")
        return v


class JudgeIssue(BaseModel):
    """Un problème signalé par le juge sur une section rédigée.

    Attributes:
        id: Identifiant du critère concerné (voir `requirements.yml`).
        severity: Sévérité du critère (`"bloquant"` ou `"recommande"`).
        detail: Explication actionnable du problème.
    """

    id: str
    severity: str
    detail: str


class JudgeVerdict(BaseModel):
    """Verdict du juge sur une section rédigée.

    Attributes:
        verdict: `"accept"` ou `"revise"`.
        issues: Problèmes relevés, y compris ceux qui ne bloquent pas l'acceptation.
    """

    verdict: str
    issues: list[JudgeIssue] = []

    @field_validator("verdict")
    @classmethod
    def valid_verdict(cls, v: str) -> str:
        """Vérifie que le verdict est une valeur autorisée.

        Args:
            v: Valeur brute du champ `verdict`.

        Returns:
            La valeur inchangée si elle est valide.

        Raises:
            ValueError: Si `v` n'est ni `"accept"` ni `"revise"`.
        """
        if v not in ("accept", "revise"):
            raise ValueError("verdict doit être 'accept' ou 'revise'")
        return v
