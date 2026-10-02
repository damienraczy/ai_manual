from __future__ import annotations

import json

import pytest

from manual_cli import glossary
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.generator import GeneratorError
from manual_cli.schemas import Chapitre, Partie, TocSchema
from manual_cli.state import build_manual_state, save_state


def entries_json(*pairs, chapitres=None):
    items = []
    for terme, definition in pairs:
        item = {"terme": terme, "definition": definition}
        if chapitres is not None:
            item["chapitres"] = chapitres
        items.append(item)
    return "```json\n" + json.dumps({"entrees": items}) + "\n```"


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return self.replies.pop(0)


@pytest.fixture
def cfg():
    spec = ModelSpec(key="w", provider="ollama", name="w:cloud", base_url="http://x", api_key="k", timeout=30)
    return AppConfig(roles={"model_write": spec})


def make_state(statuses):
    chapitres = [Chapitre(numero=i + 1, titre=f"Chap {i + 1}", description="d", sous_sections=[]) for i in range(len(statuses))]
    state = build_manual_state(TocSchema(titre_manuel="Mon manuel", parties=[Partie(numero="I", titre="P", chapitres=chapitres)]))
    for section, status in zip(state.sections, statuses):
        section.status = status
    return state


def write_chapters(tmp_path, state):
    for s in state.sections:
        if s.status == "done":
            (tmp_path / s.filename).write_text(f"## {s.numero}. {s.titre}\ntexte {s.numero}\n", encoding="utf-8")


def test_build_glossary_extracts_per_chapter_then_merges_and_writes_sorted_file(tmp_path, cfg, monkeypatch):
    state = make_state(["done", "pending", "done"])
    save_state(tmp_path, state)
    write_chapters(tmp_path, state)
    client = FakeClient(
        [
            entries_json(("Prompt", "consigne"), ("Zéro-shot", "sans exemple")),
            entries_json(("prompt", "texte envoyé au modèle")),
            entries_json(("Zéro-shot", "sans exemple donné"), ("Écart", "différence"), ("Prompt", "consigne envoyée"), chapitres=[1, 3]),
        ]
    )
    monkeypatch.setattr(glossary, "_client", lambda cfg, role: client)

    result = glossary.build_glossary(cfg, tmp_path)

    assert result.chapters == [1, 3]
    assert "texte 1" in client.prompts[0] and "texte 3" in client.prompts[1]
    assert "Prompt" in client.prompts[2] and "chap. 1" in client.prompts[2]
    text = (tmp_path / "glossaire.md").read_text(encoding="utf-8")
    assert text.startswith("# Glossaire")
    assert text.index("**Écart**") < text.index("**Prompt**") < text.index("**Zéro-shot**")
    assert "**Prompt** — consigne envoyée (chap. 1, 3)" in text
    assert result.path == tmp_path / "glossaire.md"


def test_build_glossary_without_manifest_fails(tmp_path, cfg):
    with pytest.raises(GeneratorError, match="init"):
        glossary.build_glossary(cfg, tmp_path)


def test_build_glossary_without_done_chapter_fails(tmp_path, cfg):
    save_state(tmp_path, make_state(["pending"]))
    with pytest.raises(GeneratorError, match="terminé"):
        glossary.build_glossary(cfg, tmp_path)


def test_build_glossary_missing_chapter_file_fails(tmp_path, cfg):
    save_state(tmp_path, make_state(["done"]))
    with pytest.raises(GeneratorError, match="introuvable"):
        glossary.build_glossary(cfg, tmp_path)


def test_client_builds_ollama_client_from_role(cfg):
    client = glossary._client(cfg, "model_write")
    assert client.role == "model_write"
