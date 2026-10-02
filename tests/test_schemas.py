from __future__ import annotations

import pytest
from pydantic import ValidationError

from manual_cli.schemas import Chapitre, GeneratedTocSchema, JudgeVerdict, Partie, SousSection, TocSchema


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


def toc_payload(description):
    sous_section = {"numero": "1.1", "titre": "Def"}
    if description is not None:
        sous_section["description"] = description
    return {
        "titre_manuel": "M",
        "parties": [
            {
                "numero": "I",
                "titre": "P",
                "chapitres": [{"numero": 1, "titre": "Intro", "description": "d", "sous_sections": [sous_section]}],
            }
        ],
    }


def test_sous_section_description_and_label():
    sous_section = SousSection(numero="1.1", titre="Def", description="définit le terme")

    assert sous_section.description == "définit le terme"
    assert sous_section.label == "1.1 Def"


def test_toc_schema_still_reads_a_sous_section_without_description():
    toc = TocSchema.model_validate(toc_payload(None))

    assert toc.parties[0].chapitres[0].sous_sections[0].description == ""


def test_generated_toc_schema_accepts_described_sous_sections():
    toc = GeneratedTocSchema.model_validate(toc_payload("définit le terme"))

    assert toc.parties[0].chapitres[0].sous_sections[0].description == "définit le terme"


@pytest.mark.parametrize("description", [None, "", "   "])
def test_generated_toc_schema_requires_a_description_and_names_the_sous_section(description):
    with pytest.raises(ValidationError, match="1.1 Def"):
        GeneratedTocSchema.model_validate(toc_payload(description))


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
