from __future__ import annotations

import json

import pytest
import yaml

from manual_cli import generator
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.parsing import ParsingError
from manual_cli.state import load_state, save_state
from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state


def spec(key: str) -> ModelSpec:
    return ModelSpec(key=key, provider="ollama", name=key, base_url="http://x", api_key="k", timeout=1)


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(roles={"model_write": spec("model_write")})


def chapter(numero, titre, subs=None):
    subs = subs if subs is not None else [f"{numero}.1 Def"]
    return {
        "numero": numero,
        "titre": titre,
        "description": f"desc {titre}",
        "sous_sections": [
            {"numero": s.split(" ")[0], "titre": s.split(" ", 1)[1], "description": f"résumé de {s}"} for s in subs
        ],
    }


def toc_payload(parties=None):
    parties = parties or [
        ("I", "Bases", [chapter(1, "Un"), chapter(2, "Deux")]),
        ("II", "Avancé", [chapter(3, "Trois"), chapter(4, "Quatre")]),
    ]
    return {
        "titre_manuel": "Manuel",
        "parties": [{"numero": n, "titre": t, "chapitres": cs} for n, t, cs in parties],
    }


def as_json(payload) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class Fake:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.fixture
def fake(monkeypatch):
    def install(*replies: str) -> Fake:
        client = Fake(*replies)
        monkeypatch.setattr(generator, "_client", lambda cfg, role: client)
        return client

    return install


@pytest.fixture
def workdir(tmp_path):
    """Manuel de 4 chapitres : 1 et 2 rédigés (figés), 3 en échec, 4 en attente."""
    toc = TocSchema.model_validate(toc_payload())
    state = build_manual_state(toc, subject="test-sujet")
    for s, status in zip(state.sections, ["done", "done", "failed", "pending"]):
        s.status = status
        s.attempts = 2 if status != "pending" else 0
        s.last_verdict = "accept" if status == "done" else ("revise" if status == "failed" else None)
    out = tmp_path / "out"
    out.mkdir()
    save_state(out, state)
    generator._write_toc_markdown(out, state)
    for s in state.sections[:3]:
        (out / s.filename).write_text(f"## {s.numero}. {s.titre}\ncontenu\n", encoding="utf-8")
    (out / "memory.md").write_text("mémoire", encoding="utf-8")
    return out


def run(cfg, workdir, subject, **kwargs):
    return generator.improve_toc(cfg, workdir, subject, **kwargs)


# --- amorce et prompts -----------------------------------------------------------------


def test_improve_toc_sends_current_toc_locked_chapters_and_default_instruction(cfg, workdir, subject, fake):
    client = fake(as_json(toc_payload()))

    run(cfg, workdir, subject)

    messages = client.calls[0]
    assert messages[0] == {"role": "system", "content": "SYSTEM DU SUJET"}
    prompt = messages[1]["content"]
    assert '"titre": "Quatre"' in prompt
    assert "Relis" in prompt
    assert "figé" in prompt.lower()
    frozen = prompt.split("## Chapitres figés")[1].split("\n## ")[0]
    assert "Chapitre 1 « Un »" in frozen and "Chapitre 2 « Deux »" in frozen
    assert "Chapitre 3" not in frozen and "Chapitre 4" not in frozen
    assert "$" not in prompt


def test_improve_toc_asks_for_a_description_on_every_sous_section(cfg, workdir, subject):
    prompt = generator._read_prompt("toc_improve_instruction.md")

    assert "description" in prompt.split("## Format de sortie")[1]
    assert "sous-section" in prompt.split("## Format de sortie")[1]


def test_improve_toc_asks_again_when_a_sous_section_has_no_description(cfg, workdir, subject, fake):
    incomplete = toc_payload()
    del incomplete["parties"][1]["chapitres"][1]["sous_sections"][0]["description"]
    client = fake(as_json(incomplete), as_json(toc_payload()))

    result = run(cfg, workdir, subject)

    assert len(client.calls) == 2
    assert "4.1 Def" in client.calls[1][-1]["content"]
    assert result.modified is False


def test_improve_toc_uses_custom_instruction_instead_of_default(cfg, workdir, subject, fake):
    client = fake(as_json(toc_payload()))
    default = generator._read_prompt("toc_improve_default_instruction.md").strip()

    run(cfg, workdir, subject, instruction="Ajoute un chapitre sur l'évaluation.")

    prompt = client.calls[0][1]["content"]
    assert "Ajoute un chapitre sur l'évaluation." in prompt
    assert default not in prompt


def test_improve_toc_blank_instruction_uses_default(cfg, workdir, subject, fake):
    client = fake(as_json(toc_payload()))
    default = generator._read_prompt("toc_improve_default_instruction.md").strip()

    run(cfg, workdir, subject, instruction="  ")

    assert default in client.calls[0][1]["content"]


