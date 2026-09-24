from __future__ import annotations

import pytest

from manual_cli import tracing
from manual_cli.subjects import Subject


@pytest.fixture(autouse=True)
def _reset_tracing():
    tracing.reset()
    yield
    tracing.reset()


@pytest.fixture
def subject(tmp_path) -> Subject:
    """Sujet minimal dont les prompts sont fournis par surcharge (textes reconnaissables)."""
    directory = tmp_path / "subjects" / "test-sujet"
    directory.mkdir(parents=True)
    (directory / "system_prompt.md").write_text("SYSTEM DU SUJET", encoding="utf-8")
    (directory / "toc_instruction.md").write_text("PLAN DU SUJET", encoding="utf-8")
    return Subject(
        titre="Sujet de test",
        langue="français",
        role="r",
        objectif="o",
        public="p",
        niveau="n",
        ton="t",
        plan_directeur="a → b",
        slug="test-sujet",
        directory=directory,
    )
