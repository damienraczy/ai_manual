"""Introduction et conclusion : sections hors parties, numérotées 0 et N+1."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from manual_cli import generator
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Cadre, Chapitre, GeneratedTocSchema, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, load_state, render_plan, save_state, toc_from_yaml, toc_to_yaml


def make_toc(intro=True, conclusion=True) -> TocSchema:
    return TocSchema(
        titre_manuel="M",
        introduction=Cadre(titre="Introduction", description="ouvre", sous_sections=[SousSection(numero="?", titre="Public", description="à qui")]) if intro else None,
        parties=[
            Partie(numero="I", titre="P", chapitres=[
                Chapitre(numero=1, titre="Un", description="d1", sous_sections=[]),
                Chapitre(numero=2, titre="Deux", description="d2", sous_sections=[]),
            ])
        ],
        conclusion=Cadre(titre="Conclusion", description="ferme") if conclusion else None,
    )


def test_state_puts_the_introduction_first_and_the_conclusion_last():
    state = build_manual_state(make_toc())

    assert [(s.numero, s.role, s.titre) for s in state.sections] == [
        (0, "introduction", "Introduction"),
        (1, "chapitre", "Un"),
        (2, "chapitre", "Deux"),
        (3, "conclusion", "Conclusion"),
    ]
    assert state.sections[0].filename == "00_introduction.md"
    assert state.sections[3].filename == "03_conclusion.md"
    assert state.sections[0].intitule == "Introduction" and state.sections[1].intitule == "1. Un"


def test_state_without_framing_is_unchanged():
    state = build_manual_state(make_toc(intro=False, conclusion=False))
    assert [s.numero for s in state.sections] == [1, 2]


def test_plan_file_round_trips_the_framing_and_derives_their_numbers(tmp_path):
    save_state(tmp_path, build_manual_state(make_toc()))
    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    assert plan.index("introduction:") < plan.index("parties:") < plan.index("conclusion:")

    loaded = load_state(tmp_path)

    assert loaded.toc.introduction.sous_sections[0].numero == "0.1"
    assert loaded.sections[-1].numero == 3 and loaded.sections[-1].role == "conclusion"
    assert toc_from_yaml(toc_to_yaml(loaded.toc)) == loaded.toc


def test_a_conclusion_is_renumbered_when_a_chapter_is_inserted_by_hand(tmp_path):
    save_state(tmp_path, build_manual_state(make_toc()))
    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    plan = plan.replace("conclusion:", "      - titre: Trois\n        description: d3\n        sous_sections: []\nconclusion:")
    (tmp_path / "toc.yml").write_text(plan, encoding="utf-8")

    assert load_state(tmp_path).sections[-1].numero == 4


def test_render_plan_lists_the_framing_without_a_part_heading():
    plan = render_plan(build_manual_state(make_toc()), current_numero=0)
    lines = plan.splitlines()
    assert lines[0] == "- Introduction — ouvre  ← CHAPITRE EN COURS"
    assert "- 3. Conclusion" not in plan and "- Conclusion — ferme" in plan
    assert "### Partie I — P" in plan


def test_a_generated_plan_needs_described_framing_sub_sections():
    payload = make_toc().model_dump()
    payload["introduction"]["sous_sections"][0]["description"] = ""
    for chapitre in payload["parties"][0]["chapitres"]:
        chapitre["sous_sections"] = []
    with pytest.raises(ValidationError, match="Public"):
        GeneratedTocSchema.model_validate(payload)


# --- écriture -----------------------------------------------------------------------


def spec(key):
    return ModelSpec(key=key, provider="ollama", name=key, base_url="http://x", api_key="k", timeout=1)


@pytest.fixture
def cfg():
    return AppConfig(roles={r: spec(r) for r in ("model_write", "model_judge", "model_think", "model_rewriter")})


class Router:
    """Répond d'après le texte du prompt et note l'ordre des rédactions."""

    def __init__(self):
        self.written: list[str] = []
        self.write_prompts: dict[str, str] = {}

    def client_for(self, role):
        outer = self

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                if role == "model_write":
                    numero = prompt.split("- Numéro : ")[1].split("\n")[0]
                    outer.written.append(numero)
                    outer.write_prompts[numero] = prompt
                    return f"## texte\n--- Fin de la section {numero} — Dis « continue » pour la suivante ---"
                if role == "model_judge":
                    return '```json\n{"verdict": "accept", "issues": []}\n```'
                return "mémoire"

        return _C()


def test_framing_sections_are_written_after_the_chapters_with_their_own_guidance(tmp_path, cfg, subject, monkeypatch):
    save_state(tmp_path, build_manual_state(make_toc(), subject="test-sujet"))
    router = Router()
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))

    results = generator.run_write(cfg, tmp_path, subject, workers=1)

    assert [s.numero for s in results] == [0, 1, 2, 3]
    assert router.written[:2] == ["1", "2"] and set(router.written[2:]) == {"0", "3"}
    assert "## Introduction" in router.write_prompts["0"]
    assert "introduction" in router.write_prompts["0"].lower() and "conclusion" in router.write_prompts["3"].lower()
    assert "## 1. Un" in router.write_prompts["1"]
    assert (tmp_path / "00_introduction.md").is_file() and (tmp_path / "03_conclusion.md").is_file()


def test_toc_markdown_shows_the_framing(tmp_path):
    state = build_manual_state(make_toc())
    generator._write_toc_markdown(tmp_path, state)
    text = (tmp_path / "00_toc.md").read_text(encoding="utf-8")
    assert "**Introduction**" in text and "**Conclusion**" in text and "*ouvre*" in text
