from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from manual_cli.requirements_loader import (
    DEFAULT_REQUIREMENTS_PATH,
    RequirementsError,
    blocking_ids,
    criteria_for_partie,
    load_requirements,
    render_criteria,
)

REQ_YAML = textwrap.dedent(
    """
    generic:
      - id: crit_a
        description: "Critère A"
        severity: bloquant
      - id: crit_b
        description: "Critère B"
        severity: recommande
    parties:
      "Partie I":
        - id: crit_c
          description: "Critère C"
          severity: bloquant
    """
)


@pytest.fixture
def req_file(tmp_path: Path) -> Path:
    p = tmp_path / "requirements.yml"
    p.write_text(REQ_YAML, encoding="utf-8")
    return p


def test_load_requirements_success(req_file):
    data = load_requirements(req_file)
    assert len(data["generic"]) == 2


def test_load_requirements_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_requirements(tmp_path / "does-not-exist.yml")


def test_load_requirements_invalid_content(tmp_path):
    p = tmp_path / "bad.yml"
    p.write_text("foo: bar\n", encoding="utf-8")
    with pytest.raises(RequirementsError):
        load_requirements(p)


def test_load_requirements_empty_file(tmp_path):
    p = tmp_path / "empty.yml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(RequirementsError):
        load_requirements(p)


def test_criteria_for_partie_merges_generic_and_specific(req_file):
    data = load_requirements(req_file)
    criteria = criteria_for_partie(data, "Partie I")
    ids = {c["id"] for c in criteria}
    assert ids == {"crit_a", "crit_b", "crit_c"}


def test_criteria_for_partie_unknown_partie_returns_generic_only(req_file):
    data = load_requirements(req_file)
    criteria = criteria_for_partie(data, "Partie inconnue")
    ids = {c["id"] for c in criteria}
    assert ids == {"crit_a", "crit_b"}


def test_blocking_ids(req_file):
    data = load_requirements(req_file)
    criteria = criteria_for_partie(data, "Partie I")
    assert blocking_ids(criteria) == {"crit_a", "crit_c"}


def test_render_criteria_format():
    text = render_criteria([{"id": "x", "severity": "bloquant", "description": "desc"}])
    assert text == "- [bloquant] `x` : desc"


def test_render_criteria_multiple_lines():
    text = render_criteria(
        [
            {"id": "a", "severity": "bloquant", "description": "d1"},
            {"id": "b", "severity": "recommande", "description": "d2"},
        ]
    )
    assert text.splitlines() == ["- [bloquant] `a` : d1", "- [recommande] `b` : d2"]


def test_real_requirements_file_loads():
    data = load_requirements(DEFAULT_REQUIREMENTS_PATH)
    assert "generic" in data
    assert len(data["generic"]) > 0
