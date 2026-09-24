from __future__ import annotations

import pytest

from manual_cli import generator
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, load_state, save_state

TOC_JSON = (
    '```json\n'
    '{"titre_manuel": "M", "parties": [{"numero": "I", "titre": "Fondamentaux", '
    '"chapitres": [{"numero": 1, "titre": "Intro", "description": "d", '
    '"sous_sections": [{"numero": "1.1", "titre": "Def"}]}]}]}\n'
    '```'
)

REQUIREMENTS = {
    "generic": [
        {"id": "marqueur_fin", "description": "doit se terminer par le marqueur", "severity": "bloquant"},
    ],
    "parties": {},
}


def make_spec(key: str) -> ModelSpec:
    return ModelSpec(key=key, provider="ollama", name=f"{key}:cloud", base_url="http://x", api_key="k", timeout=30)


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        roles={
            "model_write": make_spec("writer"),
            "model_judge": make_spec("judge"),
            "model_think": make_spec("think"),
            "model_rewriter": make_spec("rewriter"),
        }
    )


class FakeClients:
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


def patch_clients(monkeypatch, fake: FakeClients) -> None:
    monkeypatch.setattr(generator, "_client", lambda cfg, role: fake.client_for(role))


def make_state():
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(numero=1, titre="Intro", description="d", sous_sections=[SousSection(numero="1.1", titre="Def")])
                ],
            )
        ],
    )
    return build_manual_state(toc)


def good_section_text(numero: int = 1) -> str:
    marker = generator.SECTION_END_TEMPLATE.format(numero=numero)
    return f"## {numero}. Intro\ncontenu complet\n{marker}"


def judge_accept_json() -> str:
    return '```json\n{"verdict": "accept", "issues": []}\n```'


def judge_revise_json() -> str:
    return (
        '```json\n{"verdict": "revise", "issues": '
        '[{"id": "marqueur_fin", "severity": "bloquant", "detail": "manquant"}]}\n```'
    )


# --- _client -----------------------------------------------------------------


def test_client_builds_ollama_cloud_client_from_role(cfg):
    client = generator._client(cfg, "model_write")

    assert isinstance(client, generator.OllamaCloudClient)
    assert client.spec is cfg.role("model_write")
    assert client.spec.key == "writer"
    assert client.role == "model_write"


# --- generate_toc ---------------------------------------------------------


def test_generate_toc_creates_state_and_files(tmp_path, cfg, monkeypatch):
    fake = FakeClients({"model_write": [TOC_JSON]})
    patch_clients(monkeypatch, fake)

    state = generator.generate_toc(cfg, tmp_path)

    assert state.titre_manuel == "M"
    assert [s.titre for s in state.sections] == ["Intro"]
    assert (tmp_path / "00_toc.md").exists()
    assert (tmp_path / "manifest.json").exists()
    from manual_cli.memory import INITIAL_DIGEST

    assert (tmp_path / "memory.md").read_text(encoding="utf-8") == INITIAL_DIGEST


def test_generate_toc_markdown_contains_chapter_and_subsection(tmp_path, cfg, monkeypatch):
    fake = FakeClients({"model_write": [TOC_JSON]})
    patch_clients(monkeypatch, fake)

    generator.generate_toc(cfg, tmp_path)

    toc_md = (tmp_path / "00_toc.md").read_text(encoding="utf-8")
    assert "1. Intro" in toc_md
    assert "1.1 Def" in toc_md


# --- _strip_end_marker -----------------------------------------------------


def test_strip_end_marker_present():
    marker = generator.SECTION_END_TEMPLATE.format(numero=3)
    text = f"## contenu\n\n{marker}"
    stripped, ok = generator._strip_end_marker(text, 3)
    assert ok is True
    assert stripped == "## contenu"


def test_strip_end_marker_wrong_number():
    text = f"## contenu\n\n{generator.SECTION_END_TEMPLATE.format(numero=3)}"
    stripped, ok = generator._strip_end_marker(text, 4)
    assert ok is False
    assert stripped == text


def test_strip_end_marker_missing():
    stripped, ok = generator._strip_end_marker("## contenu sans marqueur", 1)
    assert ok is False
    assert stripped == "## contenu sans marqueur"


# --- _judge_section ---------------------------------------------------------


