from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import (
    StateError,
    render_plan,
    renumber_toc,
    SectionState,
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
    assert [ss.label for ss in state.sections[0].sous_sections] == ["1.1 Def"]
    assert state.sections[1].sous_sections == []


def test_build_manual_state_keeps_the_sous_section_descriptions():
    toc = make_toc()
    toc.parties[0].chapitres[0].sous_sections[0].description = "définit le terme"

    state = build_manual_state(toc)

    assert state.sections[0].sous_sections[0].description == "définit le terme"


def test_described_sous_sections_survive_a_round_trip(tmp_path):
    toc = make_toc()
    toc.parties[0].chapitres[0].sous_sections[0].description = "définit le terme"
    save_state(tmp_path, build_manual_state(toc))

    loaded = load_state(tmp_path)

    assert loaded.sections[0].sous_sections[0].description == "définit le terme"
    assert loaded.toc.parties[0].chapitres[0].sous_sections[0].description == "définit le terme"


def test_manifest_written_before_descriptions_still_loads(tmp_path):
    """Un manifeste ancien stocke les sous-sections en `"numero titre"` et sans description."""
    path = tmp_path / "manifest.json"
    data = json.loads(build_manual_state(make_toc()).model_dump_json())
    data["sections"][0]["sous_sections"] = ["1.1 Def"]
    for partie in data["toc"]["parties"]:
        for chapitre in partie["chapitres"]:
            for sous_section in chapitre["sous_sections"]:
                del sous_section["description"]
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_state(tmp_path)

    legacy = loaded.sections[0].sous_sections[0]
    assert (legacy.numero, legacy.titre, legacy.description) == ("1.1", "Def", "")
    assert loaded.toc.parties[0].chapitres[0].sous_sections[0].description == ""
    assert not (tmp_path / "toc.yml").exists()


def test_sous_sections_must_be_a_list():
    section = build_manual_state(make_toc()).sections[0].model_dump()
    section["sous_sections"] = "1.1 Def"

    with pytest.raises(ValidationError):
        SectionState.model_validate(section)


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


def test_subject_is_recorded_and_survives_a_round_trip(tmp_path):
    toc = TocSchema(
        titre_manuel="M",
        parties=[Partie(numero="I", titre="P", chapitres=[Chapitre(numero=1, titre="Un", description="d", sous_sections=[])])],
    )
    save_state(tmp_path, build_manual_state(toc, subject="cyber"))

    assert load_state(tmp_path).subject == "cyber"
    assert build_manual_state(toc).subject is None


def test_render_plan_lists_every_chapter_and_marks_the_current_one():
    state = build_manual_state(make_toc())
    plan = render_plan(state, current_numero=2)
    assert "Partie I — Fondamentaux" in plan
    assert "Partie II — Avancé" in plan
    assert "1. Introduction — d1" in plan
    assert "1.1 Def" in plan
    assert "3. RAG — d3" in plan
    line = next(l for l in plan.splitlines() if "2. Anatomie" in l)
    assert "CHAPITRE EN COURS" in line
    assert sum("CHAPITRE EN COURS" in l for l in plan.splitlines()) == 1


# --- persistance : toc.yml (plan éditable) + manifest.json (suivi) -----------------


def messy_toc() -> TocSchema:
    """Un plan dont les numéros sont incohérents, comme un LLM peut en produire."""
    return TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="1",
                titre="A",
                chapitres=[Chapitre(numero=7, titre="Un", description="d", sous_sections=[SousSection(numero="9.9", titre="x", description="dx")])],
            ),
            Partie(numero="Z", titre="B", chapitres=[Chapitre(numero=3, titre="Deux", description="d2", sous_sections=[])]),
        ],
    )


def test_renumber_toc_derives_every_number_from_the_position():
    toc = renumber_toc(messy_toc())

    assert [p.numero for p in toc.parties] == ["I", "II"]
    assert [c.numero for p in toc.parties for c in p.chapitres] == [1, 2]
    assert toc.parties[0].chapitres[0].sous_sections[0].numero == "1.1"


def test_renumber_toc_writes_roman_numerals_beyond_ten():
    parties = [Partie(numero="?", titre=f"P{i}", chapitres=[Chapitre(numero=i, titre=f"C{i}", description="d", sous_sections=[])]) for i in range(1, 15)]
    toc = renumber_toc(TocSchema(titre_manuel="M", parties=parties))
    assert [p.numero for p in toc.parties][8:14] == ["IX", "X", "XI", "XII", "XIII", "XIV"]
    assert toc.parties[3].numero == "IV"


def test_save_state_splits_the_plan_from_the_tracking(tmp_path):
    state = build_manual_state(make_toc(), subject="cyber")
    state.sections[0].status, state.sections[0].attempts, state.sections[0].last_verdict = "done", 2, "accept"
    save_state(tmp_path, state)

    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    assert "titre: Fondamentaux" in plan
    assert "numero" not in plan
    tracking = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert tracking["subject"] == "cyber"
    assert "toc" not in tracking
    assert tracking["sections"][0] == {"numero": 1, "titre": "Introduction", "status": "done", "attempts": 2, "last_verdict": "accept"}
    assert "description" not in json.dumps(tracking)


