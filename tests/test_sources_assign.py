"""Affectation des unités de matière aux chapitres et rendu du bloc injecté à la rédaction."""

from __future__ import annotations

import json

import pytest
import yaml

from manual_cli import sources, sources_assign
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.parsing import ParsingError
from manual_cli.schemas import Cadre, Chapitre, Partie, TocSchema
from manual_cli.sources import FileEntry, SourceIndex, SourcesError, Unite
from manual_cli.sources_assign import SourcesMap
from manual_cli.state import build_manual_state


def make_cfg(batch=10, budget=10000) -> AppConfig:
    spec = ModelSpec(key="m", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)
    return AppConfig(
        roles={"model_think": spec},
        settings={"sources": {"max_chunk_chars": 1000, "assign_batch": batch, "max_prompt_chars": budget}},
    )


def make_state():
    toc = TocSchema(
        titre_manuel="M",
        introduction=Cadre(titre="Introduction", description="ouvre"),
        parties=[
            Partie(
                numero="I",
                titre="P",
                chapitres=[
                    Chapitre(numero=1, titre="Un", description="d1", sous_sections=[]),
                    Chapitre(numero=2, titre="Deux", description="d2", sous_sections=[]),
                ],
            )
        ],
        conclusion=Cadre(titre="Conclusion", description="ferme"),
    )
    return build_manual_state(toc)


def unit(n, type_="idee", utilite="haute", enonce=None, source="a.md", **extra) -> Unite:
    return Unite(
        id=f"{source}#{n}",
        source=source,
        ligne=n,
        type=type_,
        enonce=enonce or f"énoncé {n}",
        extrait=f"extrait {n}",
        utilite=utilite,
        **extra,
    )


def make_index(*units) -> SourceIndex:
    by_file: dict[str, list[Unite]] = {}
    for u in units:
        by_file.setdefault(u.source, []).append(u)
    return SourceIndex(fichiers={name: FileEntry(hash="h", unites=us) for name, us in by_file.items()})


class Scripted:
    def __init__(self, handler):
        self.handler = handler
        self.prompts: list[str] = []

    def install(self, monkeypatch):
        outer = self

        class _C:
            def chat(self, messages):
                prompt = messages[-1]["content"]
                outer.prompts.append(prompt)
                return "```json\n" + json.dumps(outer.handler(prompt)) + "\n```"

        monkeypatch.setattr(sources, "_client", lambda cfg, role: _C())
        return self


def aff(unite, principal, secondaire=None):
    return {"unite": unite, "principal": principal, "secondaire": secondaire}


# --- carte ----------------------------------------------------------------------------


def test_map_round_trips_and_is_hand_editable(tmp_path):
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"], secondaire=["a.md#2"])}, orphelines=["a.md#3"])

    sources_assign.save_map(tmp_path, smap)
    text = (tmp_path / "sources_map.yml").read_text(encoding="utf-8")

    assert text.startswith("#") and "Un:" in text and "a.md#1" in text
    assert sources_assign.load_map(tmp_path) == smap


def test_load_map_is_empty_when_missing(tmp_path):
    assert sources_assign.load_map(tmp_path) == SourcesMap()


@pytest.mark.parametrize(
    "content",
    ["{pas du yaml", "- une liste\n", "Un: texte\n", "Un:\n  principal: a.md#1\n", "Un:\n  principal: [a.md#1]\nDeux:\n  principal: [a.md#1]\n"],
)
def test_load_map_rejects_malformed_or_ambiguous_files(tmp_path, content):
    (tmp_path / "sources_map.yml").write_text(content, encoding="utf-8")

    with pytest.raises(SourcesError, match="sources_map.yml"):
        sources_assign.load_map(tmp_path)


# --- affectation ----------------------------------------------------------------------


def test_assign_places_each_unit_in_one_principal_chapter(tmp_path, monkeypatch):
    index = make_index(unit(1), unit(2), unit(3))
    scripted = Scripted(lambda p: {"affectations": [aff("a.md#1", "Un"), aff("a.md#2", "Deux", "Un"), aff("a.md#3", None)]}).install(monkeypatch)

    report = sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)

    smap = sources_assign.load_map(tmp_path)
    assert smap.chapitres["Un"].principal == ["a.md#1"] and smap.chapitres["Un"].secondaire == ["a.md#2"]
    assert smap.chapitres["Deux"].principal == ["a.md#2"]
    assert smap.orphelines == ["a.md#3"]
    assert report.assigned == 3 and report.orphans == ["a.md#3"]
    assert "Introduction" in scripted.prompts[0] and "Conclusion" in scripted.prompts[0]


def test_assign_prompt_lists_units_and_exact_titles(tmp_path, monkeypatch):
    index = make_index(unit(1, enonce="une idée précise"))
    scripted = Scripted(lambda p: {"affectations": [aff("a.md#1", "Un")]}).install(monkeypatch)

    sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)

    assert "a.md#1" in scripted.prompts[0] and "une idée précise" in scripted.prompts[0]
    assert "- Un\n" in scripted.prompts[0]


