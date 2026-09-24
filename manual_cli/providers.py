"""Clients HTTP pour les modèles utilisés par le pipeline (texte et image).

`OllamaCloudClient` encapsule l'appel `/api/chat` d'un modèle Ollama cloud,
avec retries et normalisation de l'URL de base (certaines configurations
incluent déjà le suffixe `/api`). `OpenAIImageClient` encapsule l'appel à
l'API Images d'OpenAI, avec la même logique de retry et une normalisation
similaire (certaines configurations pointent `OPENAI_URL` vers un endpoint
précis comme `/v1/responses` plutôt que la racine `/v1`).

Chaque tentative d'appel est journalisée via `manual_cli.tracing` (rôle,
modèle, horodatages, entrée/sortie), pour permettre a posteriori d'analyser
une dérive des temps de traitement (voir `manual traces`).
"""

from __future__ import annotations

import base64
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, TypeVar

import requests

from . import tracing
from .config import ModelSpec

T = TypeVar("T")

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0


class ProviderError(Exception):
    """Échec définitif d'un appel à un modèle après épuisement des tentatives."""


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extrait le délai `Retry-After` d'une erreur HTTP 429, si présent.

    Un 429 en rafale (plusieurs workers sur le même modèle cloud, cas
    Ollama Cloud) porte parfois un en-tête `Retry-After` qui indique le
    délai exact voulu par le serveur — plus fiable qu'un backoff calculé à
    l'aveugle.

    Args:
        exc: Exception levée par l'appel réseau. Seule une
            `requests.HTTPError` dont `.response` est un 429 est exploitée ;
            toute autre exception (erreur réseau, JSON mal formé, 5xx sans
            en-tête, etc.) renvoie `None`.

    Returns:
        Le délai en secondes à respecter avant de retenter, ou `None` si
        l'exception n'est pas un 429 avec `Retry-After`, ou si l'en-tête est
        absent ou dans un format illisible.
    """
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) != 429:
        return None
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(retry_after)  # format date HTTP (RFC 7231)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def _backoff_seconds(attempt: int) -> float:
    """Calcule le délai avant la tentative suivante (backoff exponentiel, plein jitter).

    Args:
        attempt: Numéro de la tentative qui vient d'échouer (1-indexé).

    Returns:
        Délai tiré aléatoirement dans `[0, plafond]`, où `plafond` double à
        chaque tentative (`BACKOFF_BASE_SECONDS * 2**(attempt - 1)`, borné à
        `BACKOFF_MAX_SECONDS`). Le tirage aléatoire ("full jitter") évite que
        plusieurs workers, ayant échoué en même temps sur le même 429,
        retentent tous exactement au même instant.
    """
    ceiling = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0, ceiling)


def _with_retries(
    *,
    role: str,
    model_key: str,
    model_name: str,
    input_data: Any,
    format_output: Callable[[T], str],
    call: Callable[[], T],
) -> T:
    """Exécute `call` en retentant jusqu'à `MAX_RETRIES` fois, en traçant chaque tentative.

    Backoff exponentiel avec plein jitter entre les tentatives (voir
    :func:`_backoff_seconds`) — sauf sur un 429 porteur d'un `Retry-After`
    exploitable (:func:`_retry_after_seconds`), qui prévaut alors sur le
    backoff calculé. Chaque tentative (succès ou échec) est journalisée via
    `tracing.record_call`.

    Args:
        role: Rôle du modèle appelé (voir `tracing.record_call`).
        model_key: Clé du modèle appelé, utilisée dans le message d'erreur final.
        model_name: Nom du modèle transmis au fournisseur.
        input_data: Entrée envoyée au modèle, à journaliser telle quelle.
        format_output: Fonction convertissant le résultat de `call()` en
            texte à journaliser (ex: identité pour un texte, description
            courte pour des octets binaires).
        call: Fonction sans argument effectuant l'appel réseau et retournant
            le résultat souhaité ; toute levée de `requests.RequestException`,
            `KeyError` ou `ValueError` déclenche une nouvelle tentative.

    Returns:
        Le résultat de `call()` dès qu'un appel réussit.

    Raises:
        ProviderError: Si toutes les tentatives échouent.
    """
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        started_at = datetime.now(timezone.utc)
        try:
            result = call()
        except (requests.RequestException, KeyError, ValueError) as exc:
            ended_at = datetime.now(timezone.utc)
            tracing.record_call(
                role=role,
                model_key=model_key,
                model_name=model_name,
                attempt=attempt,
                started_at=started_at,
                ended_at=ended_at,
                success=False,
                input_data=input_data,
                error=f"{type(exc).__name__}: {exc}",
            )
            last_error = exc
            if attempt < MAX_RETRIES:
                delay = _retry_after_seconds(exc)
                if delay is None:
                    delay = _backoff_seconds(attempt)
                time.sleep(delay)
            continue

        ended_at = datetime.now(timezone.utc)
        tracing.record_call(
            role=role,
            model_key=model_key,
            model_name=model_name,
            attempt=attempt,
            started_at=started_at,
            ended_at=ended_at,
            success=True,
            input_data=input_data,
            output=format_output(result),
        )
        return result

    raise ProviderError(f"Échec de l'appel au modèle {model_key!r} après {MAX_RETRIES} tentatives : {last_error}")


class OllamaCloudClient:
    """Client minimal pour l'API de chat d'un modèle Ollama cloud.

    Attributes:
        spec: Spécification du modèle appelé (URL, clé API, timeout, ...).
        role: Rôle logique de ce client (`"model_write"`, `"model_judge"`,
            ...), utilisé uniquement pour le traçage des appels.
    """

    def __init__(self, spec: ModelSpec, *, role: str = "unspecified"):
        """Initialise le client pour un modèle donné.

        Args:
            spec: Spécification résolue du modèle (voir `config.ModelSpec`).
            role: Rôle logique de ce client, à des fins de traçage.
        """
        self.spec = spec
        self.role = role

    def _chat_url(self) -> str:
        """Construit l'URL de l'endpoint de chat.

        Returns:
            L'URL complète `.../api/chat`, sans dupliquer le suffixe `/api`
            si `spec.base_url` l'inclut déjà (cas de certaines URLs Ollama
            cloud configurées avec `/api` en fin de chemin).
        """
        base = self.spec.base_url.rstrip("/")
        if base.endswith("/api"):
            return base + "/chat"
        return base + "/api/chat"

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> str:
        """Envoie une conversation au modèle et retourne sa réponse texte.

        Retente jusqu'à `MAX_RETRIES` fois (backoff exponentiel avec jitter,
        `Retry-After` respecté sur un 429) en cas d'erreur réseau, HTTP ou de
        réponse mal formée.

        Args:
            messages: Historique de la conversation, au format
                `[{"role": ..., "content": ...}, ...]`.
            temperature: Température d'échantillonnage optionnelle,
                transmise dans `options` si fournie.

        Returns:
            Le contenu texte de la réponse du modèle.

        Raises:
            ProviderError: Si toutes les tentatives échouent.
        """
        url = self._chat_url()
        headers = {"Authorization": f"Bearer {self.spec.api_key}"}
        payload: dict = {"model": self.spec.name, "messages": messages, "stream": False}
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        def _call() -> str:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.spec.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

        return _with_retries(
            role=self.role,
            model_key=self.spec.key,
            model_name=self.spec.name,
            input_data=messages,
            format_output=lambda text: text,
            call=_call,
        )


def _images_url(base_url: str) -> str:
    """Construit l'URL de l'endpoint de génération d'images à partir d'une base OpenAI.

    Certaines configurations pointent `base_url` vers un endpoint précis de
    l'API (ex: `.../v1/responses`) plutôt que vers la racine `/v1`. Cette
    fonction tronque après le segment `/v1` s'il est présent, pour éviter
    de construire une URL invalide comme `.../v1/responses/images/generations`.

    Args:
        base_url: URL de base résolue pour le modèle (variable `url` du provider `openai`).

    Returns:
        L'URL complète `.../v1/images/generations`. Si `base_url` ne
        contient pas de segment `/v1`, le suffixe est simplement ajouté à
        `base_url` (sans slash final).
    """
    idx = base_url.find("/v1")
    if idx != -1:
        root = base_url[: idx + len("/v1")]
    else:
        root = base_url.rstrip("/")
    return root.rstrip("/") + "/images/generations"


class OpenAIImageClient:
    """Client minimal pour l'API Images d'OpenAI (génération d'image à partir d'un prompt texte).

    Attributes:
        spec: Spécification du modèle appelé (URL, clé API, timeout, ...).
        role: Rôle logique de ce client (normalement `"model_image"`),
            utilisé uniquement pour le traçage des appels.
    """

    def __init__(self, spec: ModelSpec, *, role: str = "unspecified"):
        """Initialise le client pour un modèle donné.

        Args:
            spec: Spécification résolue du modèle (voir `config.ModelSpec`).
            role: Rôle logique de ce client, à des fins de traçage.
        """
        self.spec = spec
        self.role = role

    def generate_image(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        """Génère une image à partir d'un prompt texte.

        Retente jusqu'à `MAX_RETRIES` fois (backoff exponentiel avec jitter,
        `Retry-After` respecté sur un 429) en cas d'erreur réseau, HTTP ou de
        réponse mal formée.

        Args:
            prompt: Description textuelle de l'image à générer.
            size: Dimensions demandées (ex: `"1024x1024"`, `"1536x1024"`).

        Returns:
            Les octets bruts de l'image (PNG), décodés depuis `b64_json` si
            présent dans la réponse, sinon téléchargés depuis `url`.

        Raises:
            ProviderError: Si toutes les tentatives échouent, ou si la
                réponse ne contient ni `b64_json` ni `url` exploitable.
        """
        url = _images_url(self.spec.base_url)
        headers = {"Authorization": f"Bearer {self.spec.api_key}"}
        payload = {"model": self.spec.name, "prompt": prompt, "size": size, "n": 1}

        def _call() -> bytes:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.spec.timeout)
            resp.raise_for_status()
            item = resp.json()["data"][0]
            b64_json = item.get("b64_json")
            if b64_json:
                return base64.b64decode(b64_json)
            image_url = item.get("url")
            if image_url:
                img_resp = requests.get(image_url, timeout=self.spec.timeout)
                img_resp.raise_for_status()
                return img_resp.content
            raise ValueError("La réponse ne contient ni 'b64_json' ni 'url' exploitable.")

        return _with_retries(
            role=self.role,
            model_key=self.spec.key,
            model_name=self.spec.name,
            input_data=prompt,
            format_output=lambda data: f"<image binaire, {len(data)} octets>",
            call=_call,
        )
