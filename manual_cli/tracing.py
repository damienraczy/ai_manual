"""Traçage des appels aux modèles, pour diagnostiquer les temps de traitement.

Chaque tentative d'appel (succès ou échec) est journalisée en JSON Lines
dans `output_dir/traces/calls.jsonl` : rôle, modèle, horodatages, durée,
entrée envoyée, sortie reçue, numéro de tentative, erreur éventuelle. Le
traçage est inactif tant que `configure()` n'a pas été appelé (comportement
par défaut, y compris dans les tests), et l'écriture est thread-safe pour la
génération parallèle de sections (`manual write -w`).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

TRACE_RELATIVE_PATH = Path("traces") / "calls.jsonl"

_lock = threading.Lock()
_trace_path: Path | None = None


def configure(output_dir: Path) -> Path:
    """Active le traçage pour ce répertoire de sortie.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le chemin du fichier de trace (son répertoire parent est créé si
        besoin ; le fichier lui-même n'est créé qu'au premier appel journalisé).
    """
    global _trace_path
    path = output_dir / TRACE_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _trace_path = path
    return path


def reset() -> None:
    """Désactive le traçage (utilisé pour isoler les tests entre eux)."""
    global _trace_path
    with _lock:
        _trace_path = None


def is_configured() -> bool:
    """Indique si le traçage est actif pour cette exécution.

    Returns:
        `True` si `configure()` a été appelé et n'a pas été suivi de `reset()`.
    """
    return _trace_path is not None


def record_call(
    *,
    role: str,
    model_key: str,
    model_name: str,
    attempt: int,
    started_at: datetime,
    ended_at: datetime,
    success: bool,
    input_data: Any,
    output: str | None = None,
    error: str | None = None,
) -> None:
    """Journalise une tentative d'appel à un modèle.

    N'écrit rien si le traçage n'a pas été activé via `configure()`.

    Args:
        role: Rôle du modèle appelé (`"model_write"`, `"model_judge"`,
            `"model_think"`, `"model_rewriter"` ou `"model_image"`).
        model_key: Clé du modèle (voir `config.ModelSpec.key`).
        model_name: Nom du modèle transmis au fournisseur.
        attempt: Numéro de la tentative (1-indexé).
        started_at: Horodatage de début de la tentative.
        ended_at: Horodatage de fin de la tentative.
        success: `True` si la tentative a abouti.
        input_data: Entrée envoyée au modèle (liste de messages pour un
            chat, prompt texte pour une génération d'image) — sérialisée
            telle quelle en JSON.
        output: Sortie reçue en cas de succès (texte, ou description
            courte pour un contenu binaire comme une image).
        error: Message d'erreur en cas d'échec.
    """
    if _trace_path is None:
        return

    record = {
        "role": role,
        "model_key": model_key,
        "model_name": model_name,
        "attempt": attempt,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "duration_seconds": (ended_at - started_at).total_seconds(),
        "success": success,
        "input": input_data,
        "output": output,
        "error": error,
    }
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _lock:
        with open(_trace_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_calls(trace_path: Path) -> list[dict]:
    """Charge tous les appels journalisés dans un fichier de trace.

    Args:
        trace_path: Chemin du fichier `calls.jsonl`.

    Returns:
        La liste des enregistrements, dans l'ordre du fichier. Liste vide si
        le fichier n'existe pas encore. Une ligne vide ou au JSON invalide
        est ignorée plutôt que de faire échouer la lecture (le fichier peut
        être en cours d'écriture par une autre section en parallèle).
    """
    if not trace_path.exists():
        return []

    calls: list[dict] = []
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return calls