def test_judge_section_overrides_accept_when_blocking_issue_listed(cfg, monkeypatch):
    fake = FakeClients(
        {
            "model_judge": [
                '```json\n{"verdict": "accept", "issues": '
                '[{"id": "marqueur_fin", "severity": "recommande", "detail": "oubli"}]}\n```'
            ]
        }
    )
    patch_clients(monkeypatch, fake)
    state = make_state()
    section = state.section_by_numero(1)

    verdict = generator._judge_section(cfg, section, "texte", REQUIREMENTS)

    assert verdict.verdict == "revise"


def test_judge_section_keeps_accept_when_only_recommande_issue_and_not_blocking(cfg, monkeypatch):
    fake = FakeClients(
        {
            "model_judge": [
                '```json\n{"verdict": "accept", "issues": '
                '[{"id": "checklist", "severity": "recommande", "detail": "un peu courte"}]}\n```'
            ]
        }
    )
    patch_clients(monkeypatch, fake)
    state = make_state()
    section = state.section_by_numero(1)

    verdict = generator._judge_section(cfg, section, "texte", REQUIREMENTS)

    assert verdict.verdict == "accept"


# --- write_section -----------------------------------------------------------


def test_write_section_accepts_on_first_try(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    text = good_section_text(1)

    fake = FakeClients(
        {
            "model_write": [text],
            "model_judge": [judge_accept_json()],
            "model_rewriter": [],
            "model_think": ["résumé mis à jour"],
        }
    )
    patch_clients(monkeypatch, fake)

    result = generator.write_section(cfg, tmp_path, state, section, REQUIREMENTS)

    assert result.status == "done"
    assert result.attempts == 1
    assert result.last_verdict == "accept"
    saved = (tmp_path / section.filename).read_text(encoding="utf-8")
    assert generator.SECTION_END_TEMPLATE.format(numero=1) not in saved
    assert (tmp_path / "memory.md").read_text(encoding="utf-8") == "résumé mis à jour"


def test_write_section_rewrites_once_then_accepts(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    bad_text = "## 1. Intro\nsans marqueur"
    good_text = good_section_text(1)

    fake = FakeClients(
        {
            "model_write": [bad_text],
            "model_judge": [judge_revise_json(), judge_accept_json()],
            "model_rewriter": [good_text],
            "model_think": ["ok"],
        }
    )
    patch_clients(monkeypatch, fake)

    result = generator.write_section(cfg, tmp_path, state, section, REQUIREMENTS, max_rewrite=2)

    assert result.status == "done"
    assert result.attempts == 2
    assert len(fake.calls["model_rewriter"]) == 1


def test_write_section_marks_failed_after_exhausting_rewrites(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    bad_text = "## 1. Intro\nsans marqueur"

    fake = FakeClients(
        {
            "model_write": [bad_text],
            "model_judge": [judge_revise_json(), judge_revise_json(), judge_revise_json()],
            "model_rewriter": [bad_text, bad_text],
            "model_think": ["ok"],
        }
    )
    patch_clients(monkeypatch, fake)

    result = generator.write_section(cfg, tmp_path, state, section, REQUIREMENTS, max_rewrite=2)

    assert result.status == "failed"
    assert result.attempts == 3
    assert len(fake.calls["model_rewriter"]) == 2


def test_write_section_fails_if_marker_missing_even_when_judge_accepts(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    text_without_marker = "## 1. Intro\ncontenu sans marqueur"

    fake = FakeClients(
        {
            "model_write": [text_without_marker],
            "model_judge": [judge_accept_json()],
            "model_rewriter": [],
            "model_think": ["ok"],
        }
    )
    patch_clients(monkeypatch, fake)

    result = generator.write_section(cfg, tmp_path, state, section, REQUIREMENTS)

    assert result.status == "failed"
    assert "marqueur de fin manquant" in result.last_verdict


# --- run_write ---------------------------------------------------------------


def test_run_write_raises_without_manifest(tmp_path, cfg):
    with pytest.raises(generator.GeneratorError):
        generator.run_write(cfg, tmp_path)


def test_run_write_only_processes_pending_sections(tmp_path, cfg, monkeypatch):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(numero=1, titre="Un", description="d", sous_sections=[]),
                    Chapitre(numero=2, titre="Deux", description="d", sous_sections=[]),
                ],
            )
        ],
    )
    state = build_manual_state(toc)
    state.sections[0].status = "done"
    save_state(tmp_path, state)

    monkeypatch.setattr(generator, "load_requirements", lambda: REQUIREMENTS)

    text2 = good_section_text(2)
    fake = FakeClients(
        {
            "model_write": [text2],
            "model_judge": [judge_accept_json()],
            "model_rewriter": [],
            "model_think": ["ok"],
        }
    )
    patch_clients(monkeypatch, fake)

    results = generator.run_write(cfg, tmp_path)

    assert [s.numero for s in results] == [2]


