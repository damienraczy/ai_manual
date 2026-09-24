from __future__ import annotations

import threading

import pytest

from manual_cli import generator
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, load_state, save_state

OLD_TEXT = "## 1. Intro\nancien contenu\n"
MARKER = generator.SECTION_END_TEMPLATE.format(numero=1)
NEW_TEXT = f"## 1. Intro\nnouveau contenu enrichi\n{MARKER}"
ACCEPT = '```json\n{"verdict": "accept", "issues": []}\n```'
REVISE = '```json\n{"verdict": "revise", "issues": [{"id": "marqueur_fin", "severity": "bloquant", "detail": "manque"}]}\n```'
REQUIREMENTS = {
    "generic": [{"id": "marqueur_fin", "description": "marqueur", "severity": "bloquant"}],
    "parties": {},
}


def spec(key: str) -> ModelSpec:
    return ModelSpec(key=key, provider="ollama", name=key, base_url="http://x", api_key="k", timeout=1)


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(roles={r: spec(r) for r in ("model_write", "model_judge", "model_think", "model_rewriter")})


class Fake:
    def __init__(self, handlers: dict[str, list[str]]):
        self.handlers = handlers
        self.calls: dict[str, list[list[dict]]] = {role: [] for role in handlers}

    def client_for(self, role: str):
        outer = self

        class _C:
            def chat(self, messages: list[dict]) -> str:
                outer.calls[role].append(messages)
                return outer.handlers[role].pop(0)

        return _C()


def install(monkeypatch, fake: Fake) -> Fake:
    monkeypatch.setattr(generator, "_client", lambda cfg, role: fake.client_for(role))
    return fake


def one_chapter_state(status: str = "done"):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Bases",
                chapitres=[
                    Chapitre(numero=1, titre="Intro", description="desc", sous_sections=[SousSection(numero="1.1", titre="Def")])
                ],
            )
        ],
    )
    state = build_manual_state(toc, subject="test-sujet")
    state.sections[0].status = status
    return state


@pytest.fixture
def workdir(tmp_path):
    """Répertoire de sortie avec un chapitre 1 déjà écrit."""
    state = one_chapter_state()
    save_state(tmp_path, state)
    (tmp_path / state.sections[0].filename).write_text(OLD_TEXT, encoding="utf-8")
    (tmp_path / "memory.md").write_text("mémoire initiale", encoding="utf-8")
    return tmp_path


def improve(cfg, workdir, **kwargs):
    state = load_state(workdir)
    return generator.improve_section(
        cfg, workdir, state, state.sections[0], REQUIREMENTS, system_prompt="SYS", **kwargs
    )


# --- improve_section : chemin nominal --------------------------------------------


def test_improve_seeds_the_draft_with_existing_text_and_default_instruction(cfg, workdir, monkeypatch):
    fake = install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["ok"]}))

    improve(cfg, workdir)

    messages = fake.calls["model_write"][0]
    assert messages[0] == {"role": "system", "content": "SYS"}
    prompt = messages[1]["content"]
    assert "ancien contenu" in prompt
    assert "Intro" in prompt and "1.1 Def" in prompt
    assert "mémoire initiale" in prompt
    assert "Relis" in prompt
    assert MARKER in prompt
    assert "$" not in prompt


def test_improve_uses_the_custom_instruction_instead_of_the_default(cfg, workdir, monkeypatch):
    fake = install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["ok"]}))
    default = generator._read_prompt("improve_default_instruction.md").strip()

    improve(cfg, workdir, instruction="Ajoute des chiffres.")

    prompt = fake.calls["model_write"][0][1]["content"]
    assert "Ajoute des chiffres." in prompt
    assert default not in prompt


def test_improve_blank_instruction_falls_back_to_the_default(cfg, workdir, monkeypatch):
    fake = install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["ok"]}))
    default = generator._read_prompt("improve_default_instruction.md").strip()

    improve(cfg, workdir, instruction="   ")

    assert default in fake.calls["model_write"][0][1]["content"]


def test_improve_replaces_the_file_keeps_a_backup_and_updates_state_and_memory(cfg, workdir, monkeypatch):
    fake = install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["mémoire enrichie"]}))
    filename = load_state(workdir).sections[0].filename

    result = improve(cfg, workdir)

    assert result.accepted is True
    assert result.path == workdir / filename
    assert result.backup == workdir / (filename + ".bak")
    assert (workdir / filename).read_text(encoding="utf-8") == "## 1. Intro\nnouveau contenu enrichi\n"
    assert (workdir / (filename + ".bak")).read_text(encoding="utf-8") == OLD_TEXT
    section = load_state(workdir).sections[0]
    assert section.status == "done" and section.attempts == 1
    assert (workdir / "memory.md").read_text(encoding="utf-8") == "mémoire enrichie"
    assert len(fake.calls["model_think"]) == 1


def test_improve_goes_through_the_rewrite_loop_like_a_normal_generation(cfg, workdir, monkeypatch):
    fake = install(
        monkeypatch,
        Fake({"model_write": ["## 1. Intro\nsans marqueur"], "model_judge": [REVISE, ACCEPT], "model_rewriter": [NEW_TEXT], "model_think": ["ok"]}),
    )

    result = improve(cfg, workdir)

    assert result.accepted is True
    assert len(fake.calls["model_rewriter"]) == 1
    assert load_state(workdir).sections[0].attempts == 2


def test_improve_can_rescue_a_failed_section_that_has_content(cfg, tmp_path, monkeypatch):
    state = one_chapter_state(status="failed")
    save_state(tmp_path, state)
    (tmp_path / state.sections[0].filename).write_text(OLD_TEXT, encoding="utf-8")
    (tmp_path / "memory.md").write_text("m", encoding="utf-8")
    install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["ok"]}))

    improve(cfg, tmp_path)

    assert load_state(tmp_path).sections[0].status == "done"


