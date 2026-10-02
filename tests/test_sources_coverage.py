"""Couverture jugée, matière dans le plan et suivi dans `status`."""

from __future__ import annotations

import json

import pytest

from manual_cli import generator, sources, sources_assign
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Cadre, Chapitre, Partie, TocSchema
from manual_cli.sources import FileEntry, SourceIndex, Unite
from manual_cli.sources_assign import ChapterUnits, SourcesMap
from manual_cli.state import build_manual_state, load_state, save_state


def make_cfg(budget=10000) -> AppConfig:
    spec = ModelSpec(key="m", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)
    roles = {r: spec for r in ("model_write", "model_judge", "model_think", "model_rewriter")}
    return AppConfig(
        roles=roles,
        settings={"sources": {"max_chunk_chars": 1000, "assign_batch": 10, "max_prompt_chars": budget}},
    )


def make_state():
    toc = TocSchema(
        titre_manuel="M",
        parties=[Partie(numero="I", titre="P", chapitres=[Chapitre(numero=1, titre="Un", description="d1", sous_sections=[])])],
    )
    return build_manual_state(toc, "test-sujet")


def unit(n, utilite="haute", themes=("t",), type_="idee", enonce=None) -> Unite:
    return Unite(
        id=f"a.md#{n}", source="a.md", ligne=n, type=type_, enonce=enonce or f"énoncé {n}",
        extrait=f"x{n}", utilite=utilite, themes=list(themes),
    )


def setup_matter(out, units, principal=None):
    index = SourceIndex(fichiers={"a.md": FileEntry(hash="h", unites=units)})
    (out / "sources_index.json").write_text(index.model_dump_json(), encoding="utf-8")
    sources_assign.save_map(out, SourcesMap(chapitres={"Un": ChapterUnits(principal=principal or [u.id for u in units])}))
    return index


# --- matière d'un chapitre -------------------------------------------------------------


def test_section_matter_lists_units_to_cover(tmp_path):
    setup_matter(tmp_path, [unit(1), unit(2, utilite="moyenne")])

    matter = sources_assign.section_matter(make_cfg(), tmp_path, make_state().sections[0])

    assert [u.id for u in matter.must_cover] == ["a.md#1"]
    assert "[a.md#2]" in matter.text


def test_section_matter_does_not_demand_units_omitted_for_lack_of_room(tmp_path):
    setup_matter(tmp_path, [unit(1, enonce="a" * 300), unit(2, enonce="b" * 300)])

    matter = sources_assign.section_matter(make_cfg(budget=900), tmp_path, make_state().sections[0])

    assert matter.omitted and all(u.id not in matter.omitted for u in matter.must_cover)


def test_section_matter_is_empty_without_index(tmp_path):
    matter = sources_assign.section_matter(make_cfg(), tmp_path, make_state().sections[0])

    assert matter.text == "" and matter.must_cover == []


# --- résumé pour le plan ---------------------------------------------------------------


def test_plan_summary_is_empty_without_useful_units():
    assert sources_assign.plan_summary(SourceIndex(), 1000) == ""
    assert sources_assign.plan_summary(SourceIndex(fichiers={"a.md": FileEntry(hash="h", unites=[unit(1, utilite="nulle")])}), 1000) == ""


def test_plan_summary_groups_units_by_theme():
    index = SourceIndex(
        fichiers={
            "a.md": FileEntry(
                hash="h",
                unites=[
                    unit(1, themes=("contexte",), enonce="le contexte compte"),
                    unit(2, themes=("Contexte", "autre"), type_="fait"),
                    unit(3, themes=("itération",)),
                    unit(4, themes=()),
                ],
            )
        }
    )

    text = sources_assign.plan_summary(index, 5000)

    assert "contexte (2 unités" in text and "itération (1 unité" in text and "divers (1 unité" in text
    assert "le contexte compte" in text
    assert "plan" in text.lower()


def test_plan_summary_respects_its_budget_and_says_what_it_dropped():
    units = [unit(i, themes=(f"thème{i}",)) for i in range(1, 30)]
    index = SourceIndex(fichiers={"a.md": FileEntry(hash="h", unites=units)})

    text = sources_assign.plan_summary(index, 700)

    assert len(text) <= 700 + 200 and "autre(s) thème(s) non listé(s)" in text


# --- critère de couverture -------------------------------------------------------------


class JudgeClient:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def chat(self, messages):
        self.prompts.append(messages[-1]["content"])
        return "```json\n" + json.dumps(self.answer) + "\n```"


def judge(monkeypatch, answer, must_cover):
    client = JudgeClient(answer)
    monkeypatch.setattr(generator, "_client", lambda cfg, role: client)
    verdict = generator._judge_section(
        make_cfg(), make_state().sections[0], "texte", {"generic": [], "parties": {}}, must_cover=must_cover
    )
    return verdict, client


def test_judge_receives_a_blocking_coverage_criterion(monkeypatch):
    verdict, client = judge(monkeypatch, {"verdict": "accept", "issues": []}, [unit(1, enonce="idée à couvrir")])

    prompt = client.prompts[0]
    assert "[bloquant] `couverture_sources`" in prompt and "[a.md#1] idée à couvrir" in prompt
    assert "écarté" in prompt and verdict.verdict == "accept"