# --- préservation ------------------------------------------------------------------------


def improved_payload():
    return toc_payload(
        [
            ("I", "Bases", [chapter(1, "Un"), chapter(2, "Deux")]),
            ("II", "Avancé", [chapter(3, "Trois, revu", ["3.1 Nouveau", "3.2 Autre"]), chapter(4, "Quatre"), chapter(5, "Cinq")]),
        ]
    )


def test_new_descriptions_on_written_chapters_do_not_send_them_back_to_pending(cfg, workdir, subject, fake):
    """Seuls le numéro et le titre des sous-sections sont figés : la description peut être enrichie."""
    payload = toc_payload()
    payload["parties"][0]["chapitres"][0]["sous_sections"][0]["description"] = "une description enrichie"
    fake(as_json(payload))

    result = run(cfg, workdir, subject)

    state = load_state(workdir)
    assert result.modified is True
    assert result.changed == []
    assert [s.status for s in state.sections[:2]] == ["done", "done"]
    assert state.sections[0].sous_sections[0].description == "une description enrichie"
    assert "  *une description enrichie*" in (workdir / "00_toc.md").read_text(encoding="utf-8")


def test_a_written_chapter_may_gain_descriptions_when_its_manifest_had_none(cfg, workdir, subject, fake):
    state = load_state(workdir)
    for section in state.sections:
        for sous_section in section.sous_sections:
            sous_section.description = ""
    for partie in state.toc.parties:
        for chapitre in partie.chapitres:
            for sous_section in chapitre.sous_sections:
                sous_section.description = ""
    save_state(workdir, state)
    fake(as_json(toc_payload()))

    run(cfg, workdir, subject)

    state = load_state(workdir)
    assert [s.status for s in state.sections[:2]] == ["done", "done"]
    assert state.sections[0].sous_sections[0].description == "résumé de 1.1 Def"


def test_unchanged_chapters_keep_their_progress_and_changed_ones_restart(cfg, workdir, subject, fake):
    fake(as_json(improved_payload()))

    result = run(cfg, workdir, subject)

    state = load_state(workdir)
    by_num = {s.numero: s for s in state.sections}
    assert (by_num[1].status, by_num[1].attempts, by_num[1].last_verdict) == ("done", 2, "accept")
    assert by_num[2].status == "done"
    assert by_num[3].status == "pending" and by_num[3].titre == "Trois, revu"
    assert by_num[4].status == "pending"
    assert by_num[5].status == "pending"
    assert state.subject == "test-sujet"
    assert [s.numero for s in result.changed] == [3, 5]
    assert [s.numero for s in result.removed] == [3]
    assert result.modified is True


def test_improve_toc_rewrites_manifest_and_readable_toc(cfg, workdir, subject, fake):
    fake(as_json(improved_payload()))

    run(cfg, workdir, subject)

    assert "5. Cinq" in (workdir / "00_toc.md").read_text(encoding="utf-8")
    assert len(load_state(workdir).sections) == 5


def test_written_chapter_files_and_memory_are_never_touched(cfg, workdir, subject, fake):
    before = {p.name: p.read_text(encoding="utf-8") for p in workdir.glob("0*.md") if p.name != "00_toc.md"}
    fake(as_json(improved_payload()))

    result = run(cfg, workdir, subject)

    after = {p.name: p.read_text(encoding="utf-8") for p in workdir.glob("0*.md") if p.name != "00_toc.md"}
    assert after == before
    assert (workdir / "memory.md").read_text(encoding="utf-8") == "mémoire"
    assert result.orphan_files == ["03_trois.md"]


def test_previous_version_is_archived_in_toc_history(cfg, workdir, subject, fake):
    old_manifest = (workdir / "manifest.json").read_text(encoding="utf-8")
    old_toc = (workdir / "00_toc.md").read_text(encoding="utf-8")
    fake(as_json(improved_payload()), as_json(toc_payload([("I", "Bases", [chapter(1, "Un"), chapter(2, "Deux")]), ("II", "Avancé", [chapter(3, "Trois"), chapter(4, "Quatre"), chapter(5, "Six")])])))

    first = run(cfg, workdir, subject)
    second = run(cfg, workdir, subject)

    assert (first.history_dir / "manifest.json").read_text(encoding="utf-8") == old_manifest
    assert (first.history_dir / "00_toc.md").read_text(encoding="utf-8") == old_toc
    assert second.history_dir != first.history_dir
    assert first.history_dir.parent == workdir / "toc_history"
    assert len(list((workdir / "toc_history").iterdir())) == 2


