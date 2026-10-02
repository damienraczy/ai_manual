"""Parcours complet sur un sujet autre que Prompt Engineering, LLM simulé.

Vérifie que rien en aval (plan, rédaction, relecture, mémoire, publication)
ne dépend du sujet fourni avec le dépôt.
"""

from __future__ import annotations

import json

import pytest

from manual_cli import generator, publish, subject_author
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.state import load_state
from manual_cli.subjects import load_subject

SPEC = {
    "titre": "Jardinage urbain",
    "langue": "français",
    "role": "Tu es un jardinier-paysagiste et formateur.",
    "objectif": "Écrire un manuel pour cultiver en ville.",
    "public": "citadins débutants",
    "niveau": "débutant → confirmé",
    "ton": "chaleureux",
    "plan_directeur": "bases → potager → entretien",
    "exclusions": [],
    "instructions": "",
    "criteres": [{"id": "saison_indiquee", "description": "La saison est précisée.", "severity": "bloquant"}],
}
TOC = {
    "titre_manuel": "Le jardinage urbain",
    "parties": [
        {
            "numero": "I",
            "titre": "Bases",
            "chapitres": [
                {"numero": 1, "titre": "Le balcon", "description": "d", "sous_sections": [{"numero": "1.1", "titre": "Lumière", "description": "mesurer l'ensoleillement"}]}
            ],
        }
    ],
}


def block(payload: dict) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class Scripted:
    """Client LLM simulé : répond selon le rôle et le contenu du prompt."""

    def __init__(self):
        self.seen: list[tuple[str, list[dict]]] = []

    def client_for(self, role: str):
        outer = self

        class _C:
            def chat(self, messages: list[dict]) -> str:
                outer.seen.append((role, messages))
                user = messages[-1]["content"]
                if role == "model_write" and user.startswith("# Tâche : cadrer un nouveau manuel"):
                    return block(SPEC)
                if role == "model_write" and user.startswith("# Tâche : générer la table des matières"):
                    return block(TOC)
                if role == "model_write" and user.startswith("# Tâche : rédiger une section"):
                    return "## 1. Le balcon\ncontenu\n" + generator.SECTION_END_TEMPLATE.format(numero=1)
                if role == "model_write":
                    return "Post d'accroche {ARTICLE_URL}"
                if role == "model_judge":
                    return block({"verdict": "accept", "issues": []})
                return "mémoire à jour"

        return _C()


@pytest.fixture
def cfg() -> AppConfig:
    spec = ModelSpec(key="k", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)
    return AppConfig(roles={r: spec for r in ("model_write", "model_judge", "model_think", "model_rewriter")})


def test_a_generated_subject_goes_all_the_way_to_a_publishable_section(tmp_path, cfg, monkeypatch):
    scripted = Scripted()
    monkeypatch.setattr(subject_author, "_client", lambda c: scripted.client_for("model_write"))
    monkeypatch.setattr(generator, "_client", lambda c, role: scripted.client_for(role))
    monkeypatch.setattr(publish, "_write_client", lambda c: scripted.client_for("model_write"))
    subjects_dir, output_dir = tmp_path / "subjects", tmp_path / "out"

    subject_author.generate_subject(cfg, "jardinage", "Manuel de jardinage urbain", subjects_dir)
    subject = load_subject("jardinage", subjects_dir)
    generator.generate_toc(cfg, output_dir, subject)
    results = generator.run_write(cfg, output_dir, subject)
    publish_dir = publish.publish_section(cfg, output_dir, 1, system_prompt=subject.system_prompt(), generate_image=False)

    assert load_state(output_dir).subject == "jardinage"
    assert [s.status for s in results] == ["done"]
    assert (publish_dir / "article.html").is_file()
    toc_call = next(m for _, m in scripted.seen if m[-1]["content"].startswith("# Tâche : générer la table des matières"))
    assert "jardinier-paysagiste" in toc_call[0]["content"]
    assert "bases → potager → entretien" in toc_call[-1]["content"]
    judge_prompt = next(m for r, m in scripted.seen if r == "model_judge")[-1]["content"]
    assert "saison_indiquee" in judge_prompt
    assert "Prompt Engineering" not in json.dumps([m for _, m in scripted.seen], ensure_ascii=False)
