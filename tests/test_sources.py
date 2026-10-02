"""Documents de référence : découverte, découpe, extraction en unités, cache, consolidation."""

from __future__ import annotations

import json

import pytest

from manual_cli import sources
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.parsing import ParsingError
from manual_cli.sources import SourcesError


def make_cfg(max_chunk_chars=1000) -> AppConfig:
    spec = ModelSpec(key="m", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)
    return AppConfig(
        roles={"model_think": spec},
        settings={"sources": {"max_chunk_chars": max_chunk_chars}},
    )


def unit_json(enonce="E", extrait="alpha", type_="idee", utilite="haute", themes=("t",)) -> dict:
    return {"type": type_, "enonce": enonce, "extrait": extrait, "utilite": utilite, "themes": list(themes)}


class Scripted:
    """Client factice : répond selon le contenu du prompt, note les appels."""

    def __init__(self, handler):
        self.handler = handler
        self.prompts: list[str] = []

    def client_for(self, role):
        outer = self

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                outer.prompts.append(prompt)
                return "```json\n" + json.dumps(outer.handler(prompt, messages)) + "\n```"

        return _C()


def install(monkeypatch, handler) -> Scripted:
    scripted = Scripted(handler)
    monkeypatch.setattr(sources, "_client", lambda cfg, role: scripted.client_for(role))
    return scripted


def write_source(subject, name, text):
    path = subject.directory / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- découverte -----------------------------------------------------------------------


def test_list_source_files_is_empty_without_directory(subject):
    assert sources.list_source_files(subject.directory) == []


def test_list_source_files_finds_md_and_txt_recursively_and_ignores_others(subject):
    write_source(subject, "b.md", "x")
    write_source(subject, "a.txt", "x")
    write_source(subject, "sub/c.md", "x")
    write_source(subject, "image.png", "x")
    write_source(subject, ".cache.md", "x")

    assert sources.list_source_files(subject.directory) == ["a.txt", "b.md", "sub/c.md"]


# --- découpe --------------------------------------------------------------------------


def test_split_chunks_keeps_a_short_text_whole():
    assert sources.split_chunks("court", 100) == ["court"]


def test_split_chunks_cuts_on_headings_first():
    text = "# A\nun\n\n# B\ndeux\n\n# C\ntrois"
    chunks = sources.split_chunks(text, 14)

    assert chunks == ["# A\nun", "# B\ndeux", "# C\ntrois"]


def test_split_chunks_loses_nothing_even_on_a_giant_paragraph():
    text = "mot " * 200
    chunks = sources.split_chunks(text, 50)

    assert all(len(c) <= 50 for c in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_chunks_rejects_a_non_positive_limit():
    with pytest.raises(SourcesError):
        sources.split_chunks("x", 0)


# --- extraction -----------------------------------------------------------------------


def test_extract_file_builds_units_with_stable_ids_and_line_numbers(monkeypatch):
    text = "intro\n\nalpha est vrai\n\nbeta aussi"
    install(
        monkeypatch,
        lambda p, m: {"unites": [unit_json("A", "alpha est vrai"), unit_json("B", "beta aussi", type_="fait")]},
    )

    units = sources.extract_file(make_cfg(), "notes.md", text)

    assert [u.id for u in units] == ["notes.md#1", "notes.md#2"]
    assert [u.ligne for u in units] == [3, 5]
    assert units[1].type == "fait" and units[1].source == "notes.md"


def test_extract_file_matches_quotes_despite_whitespace_differences(monkeypatch):
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha   est\nvrai")]})

    units = sources.extract_file(make_cfg(), "n.md", "avant alpha est vrai après")

    assert len(units) == 1


def test_extract_file_asks_again_when_a_quote_is_not_in_the_source(monkeypatch):
    answers = iter([
        {"unites": [unit_json("A", "phrase inventée")]},
        {"unites": [unit_json("A", "alpha")]},
    ])
    scripted = install(monkeypatch, lambda p, m: next(answers))

    units = sources.extract_file(make_cfg(), "n.md", "alpha")

    assert units[0].extrait == "alpha"
    assert len(scripted.prompts) == 2


def test_extract_file_fails_when_quotes_are_never_faithful(monkeypatch):
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "inventé")]})

    with pytest.raises(ParsingError):
        sources.extract_file(make_cfg(), "n.md", "alpha")


def test_extract_file_rejects_an_unknown_unit_type(monkeypatch):
    install(monkeypatch, lambda p, m: {"unites": [unit_json(type_="roman")]})

    with pytest.raises(ParsingError):
        sources.extract_file(make_cfg(), "n.md", "alpha")


