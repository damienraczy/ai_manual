from __future__ import annotations

import pytest
import yaml

from manual_cli import subjects
from manual_cli.subjects import (
    Subject,
    SubjectError,
    list_subjects,
    load_subject,
    resolve_slug,
    scaffold_subject,
)

VALID_SPEC = {
    "titre": "Cybersécurité pour dirigeants",
    "langue": "français",
    "role": "Tu es un RSSI expérimenté et formateur.",
    "objectif": "Produire un manuel de référence sur la cybersécurité.",
    "public": "dirigeants non techniques",
    "niveau": "débutant → intermédiaire",
    "ton": "clair et factuel",
    "plan_directeur": "menaces → gouvernance → réponse à incident",
}


def make_subject_dir(root, slug="cyber", spec=None, **files):
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "subject.yml").write_text(
        yaml.safe_dump(VALID_SPEC if spec is None else spec, allow_unicode=True), encoding="utf-8"
    )
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    return directory


# --- list_subjects / resolve_slug ---------------------------------------------


def test_list_subjects_returns_sorted_slugs_with_subject_yml(tmp_path):
    make_subject_dir(tmp_path, "b-sujet")
    make_subject_dir(tmp_path, "a-sujet")
    (tmp_path / "pas-un-sujet").mkdir()
    (tmp_path / "fichier.txt").write_text("x", encoding="utf-8")
    assert list_subjects(tmp_path) == ["a-sujet", "b-sujet"]


def test_list_subjects_empty_when_directory_missing(tmp_path):
    assert list_subjects(tmp_path / "absent") == []


def test_resolve_slug_returns_requested_slug_when_it_exists(tmp_path):
    make_subject_dir(tmp_path, "cyber")
    make_subject_dir(tmp_path, "autre")
    assert resolve_slug("cyber", tmp_path) == "cyber"


def test_resolve_slug_rejects_unknown_slug_and_lists_available(tmp_path):
    make_subject_dir(tmp_path, "cyber")
    with pytest.raises(SubjectError, match="inconnu.*cyber"):
        resolve_slug("nope", tmp_path)


def test_resolve_slug_defaults_to_the_only_subject(tmp_path):
    make_subject_dir(tmp_path, "cyber")
    assert resolve_slug(None, tmp_path) == "cyber"


def test_resolve_slug_requires_explicit_choice_when_several_subjects(tmp_path):
    make_subject_dir(tmp_path, "cyber")
    make_subject_dir(tmp_path, "autre")
    with pytest.raises(SubjectError, match="--subject.*autre, cyber"):
        resolve_slug(None, tmp_path)


def test_resolve_slug_fails_when_no_subject_exists(tmp_path):
    with pytest.raises(SubjectError, match="Aucun sujet.*manual subject new"):
        resolve_slug(None, tmp_path)


# --- load_subject -------------------------------------------------------------


def test_load_subject_reads_fields_and_defaults(tmp_path):
    make_subject_dir(tmp_path)
    subject = load_subject("cyber", tmp_path)
    assert isinstance(subject, Subject)
    assert subject.slug == "cyber"
    assert subject.titre == "Cybersécurité pour dirigeants"
    assert subject.exclusions == []
    assert subject.instructions == ""
    assert subject.directory == tmp_path / "cyber"


def test_load_subject_rejects_unknown_slug(tmp_path):
    with pytest.raises(SubjectError, match="introuvable"):
        load_subject("nope", tmp_path)


@pytest.mark.parametrize("missing", sorted(VALID_SPEC))
def test_load_subject_names_the_missing_field(tmp_path, missing):
    spec = {k: v for k, v in VALID_SPEC.items() if k != missing}
    make_subject_dir(tmp_path, spec=spec)
    with pytest.raises(SubjectError, match=missing):
        load_subject("cyber", tmp_path)


def test_load_subject_rejects_unknown_field(tmp_path):
    make_subject_dir(tmp_path, spec={**VALID_SPEC, "typo": "x"})
    with pytest.raises(SubjectError, match="typo"):
        load_subject("cyber", tmp_path)


def test_load_subject_rejects_empty_or_non_mapping_file(tmp_path):
    make_subject_dir(tmp_path, spec=["liste"])
    with pytest.raises(SubjectError, match="invalide"):
        load_subject("cyber", tmp_path)


def test_load_subject_rejects_invalid_yaml(tmp_path):
    directory = make_subject_dir(tmp_path)
    (directory / "subject.yml").write_text("titre: [non fermé", encoding="utf-8")
    with pytest.raises(SubjectError, match="YAML"):
        load_subject("cyber", tmp_path)


