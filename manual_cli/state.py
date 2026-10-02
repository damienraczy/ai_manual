"""État persistant du manuel : table des matières aplatie et suivi par section.

`ManualState` est la source de vérité sur l'avancement de la génération. Il
est sérialisé dans `toc.yml` (plan) et `manifest.json` (suivi) (voir `save_state`/`load_state`) et relu
à chaque commande pour reprendre là où la précédente exécution s'est arrêtée.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, field_validator

from .schemas import Cadre, Chapitre, SousSection, TocSchema

MANIFEST_FILENAME = "manifest.json"
TOC_FILENAME = "toc.yml"
_ROMAN = (("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1))


class _IndentedDumper(yaml.SafeDumper):
    """Dumper YAML qui indente les listes sous leur clé, pour un fichier lisible à la main."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: D102
        return super().increase_indent(flow, False)


class StateError(Exception):
    """Plan (`toc.yml`) ou manifeste illisible ou invalide."""


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
        sous_sections: Sous-sections attendues, avec leur description. Un
            manifeste ancien les stocke en `"numero titre"` : elles sont relues
            sans description.
        slug: Identifiant ASCII dérivé du titre, utilisé dans `filename`.
        filename: Nom du fichier Markdown de sortie de ce chapitre.
        role: `"chapitre"`, ou `"introduction"` / `"conclusion"` (sections hors parties,
            numérotées 0 et N+1 ; `partie_titre` y est vide).
        status: `"pending"`, `"done"` ou `"failed"`.
        attempts: Nombre de cycles rédaction/jugement effectués.
        last_verdict: Dernier verdict du juge, ou motif d'échec technique.
    """

    numero: int
    partie_titre: str
    titre: str
    description: str
    sous_sections: list[SousSection]
    slug: str
    filename: str
    role: str = "chapitre"  # chapitre | introduction | conclusion
    status: str = "pending"  # pending | done | failed
    attempts: int = 0
    last_verdict: str | None = None

    @property
    def intitule(self) -> str:
        """Titre tel qu'il s'écrit dans le texte : `"N. titre"` pour un chapitre, le titre seul sinon."""
        return f"{self.numero}. {self.titre}" if self.role == "chapitre" else self.titre

    @field_validator("sous_sections", mode="before")
    @classmethod
    def _read_legacy_labels(cls, value: object) -> object:
        """Convertit les sous-sections `"numero titre"` d'un manifeste ancien.

        Args:
            value: Valeur brute lue dans le manifeste.

        Returns:
            La liste, avec chaque chaîne remplacée par sa `SousSection` (sans description).
        """
        if not isinstance(value, list):
            return value
        converted = []
        for item in value:
            if isinstance(item, str):
                numero, _, titre = item.partition(" ")
                item = SousSection(numero=numero, titre=titre)
            converted.append(item)
        return converted


class ManualState(BaseModel):
    """État complet du manuel en cours de génération.

    Attributes:
        titre_manuel: Titre général du manuel.
        toc: Table des matières d'origine, telle que validée par le schéma.
        sections: Suivi d'avancement de chaque chapitre, trié par numéro.
        subject: Identifiant du sujet dont les prompts et critères ont servi à
            générer la table des matières. `None` pour un manifeste antérieur
            à la gestion des sujets.
    """

    titre_manuel: str
    toc: TocSchema
    sections: list[SectionState]
    subject: str | None = None

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


def render_plan(state: ManualState, current_numero: int) -> str:
    """Rend le plan complet de l'ouvrage, pour situer un chapitre dans l'ensemble.

    Args:
        state: État du manuel (parties, chapitres, sous-sections).
        current_numero: Numéro du chapitre en cours de rédaction, signalé dans le plan.

    Returns:
        Un plan Markdown : une ligne par partie, par chapitre (avec sa
        description) et par sous-section ; le chapitre en cours est marqué.
    """
    lines: list[str] = []
    current_partie: str | None = None
    for s in state.sections:
        marker = "  ← CHAPITRE EN COURS" if s.numero == current_numero else ""
        if s.role != "chapitre":
            current_partie = None
            lines.append(f"- {s.titre} — {s.description}{marker}")
            lines.extend(f"  - {ss.label}" for ss in s.sous_sections)
            continue
        if s.partie_titre != current_partie:
            current_partie = s.partie_titre
            numero = next((p.numero for p in state.toc.parties if p.titre == current_partie), None)
            prefix = f"Partie {numero} — " if numero else ""
            lines.append(f"### {prefix}{current_partie}")
        lines.append(f"- {s.numero}. {s.titre} — {s.description}{marker}")
        lines.extend(f"  - {ss.label}" for ss in s.sous_sections)
    return "\n".join(lines)


def build_manual_state(toc: TocSchema, subject: str | None = None) -> ManualState:
    """Aplati une table des matières en état de suivi par section.

    Args:
        toc: Table des matières générée par le LLM rédacteur.
        subject: Identifiant du sujet à mémoriser dans le manifeste.

    Returns:
        Un `ManualState` avec une `SectionState` par chapitre (statut
        `"pending"`), triées par numéro de chapitre croissant.
    """
    toc = renumber_toc(toc)
    sections: list[SectionState] = []

    def add(numero: int, partie_titre: str, item: Cadre | Chapitre, role: str) -> None:
        slug = slugify(item.titre)
        sections.append(
            SectionState(
                numero=numero,
                partie_titre=partie_titre,
                titre=item.titre,
                description=item.description,
                sous_sections=[ss.model_copy() for ss in item.sous_sections],
                slug=slug,
                filename=f"{numero:02d}_{slug}.md",
                role=role,
            )
        )

    if toc.introduction is not None:
        add(0, "", toc.introduction, "introduction")
    for partie in toc.parties:
        for chapitre in partie.chapitres:
            add(chapitre.numero, partie.titre, chapitre, "chapitre")
    if toc.conclusion is not None:
        add(sum(len(p.chapitres) for p in toc.parties) + 1, "", toc.conclusion, "conclusion")
    sections.sort(key=lambda s: s.numero)
    return ManualState(titre_manuel=toc.titre_manuel, toc=toc, sections=sections, subject=subject)


def _roman(n: int) -> str:
    """Écrit un entier positif en chiffres romains (numéro de partie).

    Args:
        n: Entier à convertir (rang de la partie, à partir de 1).

    Returns:
        L'écriture romaine de `n`.
    """
    out = ""
    for symbol, value in _ROMAN:
        while n >= value:
            out += symbol
            n -= value
    return out


def _renumber_cadre(cadre: Cadre | None, numero: int) -> Cadre | None:
    """Numérote les sous-sections d'une introduction ou d'une conclusion.

    Args:
        cadre: Introduction ou conclusion, ou `None`.
        numero: Numéro de la section (0 pour l'introduction, N+1 pour la conclusion).

    Returns:
        Une copie dont les sous-sections sont numérotées `"numero.rang"`, ou `None`.
    """
    if cadre is None:
        return None
    subs = [ss.model_copy(update={"numero": f"{numero}.{rank}"}) for rank, ss in enumerate(cadre.sous_sections, start=1)]
    return cadre.model_copy(update={"sous_sections": subs})


def renumber_toc(toc: TocSchema) -> TocSchema:
    """Recalcule tous les numéros du plan d'après la position des éléments.

    Parties en chiffres romains, chapitres de 1 à N sur tout le manuel,
    sous-sections `"chapitre.rang"` : les numéros ne sont jamais une donnée
    à maintenir, donc ne peuvent pas être incohérents.

    Args:
        toc: Plan dont les numéros peuvent être faux ou absents.

    Returns:
        Un nouveau plan, titres et descriptions inchangés.
    """
    chapter_no = 0
    parties = []
    for p_rank, partie in enumerate(toc.parties, start=1):
        chapitres = []
        for chapitre in partie.chapitres:
            chapter_no += 1
            sous_sections = [
                ss.model_copy(update={"numero": f"{chapter_no}.{rank}"})
                for rank, ss in enumerate(chapitre.sous_sections, start=1)
            ]
            chapitres.append(chapitre.model_copy(update={"numero": chapter_no, "sous_sections": sous_sections}))
        parties.append(partie.model_copy(update={"numero": _roman(p_rank), "chapitres": chapitres}))
    return toc.model_copy(
        update={
            "parties": parties,
            "introduction": _renumber_cadre(toc.introduction, 0),
            "conclusion": _renumber_cadre(toc.conclusion, chapter_no + 1),
        }
    )


def toc_to_yaml(toc: TocSchema) -> str:
    """Sérialise le plan en YAML éditable : titres et descriptions, sans aucun numéro.

    Args:
        toc: Plan à sérialiser.

    Returns:
        Le texte de `toc.yml`.
    """
    def entry(item: Cadre | Chapitre) -> dict:
        return {
            "titre": item.titre,
            "description": item.description,
            "sous_sections": [{"titre": ss.titre, "description": ss.description} for ss in item.sous_sections],
        }

    data: dict = {"titre_manuel": toc.titre_manuel}
    if toc.introduction is not None:
        data["introduction"] = entry(toc.introduction)
    data["parties"] = [
        {"titre": partie.titre, "chapitres": [entry(c) for c in partie.chapitres]} for partie in toc.parties
    ]
    if toc.conclusion is not None:
        data["conclusion"] = entry(toc.conclusion)
    return yaml.dump(data, Dumper=_IndentedDumper, allow_unicode=True, sort_keys=False, width=1000)


def _numbered_plan(data: dict) -> dict:
    """Ajoute des numéros provisoires au plan lu, pour le valider avec `TocSchema`.

    Args:
        data: Contenu brut de `toc.yml` (sans numéros).

    Returns:
        Le même plan avec des numéros factices, immédiatement recalculés par `renumber_toc`.
    """
    parties = []
    for partie in data["parties"]:
        numbered = {**partie, "numero": "?"}
        if isinstance(partie.get("chapitres"), list):
            numbered["chapitres"] = [
                {**c, "numero": 0, "sous_sections": [{**ss, "numero": "?"} for ss in c.get("sous_sections") or []]}
                for c in partie["chapitres"]
            ]
        parties.append(numbered)
    numbered = {**data, "parties": parties}
    for key in ("introduction", "conclusion"):
        if isinstance(data.get(key), dict):
            numbered[key] = {**data[key], "sous_sections": [{**ss, "numero": "?"} for ss in data[key].get("sous_sections") or []]}
    return numbered


def toc_from_yaml(text: str) -> TocSchema:
    """Relit `toc.yml` et en déduit tous les numéros.

    Args:
        text: Contenu du fichier.

    Returns:
        Le plan validé et renuméroté.

    Raises:
        StateError: Si le YAML est invalide ou si le plan ne respecte pas le schéma.
    """
    try:
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or not isinstance(data.get("parties"), list):
            raise StateError(f"{TOC_FILENAME} : attendu un objet avec `titre_manuel` et une liste `parties`.")
        return renumber_toc(TocSchema.model_validate(_numbered_plan(data)))
    except (yaml.YAMLError, ValidationError, TypeError, AttributeError) as exc:
        raise StateError(f"{TOC_FILENAME} invalide : {exc}") from exc


def manifest_path(output_dir: Path) -> Path:
    """Calcule le chemin du fichier manifeste pour un répertoire de sortie donné.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le chemin `output_dir / "manifest.json"`.
    """
    return output_dir / MANIFEST_FILENAME


def toc_path(output_dir: Path) -> Path:
    """Calcule le chemin du plan éditable `toc.yml`.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le chemin `output_dir / "toc.yml"`.
    """
    return output_dir / TOC_FILENAME


def _write_plan_if_changed(path: Path, toc: TocSchema) -> None:
    """Écrit `toc.yml` seulement si le plan a changé.

    Évite de réécrire (et donc de perdre les commentaires ou une édition en
    cours) à chaque section terminée, alors que seul le suivi a bougé.

    Args:
        path: Chemin de `toc.yml`.
        toc: Plan à enregistrer.
    """
    if path.is_file():
        try:
            if toc_from_yaml(path.read_text(encoding="utf-8")) == toc:
                return
        except StateError:
            pass  # fichier illisible : le plan en mémoire fait foi
    path.write_text(toc_to_yaml(toc), encoding="utf-8")


def save_state(output_dir: Path, state: ManualState) -> None:
    """Sérialise l'état du manuel : le plan dans `toc.yml`, le suivi dans `manifest.json`.

    Le plan (source de vérité, modifiable à la main) et le suivi (statut,
    tentatives, verdict) sont séparés, et rien n'y est écrit deux fois.
    Crée `output_dir` si nécessaire.

    Args:
        output_dir: Répertoire de sortie du manuel.
        state: État à sauvegarder.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_plan_if_changed(toc_path(output_dir), state.toc)
    tracking = {
        "subject": state.subject,
        "sections": [
            {"numero": s.numero, "titre": s.titre, "status": s.status, "attempts": s.attempts, "last_verdict": s.last_verdict}
            for s in state.sections
        ],
    }
    manifest_path(output_dir).write_text(json.dumps(tracking, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state(output_dir: Path) -> ManualState:
    """Recharge l'état du manuel : plan depuis `toc.yml`, suivi depuis `manifest.json`.

    Un chapitre ajouté à la main, ou dont le titre a changé, repart en
    attente (son fichier `NN_titre.md` n'est plus celui du plan). Un
    manifeste ancien, qui contient lui-même le plan (`toc`), est relu tel quel
    et migré à la prochaine sauvegarde.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        L'état reconstitué.

    Raises:
        FileNotFoundError: Si aucun manifeste n'existe dans `output_dir`.
        StateError: Si `toc.yml` est invalide, ou absent d'un manifeste récent.
    """
    raw = json.loads(manifest_path(output_dir).read_text(encoding="utf-8"))
    plan_file = toc_path(output_dir)
    if not plan_file.is_file():
        if "toc" in raw:
            return ManualState.model_validate(raw)
        raise StateError(f"{TOC_FILENAME} introuvable dans {output_dir} : le plan du manuel est perdu.")
    state = build_manual_state(toc_from_yaml(plan_file.read_text(encoding="utf-8")), subject=raw.get("subject"))
    tracked = {(t["numero"], t["titre"]): t for t in raw.get("sections", [])}
    for section in state.sections:
        t = tracked.get((section.numero, section.titre))
        if t is not None:
            section.status, section.attempts, section.last_verdict = t["status"], t["attempts"], t["last_verdict"]
    return state


def state_exists(output_dir: Path) -> bool:
    """Indique si un manifeste existe déjà pour ce répertoire de sortie.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        `True` si un fichier manifeste existe.
    """
    return manifest_path(output_dir).exists()