def test_judge_without_matter_has_no_coverage_criterion(monkeypatch):
    _, client = judge(monkeypatch, {"verdict": "accept", "issues": []}, [])

    assert "couverture_sources" not in client.prompts[0]


def test_local_guard_forces_revision_when_coverage_is_reported_missing(monkeypatch):
    answer = {"verdict": "accept", "issues": [{"id": "couverture_sources", "severity": "bloquant", "detail": "[a.md#1] oublié"}]}

    verdict, _ = judge(monkeypatch, answer, [unit(1)])

    assert verdict.verdict == "revise"


# --- écarts déclarés -------------------------------------------------------------------


def test_extract_discards_removes_the_comments_and_returns_them():
    text = "## 1. Un\ncorps\n\n<!-- écarté [a.md#1] : hors sujet -->\n<!--écarté [b.md#2] :  douteux  -->\n"

    clean, discards = generator._extract_discards(text)

    assert clean == "## 1. Un\ncorps"
    assert discards == ["a.md#1 : hors sujet", "b.md#2 : douteux"]


def test_extract_discards_leaves_other_comments_alone():
    text = "texte <!-- autre chose --> suite"

    assert generator._extract_discards(text) == (text, [])


# --- rédaction : suivi et nettoyage ----------------------------------------------------


class Router:
    def __init__(self, draft):
        self.draft = draft
        self.judge_prompts = []

    def client_for(self, role):
        outer = self

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                if role == "model_write":
                    return outer.draft
                if role == "model_judge":
                    outer.judge_prompts.append(prompt)
                    return '```json\n{"verdict": "accept", "issues": []}\n```'
                return "mémoire"

        return _C()


DRAFT = (
    "## 1. Un\ncontenu\n\n<!-- écarté [a.md#2] : hors sujet -->\n"
    "--- Fin de la section 1 — Dis « continue » pour la suivante ---"
)


def test_write_section_records_coverage_and_strips_discard_comments(tmp_path, subject, monkeypatch):
    setup_matter(tmp_path, [unit(1), unit(2), unit(3, utilite="moyenne")])
    router = Router(DRAFT)
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))
    state = make_state()
    save_state(tmp_path, state)

    section = generator.write_section(
        make_cfg(), tmp_path, state, state.sections[0], {"generic": [], "parties": {}}, system_prompt="S"
    )

    written = (tmp_path / section.filename).read_text(encoding="utf-8")
    assert "écarté" not in written and written.startswith("## 1. Un")
    assert section.sources_total == 2 and section.sources_ecartees == ["a.md#2 : hors sujet"]
    assert "couverture_sources" in router.judge_prompts[0]
    assert load_state(tmp_path).sections[0].sources_total == 2


def test_write_section_without_matter_records_nothing(tmp_path, monkeypatch):
    router = Router("## 1. Un\nx\n--- Fin de la section 1 — Dis « continue » pour la suivante ---")
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))
    state = make_state()
    save_state(tmp_path, state)

    section = generator.write_section(
        make_cfg(), tmp_path, state, state.sections[0], {"generic": [], "parties": {}}, system_prompt="S"
    )

    assert section.sources_total == 0 and section.sources_ecartees == []
    assert "couverture_sources" not in router.judge_prompts[0]


def test_improve_section_records_coverage_too(tmp_path, monkeypatch):
    setup_matter(tmp_path, [unit(1), unit(2)])
    router = Router(DRAFT)
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))
    state = make_state()
    save_state(tmp_path, state)
    (tmp_path / state.sections[0].filename).write_text("## 1. Un\nancien\n", encoding="utf-8")

    result = generator.improve_section(
        make_cfg(), tmp_path, state, state.sections[0], {"generic": [], "parties": {}}, system_prompt="S"
    )

    assert result.accepted
    assert result.section.sources_total == 2 and result.section.sources_ecartees == ["a.md#2 : hors sujet"]
    assert "écarté" not in (tmp_path / state.sections[0].filename).read_text(encoding="utf-8")


# --- suivi persistant ------------------------------------------------------------------


def test_tracking_round_trips_coverage_and_reads_old_manifests(tmp_path):
    state = make_state()
    state.sections[0].sources_total = 3
    state.sections[0].sources_ecartees = ["a.md#2 : hors sujet"]
    state.sections[0].status = "done"
    save_state(tmp_path, state)

    loaded = load_state(tmp_path).sections[0]
    assert loaded.sources_total == 3 and loaded.sources_ecartees == ["a.md#2 : hors sujet"]

    raw = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for entry in raw["sections"]:
        entry.pop("sources_total", None), entry.pop("sources_ecartees", None)
    (tmp_path / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    assert load_state(tmp_path).sections[0].sources_total == 0


def test_tracking_stays_lean_without_matter(tmp_path):
    save_state(tmp_path, make_state())

    raw = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert "sources_total" not in raw["sections"][0]