def test_assign_ignores_useless_units(tmp_path, monkeypatch):
    index = make_index(unit(1), unit(2, utilite="nulle"))
    scripted = Scripted(lambda p: {"affectations": [aff("a.md#1", "Un")]}).install(monkeypatch)

    sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)

    assert "a.md#2" not in scripted.prompts[0]


def test_assign_works_in_batches(tmp_path, monkeypatch):
    index = make_index(unit(1), unit(2), unit(3))

    def handler(prompt):
        ids = [i for i in ("a.md#1", "a.md#2", "a.md#3") if f"- {i} |" in prompt]
        return {"affectations": [aff(i, "Un") for i in ids]}

    scripted = Scripted(handler).install(monkeypatch)

    sources_assign.ensure_assignment(make_cfg(batch=2), make_state(), index, tmp_path)

    assert len(scripted.prompts) == 2
    assert sources_assign.load_map(tmp_path).chapitres["Un"].principal == ["a.md#1", "a.md#2", "a.md#3"]


@pytest.mark.parametrize(
    "answer",
    [
        [aff("a.md#1", "Chapitre inventé")],
        [aff("a.md#1", "Un", "Chapitre inventé")],
        [aff("a.md#1", "Un", "Un")],
        [aff("a.md#1", None, "Un")],
        [aff("a.md#9", "Un")],
        [],
        [aff("a.md#1", "Un"), aff("a.md#1", "Deux")],
    ],
)
def test_assign_rejects_inconsistent_answers(tmp_path, monkeypatch, answer):
    index = make_index(unit(1))
    Scripted(lambda p: {"affectations": answer}).install(monkeypatch)

    with pytest.raises(ParsingError):
        sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)


def test_assign_keeps_a_hand_edited_map_and_only_places_new_units(tmp_path, monkeypatch):
    sources_assign.save_map(tmp_path, SourcesMap(chapitres={"Deux": sources_assign.ChapterUnits(principal=["a.md#1"])}))
    before = (tmp_path / "sources_map.yml").read_text(encoding="utf-8")
    (tmp_path / "sources_map.yml").write_text(before + "# ma note\n", encoding="utf-8")
    index = make_index(unit(1), unit(2))
    scripted = Scripted(lambda p: {"affectations": [aff("a.md#2", "Un")]}).install(monkeypatch)

    report = sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)

    smap = sources_assign.load_map(tmp_path)
    assert smap.chapitres["Deux"].principal == ["a.md#1"] and smap.chapitres["Un"].principal == ["a.md#2"]
    assert "a.md#1 |" not in scripted.prompts[0]
    assert report.assigned == 1


