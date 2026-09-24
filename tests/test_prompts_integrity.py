from __future__ import annotations

from string import Template

from manual_cli.generator import PROMPTS_DIR
from manual_cli.requirements_loader import DEFAULT_REQUIREMENTS_PATH, load_requirements

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
    result = template.substitute(numero=1, titre="Titre", description="Desc", sous_sections="- x", digest="mem")
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


def test_real_requirements_file_loads_and_has_expected_parties():
    data = load_requirements(DEFAULT_REQUIREMENTS_PATH)
    assert "generic" in data
    assert set(data["parties"]) == {
        "Fondamentaux",
        "Techniques avancées",
        "Évaluation et optimisation",
        "Frontier techniques 2025-2026",
    }
