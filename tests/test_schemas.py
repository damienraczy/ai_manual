from __future__ import annotations

import pytest
from pydantic import ValidationError

from manual_cli.schemas import Chapitre, JudgeVerdict, Partie, SousSection, TocSchema


def test_toc_schema_valid():
    toc = TocSchema(
        titre_manuel="Manuel",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(
                        numero=1,
                        titre="Intro",
                        description="d",
                        sous_sections=[SousSection(numero="1.1", titre="Def")],
                    )
                ],
            )
        ],
    )
    assert toc.parties[0].chapitres[0].sous_sections[0].numero == "1.1"


def test_toc_schema_rejects_empty_parties():
    with pytest.raises(ValidationError):
        TocSchema(titre_manuel="Manuel", parties=[])


def test_toc_schema_rejects_missing_field():
    with pytest.raises(ValidationError):
        TocSchema.model_validate({"parties": []})


@pytest.mark.parametrize("verdict", ["accept", "revise"])
def test_judge_verdict_valid_values(verdict):
    v = JudgeVerdict(verdict=verdict, issues=[])
    assert v.verdict == verdict


def test_judge_verdict_rejects_invalid_value():
    with pytest.raises(ValidationError):
        JudgeVerdict(verdict="maybe", issues=[])


def test_judge_verdict_default_issues_empty():
    v = JudgeVerdict(verdict="accept")
    assert v.issues == []