def test_run_write_with_only_numeros_single(tmp_path, cfg, monkeypatch):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(numero=1, titre="Un", description="d", sous_sections=[]),
                    Chapitre(numero=2, titre="Deux", description="d", sous_sections=[]),
                ],
            )
        ],
    )
    state = build_manual_state(toc)
    save_state(tmp_path, state)
    monkeypatch.setattr(generator, "load_requirements", lambda: REQUIREMENTS)

    text1 = good_section_text(1)
    fake = FakeClients(
        {
            "model_write": [text1],
            "model_judge": [judge_accept_json()],
            "model_rewriter": [],
            "model_think": ["ok"],
        }
    )
    patch_clients(monkeypatch, fake)

    results = generator.run_write(cfg, tmp_path, only_numeros=[1])

    assert [s.numero for s in results] == [1]


def test_run_write_returns_empty_list_when_nothing_pending(tmp_path, cfg, monkeypatch):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[Chapitre(numero=1, titre="Un", description="d", sous_sections=[])],
            )
        ],
    )
    state = build_manual_state(toc)
    state.sections[0].status = "done"
    save_state(tmp_path, state)
    monkeypatch.setattr(generator, "load_requirements", lambda: REQUIREMENTS)

    results = generator.run_write(cfg, tmp_path)

    assert results == []


def test_run_write_processes_multiple_sections_in_parallel_with_correct_routing(tmp_path, cfg, monkeypatch):
    import re
    import threading

    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(numero=n, titre=f"Chap{n}", description="d", sous_sections=[]) for n in range(1, 5)
                ],
            )
        ],
    )
    state = build_manual_state(toc)
    save_state(tmp_path, state)
    monkeypatch.setattr(generator, "load_requirements", lambda: REQUIREMENTS)

    call_lock = threading.Lock()
    write_calls: list[str] = []

    def write_handler(messages: list[dict]) -> str:
        content = messages[-1]["content"]
        numero = int(re.search(r"Numéro : (\d+)", content).group(1))
        with call_lock:
            write_calls.append(f"write-{numero}")
        return good_section_text(numero)

    def judge_handler(messages: list[dict]) -> str:
        return judge_accept_json()

    def think_handler(messages: list[dict]) -> str:
        content = messages[0]["content"]
        current = re.search(r"## Résumé actuel\n(.*?)\n\n## Section", content, re.DOTALL).group(1).strip()
        numero = int(re.search(r"## (\d+)\. ", content).group(1))
        return (current + f" S{numero}").strip()

    class RoutingFakeClients:
        def __init__(self):
            self.lock = threading.Lock()

        def client_for(self, role: str):
            handler = {"model_write": write_handler, "model_judge": judge_handler, "model_think": think_handler}[role]

            class _C:
                def chat(_self, messages: list[dict]) -> str:
                    return handler(messages)

            return _C()

    fake = RoutingFakeClients()
    monkeypatch.setattr(generator, "_client", lambda cfg, role: fake.client_for(role))

    results = generator.run_write(cfg, tmp_path, workers=4)

    assert [s.numero for s in results] == [1, 2, 3, 4]
    assert all(s.status == "done" for s in results)
    assert sorted(write_calls) == ["write-1", "write-2", "write-3", "write-4"]

    final_state = load_state(tmp_path)
    assert [s.status for s in final_state.sections] == ["done", "done", "done", "done"]

    final_digest = (tmp_path / "memory.md").read_text(encoding="utf-8")
    for numero in range(1, 5):
        assert f"S{numero}" in final_digest, f"mise à jour mémoire perdue pour la section {numero}"
