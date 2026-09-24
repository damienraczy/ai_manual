from __future__ import annotations

import pytest

from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import (
    build_manual_state,
    load_state,
    save_state,
    slugify,
    state_exists,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Introduction Générale", "introduction-generale"),
        ("Chain-of-Thought & ReAct", "chain-of-thought-react"),
        ("Été 2025 : rétrospective", "ete-2025-retrospective"),
        ("   ", "section"),
        ("", "section"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected


def make_toc() -> TocSchema:
    return TocSchema(
        titre_manuel="Manuel Test",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(
                        numero=1,
                        titre="Introduction",
                        description="d1",
                        sous_sections=[SousSection(numero="1.1", titre="Def")],
                    ),
                    Chapitre(numero=2, titre="Anatomie", description="d2", sous_sections=[]),
                ],
            ),
            Partie(
                numero="II",
                titre="Avancé",
                chapitres=[
                    Chapitre(
                        numero=3,
                        titre="RAG",
                        description="d3",
                        sous_sections=[SousSection(numero="3.1", titre="Archi")],
                    ),
                ],
            ),
        ],
    )


def test_build_manual_state_flattens_and_orders():
    state = build_manual_state(make_toc())

    assert [s.numero for s in state.sections] == [1, 2, 3]
    assert state.sections[0].filename == "01_introduction.md"
    assert state.sections[2].partie_titre == "Avancé"
    assert state.sections[0].status == "pending"
    assert state.sections[0].sous_sections == ["1.1 Def"]
    assert state.sections[1].sous_sections == []


def test_save_and_load_state_round_trip(tmp_path):
    state = build_manual_state(make_toc())
    output_dir = tmp_path / "out"

    assert not state_exists(output_dir)
    save_state(output_dir, state)
    assert state_exists(output_dir)

    loaded = load_state(output_dir)
    assert loaded.titre_manuel == state.titre_manuel
    assert [s.numero for s in loaded.sections] == [1, 2, 3]


def test_section_by_numero_found_and_missing():
    state = build_manual_state(make_toc())
    assert state.section_by_numero(2).titre == "Anatomie"
    with pytest.raises(KeyError):
        state.section_by_numero(999)