# --- improve_section : échec de l'amélioration --------------------------------------


def test_improve_that_is_not_accepted_keeps_the_original_and_saves_a_candidate(cfg, workdir, monkeypatch):
    fake = install(
        monkeypatch,
        Fake({"model_write": [NEW_TEXT], "model_judge": [REVISE, REVISE, REVISE], "model_rewriter": [NEW_TEXT, NEW_TEXT], "model_think": []}),
    )
    state_before = (workdir / "manifest.json").read_text(encoding="utf-8")
    filename = load_state(workdir).sections[0].filename

    result = improve(cfg, workdir, max_rewrite=2)

    assert result.accepted is False
    assert result.path == workdir / filename.replace(".md", ".candidate.md")
    assert result.backup is None
    assert (workdir / filename).read_text(encoding="utf-8") == OLD_TEXT
    assert result.path.read_text(encoding="utf-8") == "## 1. Intro\nnouveau contenu enrichi\n"
    assert (workdir / "manifest.json").read_text(encoding="utf-8") == state_before
    assert (workdir / "memory.md").read_text(encoding="utf-8") == "mémoire initiale"
    assert fake.calls["model_think"] == []


def test_improve_without_end_marker_is_not_accepted_even_if_judge_accepts(cfg, workdir, monkeypatch):
    install(monkeypatch, Fake({"model_write": ["## 1. Intro\nsans marqueur"], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": []}))

    result = improve(cfg, workdir)

    assert result.accepted is False


def test_improve_requires_existing_content(cfg, tmp_path, monkeypatch):
    save_state(tmp_path, one_chapter_state(status="pending"))
    (tmp_path / "memory.md").write_text("m", encoding="utf-8")
    fake = install(monkeypatch, Fake({"model_write": []}))
    state = load_state(tmp_path)

    with pytest.raises(generator.GeneratorError, match="manual write"):
        generator.improve_section(cfg, tmp_path, state, state.sections[0], REQUIREMENTS, system_prompt="SYS")

    assert fake.calls["model_write"] == []


# --- run_improve -------------------------------------------------------------------


def test_run_improve_requires_a_manifest(cfg, tmp_path, subject):
    with pytest.raises(generator.GeneratorError, match="manual init"):
        generator.run_improve(cfg, tmp_path, subject, [1])


def test_run_improve_refuses_a_manifest_of_another_subject(cfg, workdir, subject):
    save_state(workdir, one_chapter_state().model_copy(update={"subject": "autre"}))

    with pytest.raises(generator.GeneratorError, match="autre"):
        generator.run_improve(cfg, workdir, subject, [1])


def test_run_improve_rejects_unknown_section_numbers(cfg, workdir, subject):
    with pytest.raises(KeyError):
        generator.run_improve(cfg, workdir, subject, [9])


def test_run_improve_lists_sections_without_content_before_any_llm_call(cfg, tmp_path, subject, monkeypatch):
    save_state(tmp_path, one_chapter_state(status="pending"))
    fake = install(monkeypatch, Fake({"model_write": []}))

    with pytest.raises(generator.GeneratorError, match="1"):
        generator.run_improve(cfg, tmp_path, subject, [1])

    assert fake.calls["model_write"] == []


def test_run_improve_uses_the_subject_prompt_and_forwards_the_instruction(cfg, workdir, subject, monkeypatch):
    fake = install(monkeypatch, Fake({"model_write": [NEW_TEXT], "model_judge": [ACCEPT], "model_rewriter": [], "model_think": ["ok"]}))

    results = generator.run_improve(cfg, workdir, subject, [1], instruction="Plus concret.")

    assert [r.accepted for r in results] == [True]
    assert fake.calls["model_write"][0][0] == {"role": "system", "content": "SYSTEM DU SUJET"}
    assert "Plus concret." in fake.calls["model_write"][0][1]["content"]


def test_run_improve_processes_several_sections_in_parallel(cfg, tmp_path, subject, monkeypatch):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Bases",
                chapitres=[Chapitre(numero=n, titre=f"Ch{n}", description="d", sous_sections=[]) for n in (1, 2, 3)],
            )
        ],
    )
    state = build_manual_state(toc, subject="test-sujet")
    for s in state.sections:
        s.status = "done"
        (tmp_path / s.filename).write_text(f"## {s.numero}. {s.titre}\nancien {s.numero}\n", encoding="utf-8")
    save_state(tmp_path, state)
    (tmp_path / "memory.md").write_text("m", encoding="utf-8")
    lock = threading.Lock()

    class Router:
        def client_for(self, role):
            class _C:
                def chat(self, messages):
                    content = messages[-1]["content"]
                    if role == "model_write":
                        numero = next(n for n in (1, 2, 3) if f"ancien {n}" in content)
                        return f"## {numero}. Ch{numero}\namélioré {numero}\n" + generator.SECTION_END_TEMPLATE.format(numero=numero)
                    if role == "model_judge":
                        return ACCEPT
                    with lock:
                        return "ok"

            return _C()

    router = Router()
    monkeypatch.setattr(generator, "_client", lambda cfg, role: router.client_for(role))

    results = generator.run_improve(cfg, tmp_path, subject, [1, 2, 3], workers=3)

    assert [r.section.numero for r in results] == [1, 2, 3]
    assert all(r.accepted for r in results)
    for s in load_state(tmp_path).sections:
        assert f"amélioré {s.numero}" in (tmp_path / s.filename).read_text(encoding="utf-8")