def test_identical_toc_changes_nothing(cfg, workdir, subject, fake):
    manifest = (workdir / "manifest.json").read_text(encoding="utf-8")
    fake(as_json(toc_payload()))

    result = run(cfg, workdir, subject)

    assert result.modified is False
    assert result.history_dir is None
    assert (workdir / "manifest.json").read_text(encoding="utf-8") == manifest
    assert not (workdir / "toc_history").exists()


def test_orphan_criteria_keys_are_reported_when_a_part_is_renamed(cfg, workdir, subject, fake):
    (subject.directory / "requirements.yml").write_text(
        yaml.safe_dump({"parties": {"Bases": [{"id": "c1", "description": "d", "severity": "recommande"}]}}),
        encoding="utf-8",
    )
    payload = toc_payload([("I", "Fondations", [chapter(1, "Un"), chapter(2, "Deux")]), ("II", "Avancé", [chapter(3, "Trois"), chapter(4, "Quatre")])])
    fake(as_json(payload))

    result = run(cfg, workdir, subject)

    assert result.orphan_criteria == ["Bases"]


# --- garde-fous ---------------------------------------------------------------------------


def test_model_must_keep_written_chapters_and_is_asked_again_otherwise(cfg, workdir, subject, fake):
    broken = toc_payload([("I", "Bases", [chapter(1, "Un renommé"), chapter(2, "Deux")]), ("II", "Avancé", [chapter(3, "Trois"), chapter(4, "Quatre")])])
    client = fake(as_json(broken), as_json(improved_payload()))

    run(cfg, workdir, subject)

    assert len(client.calls) == 2
    retry = client.calls[1][-1]["content"]
    assert "chapitre 1" in retry.lower()
    assert load_state(workdir).sections[0].titre == "Un"


def test_model_may_not_change_the_subsections_of_a_written_chapter(cfg, workdir, subject, fake):
    broken = toc_payload([("I", "Bases", [chapter(1, "Un", ["1.1 Autre"]), chapter(2, "Deux")]), ("II", "Avancé", [chapter(3, "Trois"), chapter(4, "Quatre")])])
    fake(as_json(broken), as_json(broken), as_json(broken))
    manifest = (workdir / "manifest.json").read_text(encoding="utf-8")

    with pytest.raises(ParsingError, match="chapitre 1"):
        run(cfg, workdir, subject)

    assert (workdir / "manifest.json").read_text(encoding="utf-8") == manifest
    assert not (workdir / "toc_history").exists()


def test_missing_written_chapter_is_rejected(cfg, workdir, subject, fake):
    broken = toc_payload([("I", "Bases", [chapter(1, "Un")])])
    fake(as_json(broken), as_json(broken), as_json(broken))

    with pytest.raises(ParsingError, match="chapitre 2"):
        run(cfg, workdir, subject)


def test_chapter_numbers_must_be_consecutive_from_one(cfg, workdir, subject, fake):
    bad = toc_payload([("I", "Bases", [chapter(1, "Un"), chapter(2, "Deux")]), ("II", "Avancé", [chapter(4, "Trois"), chapter(5, "Quatre")])])
    fake(as_json(bad), as_json(bad), as_json(bad))

    with pytest.raises(ParsingError, match="consécutifs"):
        run(cfg, workdir, subject)


def test_nothing_is_locked_before_any_chapter_is_written(cfg, tmp_path, subject, fake):
    toc = TocSchema.model_validate(toc_payload())
    out = tmp_path / "fresh"
    out.mkdir()
    save_state(out, build_manual_state(toc, subject="test-sujet"))
    client = fake(as_json(toc_payload([("I", "Tout", [chapter(1, "Alpha"), chapter(2, "Beta")])])))

    result = run(cfg, out, subject)

    assert "aucun" in client.calls[0][1]["content"].lower()
    assert [s.titre for s in load_state(out).sections] == ["Alpha", "Beta"]
    assert result.modified is True


def test_improve_toc_requires_a_manifest(cfg, tmp_path, subject):
    with pytest.raises(generator.GeneratorError, match="manual init"):
        run(cfg, tmp_path, subject)


def test_improve_toc_refuses_a_manifest_of_another_subject(cfg, workdir, subject):
    save_state(workdir, load_state(workdir).model_copy(update={"subject": "autre"}))

    with pytest.raises(generator.GeneratorError, match="autre"):
        run(cfg, workdir, subject)


def test_improve_toc_accepts_a_legacy_manifest_without_subject(cfg, workdir, subject, fake):
    save_state(workdir, load_state(workdir).model_copy(update={"subject": None}))
    fake(as_json(toc_payload()))

    assert run(cfg, workdir, subject).modified is False
