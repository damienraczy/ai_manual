"""Extraction et validation de réponses JSON structurées issues d'un LLM.

Les modèles sont instruits de répondre avec un unique bloc ```json``` ; ce
module isole ce bloc, le valide contre un schéma Pydantic, et redemande
automatiquement une correction au modèle en cas d'échec (JSON invalide ou
non conforme au schéma), jusqu'à épuisement d'un nombre maximal de tentatives.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .providers import OllamaCloudClient

T = TypeVar("T", bound=BaseModel)

JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ParsingError(Exception):
    """Aucune réponse JSON valide n'a pu être obtenue du modèle."""


def _extract_json_text(raw: str) -> str:
    """Isole le texte JSON dans une réponse brute de LLM.

    Cherche d'abord un bloc ```json``` explicite ; à défaut, se rabat sur le
    texte compris entre la première `{` et la dernière `}` de la réponse.

    Args:
        raw: Réponse texte brute du modèle.

    Returns:
        Le texte JSON candidat, non encore parsé.

    Raises:
        ParsingError: Si aucun bloc JSON ni accolades ne sont trouvés.
    """
    match = JSON_BLOCK_RE.search(raw)
    if match:
        return match.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    raise ParsingError("Aucun bloc JSON trouvé dans la réponse.")


def call_structured(
    client: OllamaCloudClient,
    messages: list[dict],
    schema: type[T],
    *,
    max_attempts: int = 3,
) -> T:
    """Appelle un modèle et valide sa réponse contre un schéma Pydantic.

    En cas d'échec (JSON introuvable, invalide, ou ne respectant pas le
    schéma), ajoute la réponse fautive et une demande de correction à la
    conversation, puis retente jusqu'à `max_attempts` fois.

    Args:
        client: Client LLM à appeler (typiquement un `OllamaCloudClient`).
        messages: Messages initiaux de la conversation.
        schema: Classe Pydantic attendue pour la réponse.
        max_attempts: Nombre maximal d'appels avant abandon.

    Returns:
        Une instance de `schema` validée à partir de la réponse du modèle.

    Raises:
        ParsingError: Si aucune réponse valide n'est obtenue après
            `max_attempts` tentatives.
    """
    conversation = list(messages)
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        raw = client.chat(conversation)
        try:
            json_text = _extract_json_text(raw)
            data = json.loads(json_text)
            return schema.model_validate(data)
        except (ParsingError, json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)
            conversation.append({"role": "assistant", "content": raw})
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "Ta réponse précédente n'était pas un JSON valide conforme au schéma demandé "
                        f"(erreur : {last_error}). Renvoie UNIQUEMENT le bloc ```json corrigé, "
                        "sans aucun texte avant ou après."
                    ),
                }
            )

    raise ParsingError(f"Impossible d'obtenir un JSON valide après {max_attempts} tentatives : {last_error}")