def test_extract_file_processes_each_chunk_and_numbers_units_continuously(monkeypatch):
    text = "# A\nalpha\n\n# B\nbeta"

    def handler(prompt, messages):
        return {"unites": [unit_json("x", "alpha" if "alpha" in prompt else "beta")]}

    scripted = install(monkeypatch, handler)

    units = sources.extract_file(make_cfg(max_chunk_chars=10), "n.md", text)

    assert [u.id for u in units] == ["n.md#1", "n.md#2"]
    assert [u.ligne for u in units] == [2, 5]
    assert len(scripted.prompts) == 2


def test_extract_file_gives_nothing_for_a_useless_text(monkeypatch):
    install(monkeypatch, lambda p, m: {"unites": []})

    assert sources.extract_file(make_cfg(), "n.md", "bla bla") == []


def test_extract_prompt_carries_the_file_name_and_text(monkeypatch):
    scripted = install(monkeypatch, lambda p, m: {"unites": []})

    sources.extract_file(make_cfg(), "biblio.md", "contenu unique")

    assert "biblio.md" in scripted.prompts[0] and "contenu unique" in scripted.prompts[0]


# --- index et cache -------------------------------------------------------------------


def test_refresh_index_extracts_new_files_and_writes_the_index(subject, tmp_path, monkeypatch):
    write_source(subject, "a.md", "alpha")
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha")]})
    out = tmp_path / "out"

    report = sources.refresh_index(make_cfg(), subject.directory, out)

    assert report.extracted == ["a.md"] and report.cached == [] and report.removed == []
    assert (out / "sources_index.json").is_file()
    assert [u.id for u in sources.load_index(out).units()] == ["a.md#1"]


def test_refresh_index_does_not_recall_the_model_for_unchanged_files(subject, tmp_path, monkeypatch):
    write_source(subject, "a.md", "alpha")
    scripted = install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha")]})
    out = tmp_path / "out"
    sources.refresh_index(make_cfg(), subject.directory, out)
    calls = len(scripted.prompts)

    report = sources.refresh_index(make_cfg(), subject.directory, out)

    assert report.cached == ["a.md"] and report.extracted == []
    assert len(scripted.prompts) == calls


def test_refresh_index_reextracts_a_modified_file(subject, tmp_path, monkeypatch):
    write_source(subject, "a.md", "alpha")
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha" if "alpha" in p else "gamma")]})
    out = tmp_path / "out"
    sources.refresh_index(make_cfg(), subject.directory, out)
    write_source(subject, "a.md", "gamma")

    report = sources.refresh_index(make_cfg(), subject.directory, out)

    assert report.extracted == ["a.md"]
    assert sources.load_index(out).units()[0].extrait == "gamma"


def test_refresh_index_drops_files_that_disappeared(subject, tmp_path, monkeypatch):
    path = write_source(subject, "a.md", "alpha")
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha")]})
    out = tmp_path / "out"
    sources.refresh_index(make_cfg(), subject.directory, out)
    path.unlink()

    report = sources.refresh_index(make_cfg(), subject.directory, out)

    assert report.removed == ["a.md"]
    assert sources.load_index(out).units() == []


def test_refresh_index_without_sources_writes_nothing(subject, tmp_path):
    out = tmp_path / "out"

    report = sources.refresh_index(make_cfg(), subject.directory, out)

    assert report.extracted == [] and not (out / "sources_index.json").exists()


def test_refresh_index_rejects_a_file_that_is_not_utf8(subject, tmp_path):
    path = subject.directory / "sources" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00")

    with pytest.raises(SourcesError, match="bad.md"):
        sources.refresh_index(make_cfg(), subject.directory, tmp_path / "out")


def test_load_index_is_empty_when_missing(tmp_path):
    assert sources.load_index(tmp_path).units() == []


def test_load_index_rejects_a_corrupt_file(tmp_path):
    (tmp_path / "sources_index.json").write_text("{pas du json", encoding="utf-8")

    with pytest.raises(SourcesError, match="sources_index.json"):
        sources.load_index(tmp_path)


# --- consolidation --------------------------------------------------------------------


def two_files(subject, monkeypatch):
    write_source(subject, "a.md", "alpha")
    write_source(subject, "b.md", "beta")

    def handler(prompt, messages):
        if "DOUBLONS" in prompt:
            return handler.consolidation
        return {"unites": [unit_json("A" if "alpha" in prompt else "B", "alpha" if "alpha" in prompt else "beta")]}

    handler.consolidation = {"fusions": [], "conflits": []}
    return install(monkeypatch, handler), handler


