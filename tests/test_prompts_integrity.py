from __future__ import annotations

from string import Template

import yaml

from manual_cli.generator import PROMPTS_DIR
from manual_cli.requirements_loader import DEFAULT_REQUIREMENTS_PATH, load_requirements
from manual_cli.subjects import SubjectSpec

PROMPT_FILES = [
    "system_prompt.md",
    "toc_instruction.md",
    "section_instruction.md",
    "judge_instruction.md",
    "rewrite_instruction.md",
]


def test_all_prompt_files_exist():
    for name in PROMPT_FILES:
        assert (PROMPTS_DIR / name).exists(), name


def test_section_instruction_placeholders_are_substitutable():
    template = Template((PROMPTS_DIR / "section_instruction.md").read_text(encoding="utf-8"))
    result = template.substitute(numero=1, titre="Titre", description="Desc", sous_sections="- x", digest="mem", plan="PLAN-X", intitule="1. Titre", role_note="", sources="SRC-X")
    assert "PLAN-X" in result and "SRC-X" in result
    assert "Titre" in result
    assert "mem" in result


def test_judge_instruction_placeholders_are_substitutable():
    template = Template((PROMPTS_DIR / "judge_instruction.md").read_text(encoding="utf-8"))
    result = template.substitute(requirements="- crit", section_text="texte")
    assert "texte" in result


def test_rewrite_instruction_placeholders_are_substitutable():
    template = Template((PROMPTS_DIR / "rewrite_instruction.md").read_text(encoding="utf-8"))
    result = template.substitute(section_text="orig", issues="- pb", numero=2)
    assert "orig" in result


def test_system_prompt_template_placeholders_are_exactly_the_subject_fields():
    template = Template((PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8"))
    assert set(template.get_identifiers()) == {
        "role",
        "objectif",
        "public",
        "niveau",
        "ton",
        "langue",
        "exclusions_section",
        "instructions_section",
    }


def test_toc_instruction_template_only_needs_the_plan_directeur():
    template = Template((PROMPTS_DIR / "toc_instruction.md").read_text(encoding="utf-8"))
    assert set(template.get_identifiers()) == {"plan_directeur"}


def test_subject_template_lists_every_subject_field():
    data = yaml.safe_load((PROMPTS_DIR / "subject_template.yml").read_text(encoding="utf-8"))
    assert set(data) == set(SubjectSpec.model_fields)


def test_shared_requirements_are_subject_agnostic():
    data = load_requirements(DEFAULT_REQUIREMENTS_PATH)
    assert data["generic"]
    assert "parties" not in data
    assert "multi_modeles" not in [c["id"] for c in data["generic"]]
    text = " ".join(c["description"] for c in data["generic"]).lower()
    for word in ("prompt", "few-shot", "token"):
        assert word not in text, f"critère commun lié au prompt engineering : {word!r}"


def test_authoring_templates_use_exactly_their_placeholders():
    expected = {
        "subject_generate_instruction.md": {"brief", "criteres_communs"},
        "subject_refine_instruction.md": {"current", "instruction"},
        "partie_criteria_instruction.md": {"subject_yaml", "parties", "criteres_existants"},
        "author_system_prompt.md": set(),
    }
    for name, placeholders in expected.items():
        template = Template((PROMPTS_DIR / name).read_text(encoding="utf-8"))
        assert set(template.get_identifiers()) == placeholders, name


def test_improve_templates_use_exactly_their_placeholders():
    template = Template((PROMPTS_DIR / "improve_instruction.md").read_text(encoding="utf-8"))
    assert set(template.get_identifiers()) == {
        "numero", "titre", "description", "sous_sections", "digest", "contenu_existant", "consigne", "plan", "intitule", "role_note", "sources",
    }
    default = Template((PROMPTS_DIR / "improve_default_instruction.md").read_text(encoding="utf-8"))
    assert set(default.get_identifiers()) == set()
    assert default.template.strip()


def test_toc_improve_templates_use_exactly_their_placeholders():
    template = Template((PROMPTS_DIR / "toc_improve_instruction.md").read_text(encoding="utf-8"))
    assert set(template.get_identifiers()) == {"toc_actuelle", "consigne", "chapitres_figes"}
    default = Template((PROMPTS_DIR / "toc_improve_default_instruction.md").read_text(encoding="utf-8"))
    assert set(default.get_identifiers()) == set()
    assert "Relis" in default.template


def test_glossary_templates_use_exactly_their_placeholders():
    expected = {
        "glossary_extract_instruction.md": {"numero", "titre", "texte"},
        "glossary_merge_instruction.md": {"entrees"},
    }
    for name, placeholders in expected.items():
        template = Template((PROMPTS_DIR / name).read_text(encoding="utf-8"))
        assert set(template.get_identifiers()) == placeholders, name


def test_sources_templates_use_exactly_their_placeholders():
    expected = {
        "sources_extract_instruction.md": {"contexte", "fichier", "texte"},
        "sources_consolidate_instruction.md": {"unites"},
    }
    for name, placeholders in expected.items():
        template = Template((PROMPTS_DIR / name).read_text(encoding="utf-8"))
        assert set(template.get_identifiers()) == placeholders, name
