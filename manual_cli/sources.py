"""Documents de référence : extraction de la matière en unités, cache et consolidation.

Un sujet peut fournir des documents (bibliographie commentée, thèmes préparés,
textes plus ou moins rédigés...) dans `subjects/<slug>/sources/`. Chaque
fichier est découpé par le LLM en *unités de matière* typées, avec un extrait
copié mot pour mot (vérifié dans la source). Le résultat est mis en cache dans
`output/<slug>/sources_index.json`, indexé par empreinte du contenu : seuls les
fichiers nouveaux ou modifiés sont ré-analysés. Une passe de consolidation
fusionne les doublons et signale les contradictions entre documents.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError, model_validator

from .config import AppConfig
from .parsing import call_structured
from .providers import OllamaCloudClient
from .subjects import PROMPTS_DIR, Subject

SOURCES_DIRNAME = "sources"
INDEX_FILENAME = "sources_index.json"
SUFFIXES = (".md", ".txt")

UniteType = Literal["idee", "fait", "reference", "exemple", "passage", "theme"]
Utilite = Literal["haute", "moyenne", "nulle"]


class SourcesError(Exception):
    """Documents de référence illisibles, index corrompu ou réglage invalide."""


class UniteBrute(BaseModel):
    """Unité telle que renvoyée par le modèle (avant attribution d'un identifiant)."""

    type: UniteType
    enonce: str
    extrait: str
    utilite: Utilite
    themes: list[str] = []


class ExtractionSchema(BaseModel):
    """Réponse attendue du modèle pour un bloc de document."""

    unites: list[UniteBrute]


class Unite(UniteBrute):
    """Unité de matière rattachée à son fichier.

    Attributes:
        id: Identifiant stable `<fichier>#<n>`.
        source: Fichier d'origine (chemin relatif à `sources/`).
        ligne: Ligne (à partir de 1) où commence l'extrait dans le fichier.
        autres_sources: Autres fichiers où la même matière a été trouvée (doublons fusionnés).
        conflit_avec: Identifiants des unités qui contredisent celle-ci.
    """

    id: str
    source: str
    ligne: int
    autres_sources: list[str] = []
    conflit_avec: list[str] = []


class Fusion(BaseModel):
    """Doublons fusionnés dans une unité conservée."""

    garde: str
    doublons: list[str]


class ConsolidationSchema(BaseModel):
    """Réponse attendue du modèle pour la consolidation."""

    fusions: list[Fusion]
    conflits: list[list[str]]


class Consolidation(ConsolidationSchema):
    """Consolidation mémorisée, avec l'empreinte des unités sur lesquelles elle a été calculée."""

    signature: str


class FileEntry(BaseModel):
    """Résultat mémorisé pour un fichier."""

    hash: str
    unites: list[Unite]


class SourceIndex(BaseModel):
    """Index des documents de référence d'un manuel."""

    fichiers: dict[str, FileEntry] = {}
    consolidation: Consolidation | None = None

    def units(self) -> list[Unite]:
        """Unités de tous les fichiers, après fusion des doublons et marquage des conflits.

        Returns:
            Les unités (copies), dans l'ordre des fichiers, `nulle` comprises.
        """
        raw = [u for name in sorted(self.fichiers) for u in self.fichiers[name].unites]
        if self.consolidation is None:
            return [u.model_copy(deep=True) for u in raw]
        by_id = {u.id: u.model_copy(deep=True) for u in raw}
        merged_into: dict[str, str] = {}
        for fusion in self.consolidation.fusions:
            for dup in fusion.doublons:
                if dup in by_id and fusion.garde in by_id:
                    merged_into[dup] = fusion.garde
                    kept = by_id[fusion.garde]
                    for name in [by_id[dup].source, *by_id[dup].autres_sources]:
                        if name != kept.source and name not in kept.autres_sources:
                            kept.autres_sources.append(name)
        for group in self.consolidation.conflits:
            ids = list(dict.fromkeys(merged_into.get(i, i) for i in group if i in by_id))
            for i in ids:
                others = [o for o in ids if o != i and o not in by_id[i].conflit_avec]
                by_id[i].conflit_avec.extend(others)
        return [by_id[u.id] for u in raw if u.id not in merged_into]

    def active_units(self) -> list[Unite]:
        """Unités utiles (`utilite` différente de `nulle`).

        Returns:
            Les unités à exploiter ; les `nulle` restent dans l'index mais jamais ici.
        """
        return [u for u in self.units() if u.utilite != "nulle"]


@dataclass
class RefreshReport:
    """Ce qu'une mise à jour de l'index a fait.

    Attributes:
        extracted: Fichiers (ré-)analysés.
        cached: Fichiers inchangés, repris du cache.
        removed: Fichiers disparus, retirés de l'index.
        consolidated: `True` si la consolidation a été recalculée.
    """

    extracted: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    consolidated: bool = False


def _client(cfg: AppConfig, role: str) -> OllamaCloudClient:
    """Construit le client LLM d'un rôle (point d'indirection pour les tests).

    Args:
        cfg: Configuration applicative résolue.
        role: Rôle (ex. `"model_think"`).

    Returns:
        Un client Ollama Cloud configuré pour ce rôle.
    """
    return OllamaCloudClient(cfg.role(role), role=role)


def _read_prompt(name: str) -> str:
    """Lit un prompt de `prompts/`."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def subject_context(subject: Subject) -> str:
    """Décrit le manuel visé, pour que le modèle juge l'utilité des unités.

    Args:
        subject: Sujet du manuel.

    Returns:
        Un court paragraphe (titre, objectif, public).
    """
    return (
        f"Manuel visé : « {subject.titre.strip()} ». Objectif : {subject.objectif.strip()} "
        f"Public : {subject.public.strip()}"
    )


def list_source_files(subject_dir: Path) -> list[str]:
    """Liste les documents de référence d'un sujet.

    Args:
        subject_dir: Dossier du sujet.

    Returns:
        Chemins relatifs à `sources/` (séparateur `/`), triés ; `.md` et `.txt`
        seulement, fichiers cachés exclus. Liste vide si `sources/` n'existe pas.
    """
    root = subject_dir / SOURCES_DIRNAME
    if not root.is_dir():
        return []
    found = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUFFIXES and not any(part.startswith(".") for part in p.relative_to(root).parts)
    ]
    return sorted(found)


def _hard_slices(text: str, max_chars: int) -> list[str]:
    """Découpe un texte sans coupure de contenu : par lignes, puis par tranches de caractères."""
    pieces: list[str] = []
    for line in filter(None, text.split("\n")):
        pieces.extend(line[i : i + max_chars] for i in range(0, len(line), max_chars))
    return pieces


def split_chunks(text: str, max_chars: int) -> list[str]:
    """Découpe un texte en blocs d'au plus `max_chars` caractères, sans rien perdre.

    Coupe d'abord sur les titres Markdown, puis sur les paragraphes, puis sur
    les lignes, enfin par tranches ; regroupe ensuite les morceaux voisins tant
    qu'ils tiennent dans la limite.

    Args:
        text: Texte à découper.
        max_chars: Taille maximale d'un bloc.

    Returns:
        Les blocs, dans l'ordre.

    Raises:
        SourcesError: Si `max_chars` n'est pas strictement positif.
    """
    if max_chars <= 0:
        raise SourcesError(f"sources.max_chunk_chars doit être positif (reçu {max_chars}).")
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for section in re.split(r"\n(?=#)", text):
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chars:
            pieces.append(section)
            continue
        for paragraph in re.split(r"\n\s*\n", section):
            paragraph = paragraph.strip()
            pieces.extend([paragraph] if len(paragraph) <= max_chars else _hard_slices(paragraph, max_chars))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def _find(text: str, quote: str, start: int = 0) -> re.Match | None:
    """Cherche un extrait dans un texte, en tolérant les différences d'espacement."""
    tokens = quote.split()
    if not tokens:
        return None
    return re.compile(r"\s+".join(re.escape(t) for t in tokens)).search(text, start)


def _extraction_schema(chunk: str) -> type[ExtractionSchema]:
    """Schéma d'extraction qui refuse tout extrait absent du bloc analysé.

    Args:
        chunk: Texte du bloc envoyé au modèle.

    Returns:
        Une sous-classe de `ExtractionSchema` dont la validation renvoie les
        extraits introuvables au modèle (via `call_structured`).
    """

    class _Faithful(ExtractionSchema):
        @model_validator(mode="after")
        def _quotes_are_in_the_source(self):
            missing = [u.extrait for u in self.unites if _find(chunk, u.extrait) is None]
            if missing:
                raise ValueError(
                    "Ces extraits ne figurent pas mot pour mot dans le document : "
                    + " | ".join(repr(m) for m in missing)
                    + ". Copie-les exactement."
                )
            return self

    return _Faithful


def extract_file(cfg: AppConfig, name: str, text: str, contexte: str = "") -> list[Unite]:
    """Extrait les unités de matière d'un document.

    Args:
        cfg: Configuration applicative résolue.
        name: Chemin relatif du fichier (sert d'identifiant et de source).
        text: Contenu du fichier.
        contexte: Description du manuel visé, pour juger l'utilité des unités.

    Returns:
        Les unités, numérotées `<name>#1`, `<name>#2`... dans l'ordre du document.

    Raises:
        SourcesError: Si `sources.max_chunk_chars` est invalide.
        ParsingError: Si le modèle ne renvoie pas d'unités valides (extraits fidèles compris).
    """
    chunks = split_chunks(text, int(cfg.setting("sources", "max_chunk_chars")))
    client = _client(cfg, "model_think")
    template = string.Template(_read_prompt("sources_extract_instruction.md"))
    units: list[Unite] = []
    cursor = 0
    for chunk in chunks:
        prompt = template.substitute(fichier=name, texte=chunk, contexte=contexte)
        found = call_structured(client, [{"role": "user", "content": prompt}], _extraction_schema(chunk))
        for brute in found.unites:
            match = _find(text, brute.extrait, cursor) or _find(text, brute.extrait)
            ligne = text.count("\n", 0, match.start()) + 1
            cursor = match.end()
            units.append(Unite(**brute.model_dump(), id=f"{name}#{len(units) + 1}", source=name, ligne=ligne))
    return units


def load_index(output_dir: Path) -> SourceIndex:
    """Charge l'index des sources.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        L'index, vide si le fichier n'existe pas.

    Raises:
        SourcesError: Si le fichier est illisible ou invalide.
    """
    path = output_dir / INDEX_FILENAME
    if not path.is_file():
        return SourceIndex()
    try:
        return SourceIndex.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        raise SourcesError(f"{INDEX_FILENAME} illisible ({path}) : {exc}. Supprime-le pour le régénérer.") from exc


def _save_index(output_dir: Path, index: SourceIndex) -> None:
    """Écrit l'index sur disque."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / INDEX_FILENAME).write_text(index.model_dump_json(indent=2), encoding="utf-8")


def _signature(units: list[Unite]) -> str:
    """Empreinte des unités soumises à la consolidation."""
    payload = json.dumps([(u.id, u.type, u.enonce) for u in units], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _consolidation_schema(known: set[str]) -> type[ConsolidationSchema]:
    """Schéma de consolidation qui refuse les identifiants inconnus ou incohérents."""

    class _Known(ConsolidationSchema):
        @model_validator(mode="after")
        def _ids_exist(self):
            used = [i for f in self.fusions for i in (f.garde, *f.doublons)] + [i for g in self.conflits for i in g]
            unknown = sorted(set(used) - known)
            if unknown:
                raise ValueError(f"Identifiants inconnus : {', '.join(unknown)}. N'utilise que ceux de la liste.")
            if any(f.garde in f.doublons for f in self.fusions):
                raise ValueError("Une unité ne peut pas être son propre doublon.")
            return self

    return _Known


def _consolidate(cfg: AppConfig, index: SourceIndex) -> bool:
    """Recalcule la consolidation si les unités actives ont changé.

    Returns:
        `True` si un appel au modèle a eu lieu.
    """
    index.consolidation = None
    active = [u for u in index.units() if u.utilite != "nulle"]
    signature = _signature(active)
    if len(active) < 2:
        index.consolidation = Consolidation(signature=signature, fusions=[], conflits=[])
        return False
    lines = "\n".join(f"- {u.id} | {u.type} | {u.enonce}" for u in active)
    prompt = string.Template(_read_prompt("sources_consolidate_instruction.md")).substitute(unites=lines)
    answer = call_structured(
        _client(cfg, "model_think"),
        [{"role": "user", "content": prompt}],
        _consolidation_schema({u.id for u in active}),
    )
    index.consolidation = Consolidation(signature=signature, fusions=answer.fusions, conflits=answer.conflits)
    return True


def refresh_index(cfg: AppConfig, subject_dir: Path, output_dir: Path, contexte: str = "") -> RefreshReport:
    """Met l'index à jour : ré-analyse les fichiers nouveaux ou modifiés, puis consolide.

    Args:
        cfg: Configuration applicative résolue.
        subject_dir: Dossier du sujet (contient `sources/`).
        output_dir: Répertoire de sortie du manuel (contient l'index).
        contexte: Description du manuel visé (fait partie de l'empreinte : la changer ré-analyse tout).

    Returns:
        Le compte rendu de la mise à jour. Sans document de référence, rien n'est écrit.

    Raises:
        SourcesError: Si un fichier n'est pas de l'UTF-8 lisible ou si l'index est corrompu.
        ParsingError: Si le modèle ne renvoie pas de réponse valide.
    """
    names = list_source_files(subject_dir)
    index = load_index(output_dir)
    report = RefreshReport()
    if not names and not index.fichiers:
        return report

    report.removed = sorted(set(index.fichiers) - set(names))
    for name in report.removed:
        del index.fichiers[name]

    for name in names:
        path = subject_dir / SOURCES_DIRNAME / name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SourcesError(f"Lecture impossible de {name} : {exc}") from exc
        digest = hashlib.sha256(f"{contexte}\0{text}".encode("utf-8")).hexdigest()
        entry = index.fichiers.get(name)
        if entry is not None and entry.hash == digest:
            report.cached.append(name)
            continue
        index.fichiers[name] = FileEntry(hash=digest, unites=extract_file(cfg, name, text, contexte))
        report.extracted.append(name)

    if index.consolidation is None or report.extracted or report.removed:
        report.consolidated = _consolidate(cfg, index)
    _save_index(output_dir, index)
    return report