def test_consolidation_merges_duplicates_and_keeps_every_provenance(subject, tmp_path, monkeypatch):
    scripted, handler = two_files(subject, monkeypatch)
    handler.consolidation = {"fusions": [{"garde": "a.md#1", "doublons": ["b.md#1"]}], "conflits": []}
    out = tmp_path / "out"

    sources.refresh_index(make_cfg(), subject.directory, out)
    units = sources.load_index(out).units()

    assert [u.id for u in units] == ["a.md#1"]
    assert units[0].autres_sources == ["b.md"]


def test_consolidation_flags_conflicts_on_both_units(subject, tmp_path, monkeypatch):
    scripted, handler = two_files(subject, monkeypatch)
    handler.consolidation = {"fusions": [], "conflits": [["a.md#1", "b.md#1"]]}
    out = tmp_path / "out"

    sources.refresh_index(make_cfg(), subject.directory, out)
    by_id = {u.id: u for u in sources.load_index(out).units()}

    assert by_id["a.md#1"].conflit_avec == ["b.md#1"]
    assert by_id["b.md#1"].conflit_avec == ["a.md#1"]


def test_consolidation_rejects_unknown_ids(subject, tmp_path, monkeypatch):
    scripted, handler = two_files(subject, monkeypatch)
    handler.consolidation = {"fusions": [{"garde": "a.md#1", "doublons": ["z.md#9"]}], "conflits": []}

    with pytest.raises(ParsingError):
        sources.refresh_index(make_cfg(), subject.directory, tmp_path / "out")


def test_consolidation_is_not_redone_when_nothing_changed(subject, tmp_path, monkeypatch):
    scripted, handler = two_files(subject, monkeypatch)
    out = tmp_path / "out"
    sources.refresh_index(make_cfg(), subject.directory, out)
    calls = len(scripted.prompts)

    sources.refresh_index(make_cfg(), subject.directory, out)

    assert len(scripted.prompts) == calls


def test_consolidation_is_skipped_with_a_single_unit(subject, tmp_path, monkeypatch):
    write_source(subject, "a.md", "alpha")
    scripted = install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "alpha")]})

    sources.refresh_index(make_cfg(), subject.directory, tmp_path / "out")

    assert len(scripted.prompts) == 1


def test_useless_units_stay_in_the_index_but_are_not_active(subject, tmp_path, monkeypatch):
    write_source(subject, "a.md", "alpha beta")
    install(
        monkeypatch,
        lambda p, m: {"unites": [unit_json("A", "alpha", utilite="haute"), unit_json("B", "beta", utilite="nulle")]},
    )
    out = tmp_path / "out"
    sources.refresh_index(make_cfg(), subject.directory, out)
    index = sources.load_index(out)

    assert [u.id for u in index.units()] == ["a.md#1", "a.md#2"]
    assert [u.id for u in index.active_units()] == ["a.md#1"]


# --- client ---------------------------------------------------------------------------


def test_client_uses_the_think_role(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, spec, role=None):
            seen["role"] = role

    monkeypatch.setattr(sources, "OllamaCloudClient", FakeClient)

    sources._client(make_cfg(), "model_think")

    assert seen["role"] == "model_think"


# --- cas limites ----------------------------------------------------------------------


def test_split_chunks_ignores_blank_sections_and_paragraphs():
    text = "\n# A\nun\n\n\n\n# B\ndeux\n\n# C\ntrois"

    chunks = sources.split_chunks(text, 12)

    assert all(c.strip() for c in chunks) and "".join(chunks).count("un") >= 1


def test_split_chunks_cuts_a_long_section_by_paragraphs():
    text = "# T\n" + "\n\n".join(["alpha beta"] * 6)

    chunks = sources.split_chunks(text, 25)

    assert len(chunks) > 1 and all(len(c) <= 25 for c in chunks)


def test_find_rejects_an_empty_quote():
    assert sources._find("texte", "   ") is None


def test_extract_file_rejects_an_empty_quote(monkeypatch):
    install(monkeypatch, lambda p, m: {"unites": [unit_json("A", "  ")]})

    with pytest.raises(ParsingError):
        sources.extract_file(make_cfg(), "n.md", "alpha")


def test_consolidation_rejects_a_unit_that_is_its_own_duplicate(subject, tmp_path, monkeypatch):
    scripted, handler = two_files(subject, monkeypatch)
    handler.consolidation = {"fusions": [{"garde": "a.md#1", "doublons": ["a.md#1"]}], "conflits": []}

    with pytest.raises(ParsingError):
        sources.refresh_index(make_cfg(), subject.directory, tmp_path / "out")
