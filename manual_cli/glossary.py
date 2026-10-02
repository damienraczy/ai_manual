"""Génération du glossaire d'un manuel à partir de ses chapitres terminés.

Deux temps : un appel d'extraction par chapitre (`model_write`), puis un
appel de consolidation qui fusionne les doublons et harmonise les
définitions. Le résultat est écrit dans `glossaire.md`, trié par ordre
alphabétique (sans tenir compte de la casse ni des accents).
"""

from __future__ import annotations

import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from .config import AppConfig
from .generator import GeneratorError, _read_prompt
from .parsing import call_structured
from .providers import OllamaCloudClient
from .state import load_state, state_exists

GLOSSARY_FILENAME = "glossaire.md"


class GlossaryEntry(BaseModel):
    """Un terme du glossaire.

    Attributes:
        terme: Le terme défini.
        definition: Sa définition (une à deux phrases).
        chapitres: Numéros des chapitres où il est traité.
    """

    terme: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    chapitres: list[int] = []


class GlossarySchema(BaseModel):
    """Réponse attendue du modèle : une liste d'entrées."""

    entrees: list[GlossaryEntry]


@dataclass
class GlossaryResult:
    """Résultat de la génération du glossaire.

    Attributes:
        path: Fichier Markdown écrit.
        entries: Entrées finales, triées.
        chapters: Numéros des chapitres dont le texte a été exploité.
    """

    path: Path
    entries: list[GlossaryEntry]
    chapters: list[int]


def _client(cfg: AppConfig, role: str) -> OllamaCloudClient:
    """Construit le client LLM d'un rôle (point d'indirection pour les tests).

    Args:
        cfg: Configuration applicative résolue.
        role: Rôle (ex. `"model_write"`).

    Returns:
        Un client Ollama Cloud configuré pour ce rôle.
    """
    return OllamaCloudClient(cfg.role(role), role=role)


def _sort_key(terme: str) -> str:
    """Clé de tri alphabétique insensible à la casse et aux accents.

    Args:
        terme: Terme à classer.

    Returns:
        Le terme en minuscules, sans diacritiques.
    """
    decomposed = unicodedata.normalize("NFKD", terme.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def render_glossary(titre_manuel: str, entries: list[GlossaryEntry]) -> str:
    """Rend le glossaire en Markdown, trié alphabétiquement.

    Args:
        titre_manuel: Titre du manuel.
        entries: Entrées à rendre.

    Returns:
        Le Markdown du glossaire (une ligne par terme, avec ses chapitres).
    """
    lines = [f"# Glossaire : {titre_manuel}", ""]
    for e in sorted(entries, key=lambda e: _sort_key(e.terme)):
        chapters = f" (chap. {', '.join(str(n) for n in sorted(e.chapitres))})" if e.chapitres else ""
        lines.append(f"- **{e.terme}** : {e.definition.strip()}{chapters}")
    return "\n".join(lines) + "\n"


def _messages(system_prompt: str, instruction: str) -> list[dict]:
    """Assemble la conversation : prompt système du sujet puis consigne.

    Args:
        system_prompt: Prompt système du sujet (langue, style, typographie).
        instruction: Consigne de la tâche.

    Returns:
        Les messages à envoyer au modèle.
    """
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": instruction}]


def build_glossary(cfg: AppConfig, output_dir: Path, *, system_prompt: str) -> GlossaryResult:
    """Construit `glossaire.md` à partir des chapitres terminés.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        system_prompt: Prompt système du sujet : les définitions sont publiées et suivent
            les mêmes règles de langue et de typographie que les chapitres.

    Returns:
        Le résultat (fichier, entrées, chapitres exploités).

    Raises:
        GeneratorError: Si le manuel n'est pas initialisé, si aucun chapitre
            n'est terminé, ou si le fichier d'un chapitre terminé est introuvable.
        ParsingError: Si le modèle ne renvoie pas un JSON valide.
    """
    if not state_exists(output_dir):
        raise GeneratorError("Aucun manifeste trouvé : lance d'abord `manual init`.")
    state = load_state(output_dir)
    done = [s for s in state.sections if s.status == "done"]
    if not done:
        raise GeneratorError("Aucun chapitre terminé : lance `manual write` avant de générer le glossaire.")

    client = _client(cfg, "model_write")
    extract = string.Template(_read_prompt("glossary_extract_instruction.md"))
    raw: list[GlossaryEntry] = []
    for section in done:
        path = output_dir / section.filename
        if not path.is_file():
            raise GeneratorError(f"Fichier du chapitre {section.numero} introuvable : {path}")
        prompt = extract.substitute(numero=section.numero, titre=section.titre, texte=path.read_text(encoding="utf-8").strip())
        found = call_structured(client, _messages(system_prompt, prompt), GlossarySchema)
        raw.extend(e.model_copy(update={"chapitres": [section.numero]}) for e in found.entrees)

    lines = "\n".join(f"- {e.terme} : {e.definition} (chap. {e.chapitres[0]})" for e in raw)
    merge = string.Template(_read_prompt("glossary_merge_instruction.md")).substitute(entrees=lines)
    merged = call_structured(client, _messages(system_prompt, merge), GlossarySchema)

    path = output_dir / GLOSSARY_FILENAME
    path.write_text(render_glossary(state.titre_manuel, merged.entrees), encoding="utf-8")
    entries = sorted(merged.entrees, key=lambda e: _sort_key(e.terme))
    return GlossaryResult(path=path, entries=entries, chapters=[s.numero for s in done])