def test_load_subject_rejects_placeholders_left_by_scaffold(tmp_path):
    make_subject_dir(tmp_path, spec={**VALID_SPEC, "ton": "À COMPLÉTER"})
    with pytest.raises(SubjectError, match="ton.*À COMPLÉTER"):
        load_subject("cyber", tmp_path)


def test_load_subject_rejects_blank_field(tmp_path):
    make_subject_dir(tmp_path, spec={**VALID_SPEC, "role": "   "})
    with pytest.raises(SubjectError, match="role"):
        load_subject("cyber", tmp_path)


# --- rendu des prompts --------------------------------------------------------


def test_system_prompt_injects_subject_fields(tmp_path):
    make_subject_dir(tmp_path)
    prompt = load_subject("cyber", tmp_path).system_prompt()
    for expected in (VALID_SPEC["role"], VALID_SPEC["objectif"], VALID_SPEC["public"], VALID_SPEC["ton"]):
        assert expected in prompt
    assert "français" in prompt
    assert "$" not in prompt


def test_system_prompt_omits_optional_sections_when_empty(tmp_path):
    make_subject_dir(tmp_path)
    prompt = load_subject("cyber", tmp_path).system_prompt()
    assert "Hors périmètre" not in prompt
    assert "Consignes complémentaires" not in prompt


def test_system_prompt_includes_exclusions_and_instructions(tmp_path):
    spec = {**VALID_SPEC, "exclusions": ["programmation", "juridique"], "instructions": "Cite des cas réels."}
    make_subject_dir(tmp_path, spec=spec)
    prompt = load_subject("cyber", tmp_path).system_prompt()
    assert "Hors périmètre" in prompt
    assert "- programmation" in prompt
    assert "- juridique" in prompt
    assert "Consignes complémentaires" in prompt
    assert "Cite des cas réels." in prompt


def test_system_prompt_keeps_generic_output_rules(tmp_path):
    make_subject_dir(tmp_path)
    prompt = load_subject("cyber", tmp_path).system_prompt()
    assert "Format de sortie" in prompt
    assert "Markdown strict" in prompt


def test_system_prompt_override_file_is_used_verbatim(tmp_path):
    make_subject_dir(tmp_path, **{"system_prompt.md": "Prompt maison $pas_touche"})
    assert load_subject("cyber", tmp_path).system_prompt() == "Prompt maison $pas_touche"


def test_toc_instruction_injects_plan_directeur_and_keeps_json_schema(tmp_path):
    make_subject_dir(tmp_path)
    instruction = load_subject("cyber", tmp_path).toc_instruction()
    assert "menaces → gouvernance → réponse à incident" in instruction
    assert '"titre_manuel"' in instruction
    assert "$" not in instruction


def test_toc_instruction_override_file_is_used_verbatim(tmp_path):
    make_subject_dir(tmp_path, **{"toc_instruction.md": "Plan maison"})
    assert load_subject("cyber", tmp_path).toc_instruction() == "Plan maison"


# --- exigences ----------------------------------------------------------------


def test_requirements_without_subject_file_are_the_shared_base(tmp_path):
    make_subject_dir(tmp_path)
    requirements = load_subject("cyber", tmp_path).requirements()
    assert requirements["generic"]
    assert requirements.get("parties", {}) == {}


def test_requirements_merge_subject_criteria_after_shared_base(tmp_path):
    extra = {
        "generic": [{"id": "extra", "description": "d", "severity": "recommande"}],
        "parties": {"Menaces": [{"id": "p", "description": "d", "severity": "bloquant"}]},
    }
    make_subject_dir(tmp_path, **{"requirements.yml": yaml.safe_dump(extra)})
    requirements = load_subject("cyber", tmp_path).requirements()
    ids = [c["id"] for c in requirements["generic"]]
    assert ids[-1] == "extra"
    assert "definition_claire" in ids
    assert requirements["parties"]["Menaces"][0]["id"] == "p"


def test_requirements_file_may_only_declare_parties(tmp_path):
    extra = {"parties": {"Menaces": [{"id": "p", "description": "d", "severity": "bloquant"}]}}
    make_subject_dir(tmp_path, **{"requirements.yml": yaml.safe_dump(extra)})
    requirements = load_subject("cyber", tmp_path).requirements()
    assert "definition_claire" in [c["id"] for c in requirements["generic"]]
    assert "Menaces" in requirements["parties"]


