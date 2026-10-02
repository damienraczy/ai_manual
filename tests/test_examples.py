"""Le dossier d'exemple guidé (Prompt Engineering) doit rester utilisable tel quel."""

from __future__ import annotations

from pathlib import Path

from manual_cli.subjects import load_subject

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "prompt-engineering"


def test_example_subject_is_a_valid_subject():
    subject = load_subject("prompt-engineering", EXAMPLE / "subjects")

    assert "Prompt Engineering" in subject.system_prompt()
    ids = [c["id"] for c in subject.requirements()["generic"]]
    assert "exemples_prompts" in ids and "multi_modeles" in ids
    assert "definition_claire" in ids  # critères communs conservés


def test_example_support_files_exist_and_are_not_empty():
    for name in ("README.md", "descriptif.txt", "consigne-improve-toc.txt", "consigne-improve.txt"):
        assert (EXAMPLE / name).read_text(encoding="utf-8").strip(), name