def test_assign_does_not_touch_the_file_when_nothing_is_pending(tmp_path, monkeypatch):
    sources_assign.save_map(tmp_path, SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"])}))
    path = tmp_path / "sources_map.yml"
    path.write_text(path.read_text(encoding="utf-8") + "# ma note\n", encoding="utf-8")
    scripted = Scripted(lambda p: {"affectations": []}).install(monkeypatch)

    report = sources_assign.ensure_assignment(make_cfg(), make_state(), make_index(unit(1)), tmp_path)

    assert scripted.prompts == [] and report.assigned == 0
    assert "# ma note" in path.read_text(encoding="utf-8")


def test_assign_drops_vanished_units_and_chapters_then_reassigns(tmp_path, monkeypatch):
    sources_assign.save_map(
        tmp_path,
        SourcesMap(
            chapitres={
                "Ancien chapitre": sources_assign.ChapterUnits(principal=["a.md#1"]),
                "Un": sources_assign.ChapterUnits(principal=["a.md#2", "gone.md#1"], secondaire=["gone.md#2"]),
            },
            orphelines=["gone.md#3"],
        ),
    )
    index = make_index(unit(1), unit(2))
    Scripted(lambda p: {"affectations": [aff("a.md#1", "Deux")]}).install(monkeypatch)

    report = sources_assign.ensure_assignment(make_cfg(), make_state(), index, tmp_path)

    smap = sources_assign.load_map(tmp_path)
    assert "Ancien chapitre" not in smap.chapitres
    assert smap.chapitres["Un"].principal == ["a.md#2"] and smap.chapitres["Un"].secondaire == []
    assert smap.chapitres["Deux"].principal == ["a.md#1"] and smap.orphelines == []
    assert report.pruned == 4


def test_force_recomputes_everything_and_keeps_a_backup(tmp_path, monkeypatch):
    sources_assign.save_map(tmp_path, SourcesMap(chapitres={"Deux": sources_assign.ChapterUnits(principal=["a.md#1"])}))
    Scripted(lambda p: {"affectations": [aff("a.md#1", "Un")]}).install(monkeypatch)

    sources_assign.ensure_assignment(make_cfg(), make_state(), make_index(unit(1)), tmp_path, force=True)

    assert sources_assign.load_map(tmp_path).chapitres == {"Un": sources_assign.ChapterUnits(principal=["a.md#1"])}
    assert (tmp_path / "sources_map.yml.bak").is_file()


def test_orphan_units_are_active_units_without_principal_chapter():
    index = make_index(unit(1), unit(2), unit(3, utilite="nulle"), unit(4))
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"], secondaire=["a.md#2"])}, orphelines=["a.md#4"])

    assert [u.id for u in sources_assign.orphan_units(index, smap)] == ["a.md#2", "a.md#4"]


# --- rendu ----------------------------------------------------------------------------


def block_for(section_title, index, smap, budget=10000):
    return sources_assign.render_sources(make_state().sections[1 if section_title == "Un" else 2], index, smap, budget)


def test_render_is_empty_when_the_chapter_has_no_unit():
    block = block_for("Un", make_index(unit(1)), SourcesMap())

    assert block.text == "" and block.omitted == []


def test_render_groups_by_type_with_instructions_and_marks_must_cover():
    index = make_index(
        unit(1, "reference", enonce="Dupont, 2020"),
        unit(2, "passage", utilite="moyenne"),
        unit(3, "theme"),
    )
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1", "a.md#2", "a.md#3"])})

    text = block_for("Un", index, smap).text

    assert "matière à exploiter, pas une vérité" in text
    assert "n'en invente aucune autre" in text and "étoffe" in text
    assert "[a.md#1] **À COUVRIR**" in text and "[a.md#2]" in text and "[a.md#2] **À COUVRIR**" not in text
    assert "« extrait 1 »" in text and "a.md, l.1" in text
    assert "Dupont, 2020" in text


def test_render_never_includes_useless_units():
    index = make_index(unit(1, utilite="nulle"))
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"])})

    assert block_for("Un", index, smap).text == ""


def test_render_flags_conflicts_and_other_sources():
    index = make_index(
        unit(1, conflit_avec=["a.md#2"], autres_sources=["b.md"]),
        unit(2),
    )
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"]), "Deux": sources_assign.ChapterUnits(principal=["a.md#2"])})

    text = block_for("Un", index, smap).text

    assert "⚠ contredit [a.md#2] : énoncé 2" in text
    assert "aussi dans b.md" in text


def test_render_lists_secondary_units_as_pointers_to_their_principal_chapter():
    index = make_index(unit(1, enonce="idée voisine"))
    smap = SourcesMap(
        chapitres={
            "Un": sources_assign.ChapterUnits(secondaire=["a.md#1"]),
            "Deux": sources_assign.ChapterUnits(principal=["a.md#1"]),
        }
    )

    text = block_for("Un", index, smap).text

    assert "renvoi" in text.lower() and "[a.md#1] idée voisine → traité au chapitre « Deux »" in text
    assert "] **À COUVRIR**" not in text


def test_render_shortens_then_omits_units_over_budget_and_says_so():
    units = [unit(i, enonce="e" * 40) for i in range(1, 6)]
    index = make_index(*units)
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=[u.id for u in units])})
    full = block_for("Un", index, smap).text

    short = block_for("Un", index, smap, budget=len(full) - 100)
    tiny = block_for("Un", index, smap, budget=700)

    assert short.omitted == [] and "extrait 5" not in short.text and "e" * 40 in short.text
    assert tiny.omitted and "omis" in tiny.text.lower() and tiny.omitted[0] in tiny.text


def test_render_keeps_must_cover_units_before_others_when_cutting():
    index = make_index(unit(1, utilite="moyenne", enonce="m" * 60), unit(2, utilite="haute", enonce="h" * 60))
    smap = SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1", "a.md#2"])})
    full = block_for("Un", index, smap).text

    cut = block_for("Un", index, smap, budget=len(full) - 80)

    assert "h" * 60 in cut.text and "a.md#1" in cut.omitted


# --- accès depuis la rédaction ---------------------------------------------------------


def test_sources_for_section_is_empty_without_index(tmp_path):
    section = make_state().sections[1]

    assert sources_assign.sources_for_section(make_cfg(), tmp_path, section) == ""


def test_sources_for_section_reads_the_index_and_the_map(tmp_path):
    index = make_index(unit(1, enonce="matière du chapitre un"))
    (tmp_path / "sources_index.json").write_text(index.model_dump_json(), encoding="utf-8")
    sources_assign.save_map(tmp_path, SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"])}))
    state = make_state()

    assert "matière du chapitre un" in sources_assign.sources_for_section(make_cfg(), tmp_path, state.sections[1])
    assert sources_assign.sources_for_section(make_cfg(), tmp_path, state.sections[2]) == ""


def test_map_file_is_plain_yaml(tmp_path):
    sources_assign.save_map(tmp_path, SourcesMap(chapitres={"Un": sources_assign.ChapterUnits(principal=["a.md#1"])}, orphelines=["a.md#2"]))

    data = yaml.safe_load((tmp_path / "sources_map.yml").read_text(encoding="utf-8"))

    assert data == {"Un": {"principal": ["a.md#1"], "secondaire": []}, "orphelines": ["a.md#2"]}


def test_assign_rejects_a_non_positive_batch(tmp_path):
    cfg = make_cfg(batch=0)

    with pytest.raises(SourcesError, match="assign_batch"):
        sources_assign.ensure_assignment(cfg, make_state(), make_index(unit(1)), tmp_path)
