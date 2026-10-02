"""Les documents de référence alimentent la rédaction et l'amélioration des chapitres."""

from __future__ import annotations

import json

from manual_cli import generator, sources, sources_assign
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Cadre, Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, save_state


def make_cfg() -> AppConfig:
    spec = ModelSpec(key="m", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)
    roles = {r: spec for r in ("model_write", "model_judge", "model_think", "model_rewriter")}
    return AppConfig(
        roles=roles,
        settings={"sources": {"max_chunk_chars": 1000, "assign_batch": 10, "max_prompt_chars": 10000}},
    )


def make_state(subject_slug="test-sujet"):
    toc = TocSchema(
        titre_manuel="M",
        introduction=Cadre(titre="Introduction", description="ouvre"),
        parties=[Partie(numero="I", titre="P", chapitres=[Chapitre(numero=1, titre="Un", description="d1", sous_sections=[])])],
    )
    return build_manual_state(toc, subject_slug)


class Router:
    """Un client par rôle ; répond d'après le prompt et conserve les prompts de rédaction."""

    def __init__(self):
        self.write_prompts: list[str] = []
        self.think_prompts: list[str] = []

    def client_for(self, role):
        outer = self

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                if role == "model_write":
                    outer.write_prompts.append(prompt)
                    numero = prompt.split("- Numéro : ")[1].split("\n")[0]
                    return f"## texte\n--- Fin de la section {numero} — Dis « continue » pour la suivante ---"
                if role == "model_judge":
                    return '```json\n{"verdict": "accept", "issues": []}\n```'
                outer.think_prompts.append(prompt)
                if "extraire la matière" in prompt:
                    return '```json\n{"unites": [{"type": "idee", "enonce": "idée de l\'auteur", "extrait": "alpha", "utilite": "haute", "themes": ["t"]}]}\n```'
                if "affecter des unités" in prompt:
                    return '```json\n{"affectations": [{"unite": "notes.md#1", "principal": "Un", "secondaire": null}]}\n```'
                return "mémoire"

        return _C()


def install(monkeypatch) -> Router:
    router = Router()
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))
    monkeypatch.setattr(sources, "_client", lambda cfg, role: router.client_for(role))
    return router


def add_source(subject, text="alpha beta"):
    path = subject.directory / "sources" / "notes.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_run_write_without_sources_has_no_sources_block(tmp_path, subject, monkeypatch):
    router = install(monkeypatch)
    save_state(tmp_path, make_state())

    generator.run_write(make_cfg(), tmp_path, subject, [1], workers=1)

    assert "Matière fournie" not in router.write_prompts[0]
    assert not (tmp_path / "sources_index.json").exists()


def test_run_write_analyses_assigns_and_injects_the_matter(tmp_path, subject, monkeypatch):
    router = install(monkeypatch)
    add_source(subject)
    save_state(tmp_path, make_state())

    generator.run_write(make_cfg(), tmp_path, subject, [1, 0], workers=1)

    by_number = {p.split("- Numéro : ")[1].split("\n")[0]: p for p in router.write_prompts}
    assert "Matière fournie par l'auteur" in by_number["1"] and "idée de l'auteur" in by_number["1"]
    assert "[notes.md#1] **À COUVRIR**" in by_number["1"]
    assert "Matière fournie" not in by_number["0"]
    assert (tmp_path / "sources_index.json").is_file() and (tmp_path / "sources_map.yml").is_file()


def test_run_write_does_not_reanalyse_unchanged_sources(tmp_path, subject, monkeypatch):
    router = install(monkeypatch)
    add_source(subject)
    save_state(tmp_path, make_state())
    generator.run_write(make_cfg(), tmp_path, subject, [1], workers=1)
    extractions = sum("extraire la matière" in p for p in router.think_prompts)
    assignments = sum("affecter des unités" in p for p in router.think_prompts)

    generator.run_write(make_cfg(), tmp_path, subject, [1], workers=1)

    assert sum("extraire la matière" in p for p in router.think_prompts) == extractions
    assert sum("affecter des unités" in p for p in router.think_prompts) == assignments


def test_improve_injects_the_matter_too(tmp_path, subject, monkeypatch):
    router = install(monkeypatch)
    add_source(subject)
    state = make_state()
    save_state(tmp_path, state)
    (tmp_path / state.section_by_numero(1).filename).write_text("## 1. Un\nancien\n", encoding="utf-8")

    generator.run_improve(make_cfg(), tmp_path, subject, [1], workers=1)

    assert "idée de l'auteur" in router.write_prompts[0]
    assert "<version_actuelle>" in router.write_prompts[0]


