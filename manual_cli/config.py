"""Chargement de la configuration LLM depuis `params.yml` et `~/.env`.

Résout les rôles LLM (rédacteur, juge, mémoire, réécrivain, et l'optionnel
`model_image`) en instances de `ModelSpec` prêtes à l'emploi, en validant
que chaque rôle pointe vers un modèle existant, dont le provider est
autorisé pour ce rôle, et que les variables d'environnement associées (URL,
clé API) sont bien définies.

`AppConfig` produite par `load_config()` recharge `params.yml` (et `~/.env`)
à chaque appel de `.role(...)`, plutôt que de figer une résolution unique au
démarrage : un changement de `params.yml` (ex: un timeout ajusté pendant une
longue exécution de `manual write`) est donc pris en compte dès le prochain
appel LLM, sans avoir à relancer la commande.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARAMS_PATH = PROJECT_ROOT / "params.yml"
DEFAULT_ENV_PATH = Path.home() / ".env"

REQUIRED_ROLES = ("model_write", "model_judge", "model_think", "model_rewriter")
IMAGE_ROLE = "model_image"
SUPPORTED_PROVIDER = "ollama"
SUPPORTED_IMAGE_PROVIDERS = ("openai",)


def _allowed_providers(role_name: str) -> tuple[str, ...]:
    """Fournisseurs autorisés pour un rôle donné.

    Args:
        role_name: Nom du rôle (voir `REQUIRED_ROLES` et `IMAGE_ROLE`).

    Returns:
        `SUPPORTED_IMAGE_PROVIDERS` pour le rôle `model_image` (génération
        d'image), `(SUPPORTED_PROVIDER,)` pour tous les autres rôles (texte,
        Ollama uniquement).
    """
    return SUPPORTED_IMAGE_PROVIDERS if role_name == IMAGE_ROLE else (SUPPORTED_PROVIDER,)


class ConfigError(Exception):
    """Configuration invalide ou incomplète (rôle, modèle ou variable d'environnement manquant)."""


class ModelSpec(BaseModel):
    """Description résolue d'un modèle prêt à être appelé.

    Attributes:
        key: Clé du modèle telle que déclarée sous `params.yml -> models`.
        provider: Fournisseur du modèle (`"ollama"`, ou `"openai"` pour `model_image`).
        name: Nom du modèle à transmettre à l'API du fournisseur.
        base_url: URL de base résolue depuis la variable d'environnement `url`.
        api_key: Clé API résolue depuis la variable d'environnement `api_key`.
        timeout: Délai d'attente HTTP en secondes.
    """

    key: str
    provider: str
    name: str
    base_url: str
    api_key: str
    timeout: int


def _read_role_map(params_path: Path) -> dict:
    """Lit uniquement le mapping des rôles depuis `params.yml`.

    Args:
        params_path: Chemin du fichier YAML de configuration des modèles.

    Returns:
        Le dictionnaire `llm_config.llm` (rôle -> clé de modèle), vide si absent.
    """
    with open(params_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    llm_config = raw.get("llm_config") or {}
    return llm_config.get("llm") or {}


def _resolve_role(name: str, *, params_path: Path, env_path: Path) -> ModelSpec:
    """Résout un rôle en relisant `params.yml` et `~/.env` à cet instant précis.

    Args:
        name: Nom du rôle à résoudre (ex: `"model_write"`).
        params_path: Chemin du fichier YAML de configuration des modèles.
        env_path: Chemin du fichier `.env` contenant les secrets.

    Returns:
        La spécification du modèle actuellement associé à ce rôle.

    Raises:
        ConfigError: Si le rôle est absent de `llm_config.llm`, s'il
            référence un modèle inconnu, si ce modèle utilise un provider
            non autorisé pour ce rôle, ou si une variable d'environnement
            nécessaire est manquante.
    """
    load_dotenv(env_path, override=False)

    with open(params_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    models = raw.get("models") or {}
    llm_config = raw.get("llm_config") or {}
    fallback_timeout = int(llm_config.get("timeout", 120))
    role_map = llm_config.get("llm") or {}

    if name not in role_map:
        raise ConfigError(f"Rôle manquant dans params.yml -> llm_config.llm : {name}")

    model_key = role_map[name]
    model_def = models.get(model_key)
    if model_def is None:
        raise ConfigError(
            f"Le rôle {name!r} référence le modèle {model_key!r}, absent de params.yml -> models."
        )

    provider = model_def.get("provider")
    allowed = _allowed_providers(name)
    if provider not in allowed:
        raise ConfigError(
            f"Le rôle {name!r} (modèle {model_key!r}) utilise le provider {provider!r}, "
            f"mais seul(s) {', '.join(allowed)!r} est/sont supporté(s) pour ce rôle."
        )

    url_env = model_def["url"]
    api_key_env = model_def["api_key"]
    base_url = os.environ.get(url_env)
    api_key = os.environ.get(api_key_env)
    missing_env = [v for v in (url_env, api_key_env) if not os.environ.get(v)]
    if missing_env:
        raise ConfigError(
            f"Variables d'environnement manquantes dans {env_path} : " + ", ".join(missing_env)
        )

    return ModelSpec(
        key=model_key,
        provider=provider,
        name=model_def["name"],
        base_url=base_url,
        api_key=api_key,
        timeout=int(model_def.get("timeout", fallback_timeout)),
    )


class AppConfig(BaseModel):
    """Configuration applicative, en mode statique ou en mode rechargement à la demande.

    Deux modes de construction :

    - **Statique** (`AppConfig(roles={...})`, sans `params_path`/`env_path`) :
      `.role(name)` lit simplement `roles`, sans jamais toucher au disque.
      Pratique pour construire une configuration en mémoire (tests, usage
      programmatique) sans fichier réel.
    - **Rechargement à la demande** (retourné par `load_config()`) :
      `.role(name)` relit `params.yml`/`~/.env` à chaque appel, pour que
      toute modification de `params.yml` (ex: un timeout ajusté en cours de
      route) soit prise en compte dès le prochain appel LLM.

    Attributes:
        roles: Rôles déjà résolus, utilisés tels quels en mode statique.
        params_path: Chemin de `params.yml`, si le rechargement à la demande est actif.
        env_path: Chemin du fichier `.env`, si le rechargement à la demande est actif.
    """

    roles: dict[str, ModelSpec] = {}
    params_path: Path | None = None
    env_path: Path | None = None

    def role(self, name: str) -> ModelSpec:
        """Récupère la spécification du modèle associé à un rôle.

        En mode rechargement à la demande, relit `params.yml`/`~/.env` avant
        de répondre, pour refléter tout changement effectué depuis le
        dernier appel (voir `AppConfig`).

        Args:
            name: Nom du rôle (ex: `"model_write"`).

        Returns:
            La spécification du modèle correspondant, à jour.

        Raises:
            ConfigError: Si le rôle n'est pas configuré.
        """
        if self.params_path is not None and self.env_path is not None:
            return _resolve_role(name, params_path=self.params_path, env_path=self.env_path)
        try:
            return self.roles[name]
        except KeyError:
            raise ConfigError(f"Rôle LLM inconnu ou non configuré : {name!r}")


def load_config(
    params_path: Path = DEFAULT_PARAMS_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
) -> AppConfig:
    """Valide la configuration LLM au démarrage et retourne une config à rechargement à la demande.

    Résout immédiatement chaque rôle requis (et `model_image` s'il est
    présent dans `llm_config.llm`) pour échouer tout de suite en cas de
    configuration incomplète, en rapportant tous les problèmes détectés en
    une seule fois plutôt qu'un par un. La configuration retournée ne fige
    toutefois pas ces valeurs : chaque appel ultérieur à `.role(...)` relit
    `params.yml`/`~/.env` (voir `AppConfig`).

    Args:
        params_path: Chemin du fichier YAML de configuration des modèles.
        env_path: Chemin du fichier `.env` contenant les secrets (URLs, clés API).

    Returns:
        Une configuration applicative en mode rechargement à la demande.

    Raises:
        ConfigError: Si un rôle requis est absent, s'il référence un modèle
            inconnu, si ce modèle utilise un provider non autorisé pour ce
            rôle, ou si une variable d'environnement nécessaire est manquante.
    """
    cfg = AppConfig(params_path=params_path, env_path=env_path)

    role_names = list(REQUIRED_ROLES)
    if IMAGE_ROLE in _read_role_map(params_path):
        role_names.append(IMAGE_ROLE)

    errors: list[str] = []
    for role_name in role_names:
        try:
            cfg.role(role_name)
        except ConfigError as exc:
            errors.append(str(exc))

    if errors:
        unique_errors = list(dict.fromkeys(errors))  # préserve l'ordre, déduplique
        raise ConfigError("; ".join(unique_errors))

    return cfg
