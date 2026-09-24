"""Application Flask de visualisation des traces d'appels LLM.

Sert une page unique (`static/viewer.html`) qui charge les appels journalisés
via `/api/calls` et les affiche sous forme de tableau et d'un graphique
chronologique des durées — utile pour repérer une dérive des temps de
traitement au fil de l'avancement (voir `manual_cli.tracing`).
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify

from ..tracing import read_calls

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(trace_path: Path) -> Flask:
    """Construit l'application Flask de visualisation des traces.

    Args:
        trace_path: Chemin du fichier `calls.jsonl` à servir (peut ne pas
            encore exister : l'API renverra alors une liste vide).

    Returns:
        Une application Flask avec deux routes : `/` (page HTML) et
        `/api/calls` (les appels journalisés, en JSON).
    """
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index() -> tuple[str, int, dict[str, str]]:
        html = (STATIC_DIR / "viewer.html").read_text(encoding="utf-8")
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/api/calls")
    def api_calls():
        return jsonify(read_calls(trace_path))

    return app