def test_split_state_round_trips_with_tracking(tmp_path):
    state = build_manual_state(make_toc(), subject="cyber")
    state.sections[1].status = "failed"
    save_state(tmp_path, state)

    loaded = load_state(tmp_path)

    assert loaded.subject == "cyber"
    assert [s.status for s in loaded.sections] == ["pending", "failed", "pending"]
    assert loaded.sections[2].sous_sections[0].numero == "3.1"
    assert loaded.toc.parties[1].numero == "II"
    assert loaded.model_dump() == state.model_dump()


def test_hand_edited_plan_is_picked_up_and_keeps_the_tracking(tmp_path):
    state = build_manual_state(make_toc())
    state.sections[0].status = "done"
    save_state(tmp_path, state)
    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    (tmp_path / "toc.yml").write_text(plan.replace("description: d2", "description: nouvelle description"), encoding="utf-8")

    loaded = load_state(tmp_path)

    assert loaded.section_by_numero(2).description == "nouvelle description"
    assert loaded.section_by_numero(1).status == "done"


def test_a_retitled_chapter_goes_back_to_pending(tmp_path):
    state = build_manual_state(make_toc())
    state.sections[0].status = "done"
    save_state(tmp_path, state)
    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    (tmp_path / "toc.yml").write_text(plan.replace("titre: Introduction", "titre: Autre titre"), encoding="utf-8")

    loaded = load_state(tmp_path)

    assert loaded.section_by_numero(1).titre == "Autre titre"
    assert loaded.section_by_numero(1).status == "pending"


def test_a_chapter_added_by_hand_is_pending(tmp_path):
    save_state(tmp_path, build_manual_state(make_toc()))
    plan = (tmp_path / "toc.yml").read_text(encoding="utf-8")
    plan += "      - titre: Ajouté\n        description: neuf\n        sous_sections: []\n"
    (tmp_path / "toc.yml").write_text(plan, encoding="utf-8")

    loaded = load_state(tmp_path)

    assert [s.titre for s in loaded.sections][-1] == "Ajouté"
    assert loaded.sections[-1].numero == 4 and loaded.sections[-1].status == "pending"


@pytest.mark.parametrize(
    "content, message",
    [
        ("titre_manuel: [", "toc.yml"),
        ("- une liste", "toc.yml"),
        ("titre_manuel: M\nparties: []\n", "toc.yml"),
        ("titre_manuel: M\nparties:\n  - titre: P\n", "toc.yml"),
    ],
)
def test_an_invalid_plan_file_fails_fast(tmp_path, content, message):
    save_state(tmp_path, build_manual_state(make_toc()))
    (tmp_path / "toc.yml").write_text(content, encoding="utf-8")

    with pytest.raises(StateError, match=message):
        load_state(tmp_path)


def test_a_manifest_without_plan_nor_toc_fails_fast(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"subject": "x", "sections": []}), encoding="utf-8")

    with pytest.raises(StateError, match="toc.yml"):
        load_state(tmp_path)


def test_a_legacy_manifest_is_migrated_on_the_next_save(tmp_path):
    (tmp_path / "manifest.json").write_text(build_manual_state(make_toc()).model_dump_json(), encoding="utf-8")

    save_state(tmp_path, load_state(tmp_path))

    assert (tmp_path / "toc.yml").is_file()
    assert "toc" not in json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))


def test_save_state_leaves_an_unchanged_plan_file_untouched(tmp_path):
    state = build_manual_state(make_toc())
    save_state(tmp_path, state)
    annotated = "# mes notes\n" + (tmp_path / "toc.yml").read_text(encoding="utf-8")
    (tmp_path / "toc.yml").write_text(annotated, encoding="utf-8")

    state.sections[0].status = "done"
    save_state(tmp_path, load_state(tmp_path))

    assert (tmp_path / "toc.yml").read_text(encoding="utf-8") == annotated


def test_save_state_rewrites_the_plan_file_when_the_plan_changed(tmp_path):
    save_state(tmp_path, build_manual_state(make_toc()))
    other = make_toc().model_copy(update={"titre_manuel": "Autre titre"})

    save_state(tmp_path, build_manual_state(other))

    assert "Autre titre" in (tmp_path / "toc.yml").read_text(encoding="utf-8")


def test_save_state_rewrites_an_unreadable_plan_file(tmp_path):
    save_state(tmp_path, build_manual_state(make_toc()))
    (tmp_path / "toc.yml").write_text("titre_manuel: [", encoding="utf-8")

    save_state(tmp_path, build_manual_state(make_toc()))

    assert load_state(tmp_path).titre_manuel == "Manuel Test"
