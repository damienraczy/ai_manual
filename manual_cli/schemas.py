"""Schémas Pydantic pour les sorties JSON strictes attendues des LLM.

Deux formes de réponse structurée sont utilisées dans le pipeline :
`TocSchema` (table des matières générée une seule fois) et `JudgeVerdict`
(verdict du juge après chaque rédaction de section). Les deux sont validées
via `manual_cli.parsing.call_structured`, qui redemande une correction au
modèle en cas d'échec de validation.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator


class SousSection(BaseModel):
    """Une sous-section de la table des matières (ex: « 1.1 »).

    Attributes:
        numero: Numéro hiérarchique de la sous-section (ex: `"1.1"`).
        titre: Titre de la sous-section.
        description: Résumé de la sous-section en une phrase. Vide dans les
            manifestes générés avant l'ajout de ce champ ; `GeneratedTocSchema`
            l'exige pour toute table des matières produite par le modèle.
    """

    numero: str
    titre: str
    description: str = ""

    @property
    def label(self) -> str:
        """Intitulé `"numero titre"`, sans description (sert à identifier la sous-section)."""
        return f"{self.numero} {self.titre}"


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


class Cadre(BaseModel):
    """Introduction ou conclusion du manuel, hors des parties.

    Attributes:
        titre: Titre de la section (ex: `"Introduction"`).
        description: Résumé de la section en une phrase.
        sous_sections: Sous-sections éventuelles.
    """

    titre: str
    description: str
    sous_sections: list[SousSection] = []


class TocSchema(BaseModel):
    """Table des matières complète du manuel, telle que générée par le LLM rédacteur.

    Attributes:
        titre_manuel: Titre général du manuel.
        parties: Parties composant le manuel (au moins une).
        introduction: Introduction du manuel (section numéro 0), optionnelle.
        conclusion: Conclusion du manuel (dernière section), optionnelle.
    """

    titre_manuel: str
    parties: list[Partie]
    introduction: Cadre | None = None
    conclusion: Cadre | None = None

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


class GeneratedTocSchema(TocSchema):
    """Table des matières telle qu'un modèle doit la produire.

    Comme `TocSchema`, mais chaque sous-section doit porter une description :
    `TocSchema` reste indulgent pour relire un manifeste ancien, où elle manque.
    """

    @model_validator(mode="after")
    def _sous_sections_are_described(self) -> GeneratedTocSchema:
        """Exige une description non vide pour chaque sous-section.

        Returns:
            La table inchangée si toutes les sous-sections sont décrites.

        Raises:
            ValueError: Avec la liste des sous-sections sans description
                (renvoyée au modèle pour correction).
        """
        missing = [
            ss.label
            for partie in self.parties
            for chapitre in partie.chapitres
            for ss in chapitre.sous_sections
            if not ss.description.strip()
        ] + [
            ss.label
            for cadre in (self.introduction, self.conclusion)
            if cadre is not None
            for ss in cadre.sous_sections
            if not ss.description.strip()
        ]
        if missing:
            raise ValueError(f"Description manquante pour les sous-sections : {', '.join(missing)}.")
        return self


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