def test_requirements_file_that_is_not_a_mapping_is_rejected(tmp_path):
    make_subject_dir(tmp_path, **{"requirements.yml": "- juste une liste\n"})
    with pytest.raises(SubjectError, match="requirements.yml"):
        load_subject("cyber", tmp_path).requirements()


def test_requirements_rejects_duplicate_criterion_ids(tmp_path):
    extra = {"generic": [{"id": "definition_claire", "description": "d", "severity": "bloquant"}]}
    make_subject_dir(tmp_path, **{"requirements.yml": yaml.safe_dump(extra)})
    with pytest.raises(SubjectError, match="definition_claire"):
        load_subject("cyber", tmp_path).requirements()


# --- scaffold_subject ---------------------------------------------------------


def test_scaffold_creates_subject_yml_and_requirements(tmp_path):
    directory = scaffold_subject("nouveau-sujet", tmp_path)
    assert directory == tmp_path / "nouveau-sujet"
    assert (directory / "subject.yml").is_file()
    assert (directory / "requirements.yml").is_file()


def test_scaffolded_subject_is_rejected_until_completed(tmp_path):
    scaffold_subject("nouveau-sujet", tmp_path)
    with pytest.raises(SubjectError, match="À COMPLÉTER"):
        load_subject("nouveau-sujet", tmp_path)


def test_scaffolded_files_become_valid_once_filled(tmp_path):
    directory = scaffold_subject("nouveau-sujet", tmp_path)
    (directory / "subject.yml").write_text(yaml.safe_dump(VALID_SPEC, allow_unicode=True), encoding="utf-8")
    subject = load_subject("nouveau-sujet", tmp_path)
    assert subject.requirements()["generic"]


def test_scaffold_refuses_to_overwrite_existing_subject(tmp_path):
    make_subject_dir(tmp_path, "cyber")
    with pytest.raises(SubjectError, match="existe déjà"):
        scaffold_subject("cyber", tmp_path)


@pytest.mark.parametrize("bad", ["", "Majuscule", "avec espace", "../evade", "-tiret", "a/b"])
def test_scaffold_rejects_invalid_slug(tmp_path, bad):
    with pytest.raises(SubjectError, match="Identifiant invalide"):
        scaffold_subject(bad, tmp_path)


def test_default_subjects_dir_is_the_repository_subjects_folder():
    assert subjects.SUBJECTS_DIR.name == "subjects"
    assert subjects.SUBJECTS_DIR.parent == subjects.PROMPTS_DIR.parent


# --- validation des critères --------------------------------------------------


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"generic": "pas une liste"}, "liste de critères"),
        ({"generic": ["pas un dict"]}, "id, description et severity"),
        ({"generic": [{"id": "x", "description": "d"}]}, "id, description et severity"),
        ({"generic": [{"id": "x", "description": "d", "severity": "grave"}]}, "severity.*grave"),
        ({"parties": {"P": "pas une liste"}}, "partie « P »"),
    ],
)
def test_requirements_rejects_malformed_criteria(tmp_path, extra, message):
    make_subject_dir(tmp_path, **{"requirements.yml": yaml.safe_dump(extra)})
    with pytest.raises(SubjectError, match=message):
        load_subject("cyber", tmp_path).requirements()


def test_requirements_rejects_invalid_yaml(tmp_path):
    make_subject_dir(tmp_path, **{"requirements.yml": "generic: [non fermé"})
    with pytest.raises(SubjectError, match="YAML invalide"):
        load_subject("cyber", tmp_path).requirements()


# --- sujet fourni avec le dépôt -----------------------------------------------


def test_bundled_prompt_engineering_subject_is_valid():
    subject = load_subject("prompt-engineering")
    assert "Prompt Engineering" in subject.system_prompt()
    assert "RAG" in subject.system_prompt()
    assert "frontier techniques 2025-2026" in subject.toc_instruction()
    requirements = subject.requirements()
    assert set(requirements["parties"]) == {
        "Fondamentaux",
        "Techniques avancées",
        "Évaluation et optimisation",
        "Frontier techniques 2025-2026",
    }
    assert "multi_modeles" in [c["id"] for c in requirements["generic"]]
    assert "definition_claire" in [c["id"] for c in requirements["generic"]]


@pytest.mark.parametrize(
    "field, value",
    [("instructions", "À COMPLÉTER"), ("exclusions", ["ok", "À COMPLÉTER"])],
)
def test_load_subject_rejects_placeholder_in_optional_fields(tmp_path, field, value):
    make_subject_dir(tmp_path, spec={**VALID_SPEC, field: value})
    with pytest.raises(SubjectError, match=f"{field}.*À COMPLÉTER"):
        load_subject("cyber", tmp_path)