def test_prepare_sources_is_a_no_op_without_documents(tmp_path, subject, monkeypatch):
    called = []
    monkeypatch.setattr(generator, "refresh_index", lambda *a, **k: called.append("refresh"))

    generator._prepare_sources(make_cfg(), tmp_path, subject, make_state())

    assert called == []


def test_prepare_sources_still_runs_when_documents_were_removed(tmp_path, subject, monkeypatch):
    router = install(monkeypatch)
    add_source(subject)
    state = make_state()
    generator._prepare_sources(make_cfg(), tmp_path, subject, state)
    (subject.directory / "sources" / "notes.md").unlink()

    generator._prepare_sources(make_cfg(), tmp_path, subject, state)

    assert sources.load_index(tmp_path).units() == []
    assert sources_assign.load_map(tmp_path).chapitres["Un"].principal == []


# --- plan ------------------------------------------------------------------------------


def toc_reply(chapters=("Un",)):
    payload = {
        "titre_manuel": "M",
        "parties": [
            {
                "numero": "I",
                "titre": "P",
                "chapitres": [
                    {"numero": i, "titre": t, "description": f"d{t}", "sous_sections": [{"numero": f"{i}.1", "titre": "S", "description": "r"}]}
                    for i, t in enumerate(chapters, 1)
                ],
            }
        ],
    }
    return "```json\n" + json.dumps(payload) + "\n```"


class TocRouter(Router):
    def __init__(self, toc):
        super().__init__()
        self.toc = toc
        self.toc_prompts = []

    def client_for(self, role):
        outer = self
        base = super().client_for(role)

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                if role == "model_write" and ("table des matières" in prompt.lower() or "PLAN DU SUJET" in prompt):
                    outer.toc_prompts.append(prompt)
                    return outer.toc
                return base.chat(messages)

        return _C()


def install_toc(monkeypatch, toc) -> TocRouter:
    router = TocRouter(toc)
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))
    monkeypatch.setattr(sources, "_client", lambda cfg, role: router.client_for(role))
    return router


def test_generate_toc_shows_the_matter_then_assigns_it_to_the_new_chapters(tmp_path, subject, monkeypatch):
    router = install_toc(monkeypatch, toc_reply())
    add_source(subject)

    generator.generate_toc(make_cfg(), tmp_path, subject)

    assert "Matière fournie par l'auteur" in router.toc_prompts[0] and "idée de l'auteur" in router.toc_prompts[0]
    assert sources_assign.load_map(tmp_path).chapitres["Un"].principal == ["notes.md#1"]


def test_generate_toc_without_sources_is_unchanged(tmp_path, subject, monkeypatch):
    router = install_toc(monkeypatch, toc_reply())

    generator.generate_toc(make_cfg(), tmp_path, subject)

    assert "Matière fournie" not in router.toc_prompts[0]
    assert not (tmp_path / "sources_index.json").exists()


def test_improve_toc_shows_the_matter_and_reassigns_after_a_change(tmp_path, subject, monkeypatch):
    router = install_toc(monkeypatch, toc_reply(("Un", "Deux")))
    add_source(subject)
    state = make_state()
    save_state(tmp_path, state)
    generator._prepare_sources(make_cfg(), tmp_path, subject, state)

    result = generator.improve_toc(make_cfg(), tmp_path, subject)

    assert result.modified
    assert "idée de l'auteur" in router.toc_prompts[0]
    assert "Un" in sources_assign.load_map(tmp_path).chapitres


def test_improve_toc_keeps_the_coverage_tracking_of_unchanged_chapters(tmp_path, subject, monkeypatch):
    install_toc(monkeypatch, toc_reply(("Un", "Deux", "Trois")))
    state = build_manual_state(
        TocSchema(
            titre_manuel="M",
            parties=[
                Partie(
                    numero="I",
                    titre="P",
                    chapitres=[
                        Chapitre(numero=1, titre="Un", description="dUn", sous_sections=[SousSection(numero="1.1", titre="S", description="r")]),
                        Chapitre(numero=2, titre="Deux", description="dDeux", sous_sections=[SousSection(numero="2.1", titre="S", description="r")]),
                    ],
                )
            ],
        ),
        "test-sujet",
    )
    state.sections[1].status = "done"
    state.sections[1].sources_total = 2
    state.sections[1].sources_ecartees = ["a#1 : x"]
    save_state(tmp_path, state)

    result = generator.improve_toc(make_cfg(), tmp_path, subject)

    kept = result.state.section_by_numero(2)
    assert kept.sources_total == 2 and kept.sources_ecartees == ["a#1 : x"]
