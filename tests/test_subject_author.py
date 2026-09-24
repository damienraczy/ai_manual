from __future__ import annotations

import json

import pytest
import yaml

from manual_cli import subject_author
from manual_cli.parsing import ParsingError
from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, save_state
from manual_cli.subjects import SubjectError, load_subject

SPEC = {
    "titre": "Cybersécurité pour dirigeants",
    "langue": "français",
    "role": "Tu es un RSSI expérimenté et formateur.",
    "objectif": "Produire un manuel de référence sur la cybersécurité.",
    "public": "dirigeants non techniques",
    "niveau": "débutant → intermédiaire",
    "ton": "clair et factuel",
    "plan_directeur": "menaces → gouvernance → réponse à incident",
    "exclusions": ["configuration technique"],
    "instructions": "Cite des incidents réels.",
}
CRITERE = {"id": "cas_incident", "description": "Un incident réel illustre le propos.", "severity": "recommande"}


def as_json(payload: dict) -> str:
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


class FakeClient:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self.replies.pop(0)


@pytest.fixture
def fake(monkeypatch):
    def install(*replies: str) -> FakeClient:
        client = FakeClient(list(replies))
        monkeypatch.setattr(subject_author, "_client", lambda cfg: client)
        return client

    return install


def write_subject(root, slug="cyber", spec=None, requirements=None):
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "subject.yml").write_text(yaml.safe_dump(spec or SPEC, allow_unicode=True), encoding="utf-8")
    if requirements is not None:
        (directory / "requirements.yml").write_text(yaml.safe_dump(requirements, allow_unicode=True), encoding="utf-8")
    return directory


# --- generate_subject ---------------------------------------------------------


def test_generate_subject_writes_a_valid_subject_from_the_brief(tmp_path, fake):
    fake(as_json({**SPEC, "criteres": [CRITERE]}))

    directory = subject_author.generate_subject(object(), "cyber", "Manuel de cybersécurité", tmp_path)

    assert directory == tmp_path / "cyber"
    subject = load_subject("cyber", tmp_path)
    assert subject.titre == SPEC["titre"]
    assert subject.exclusions == ["configuration technique"]
    assert "cas_incident" in [c["id"] for c in subject.requirements()["generic"]]


def test_generate_subject_sends_brief_and_shared_criteria_to_the_model(tmp_path, fake):
    client = fake(as_json(SPEC))

    subject_author.generate_subject(object(), "cyber", "Manuel de cybersécurité pour COMEX", tmp_path)

    messages = client.calls[0]
    assert messages[0]["role"] == "system"
    assert "Manuel de cybersécurité pour COMEX" in messages[1]["content"]
    assert "definition_claire" in messages[1]["content"]
    assert "$" not in messages[1]["content"]


def test_generate_subject_passes_a_long_multiline_brief_verbatim(tmp_path, fake):
    brief = "Manuel de cybersécurité.\n\nPublic : COMEX.\n- point 1\n- point 2"
    client = fake(as_json(SPEC))

    subject_author.generate_subject(object(), "cyber", brief, tmp_path)

    assert brief in client.calls[0][1]["content"]


def test_generate_subject_without_criteria_keeps_a_documented_requirements_file(tmp_path, fake):
    fake(as_json(SPEC))

    subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert (tmp_path / "cyber" / "requirements.yml").is_file()
    assert load_subject("cyber", tmp_path).requirements()["parties"] == {}


def test_generate_subject_rejects_existing_subject_before_calling_the_model(tmp_path, fake):
    write_subject(tmp_path)
    client = fake()

    with pytest.raises(SubjectError, match="existe déjà"):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert client.calls == []


def test_generate_subject_rejects_invalid_slug_before_calling_the_model(tmp_path, fake):
    client = fake()

    with pytest.raises(SubjectError, match="Identifiant invalide"):
        subject_author.generate_subject(object(), "Pas Valide", "brief", tmp_path)

    assert client.calls == []


def test_generate_subject_rejects_blank_brief(tmp_path, fake):
    client = fake()

    with pytest.raises(SubjectError, match="brief"):
        subject_author.generate_subject(object(), "cyber", "   ", tmp_path)

    assert client.calls == []


def test_generate_subject_refuses_criteria_clashing_with_shared_ones_and_writes_nothing(tmp_path, fake):
    clash = {**CRITERE, "id": "definition_claire"}
    fake(as_json({**SPEC, "criteres": [clash]}))

    with pytest.raises(SubjectError, match="definition_claire"):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert not (tmp_path / "cyber").exists()


def test_generate_subject_refuses_duplicate_criterion_ids_and_writes_nothing(tmp_path, fake):
    fake(as_json({**SPEC, "criteres": [CRITERE, CRITERE]}))

    with pytest.raises(SubjectError, match="cas_incident"):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert not (tmp_path / "cyber").exists()


def test_generate_subject_retries_when_the_model_answer_is_incomplete(tmp_path, fake):
    incomplete = {k: v for k, v in SPEC.items() if k != "ton"}
    client = fake(as_json(incomplete), as_json(SPEC))

    subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert len(client.calls) == 2
    assert load_subject("cyber", tmp_path).ton == "clair et factuel"


def test_generate_subject_gives_up_on_placeholders_and_writes_nothing(tmp_path, fake):
    bad = {**SPEC, "ton": "À COMPLÉTER"}
    fake(as_json(bad), as_json(bad), as_json(bad))

    with pytest.raises(ParsingError):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)

    assert not (tmp_path / "cyber").exists()


def test_generate_subject_rejects_unknown_severity(tmp_path, fake):
    bad = {**SPEC, "criteres": [{**CRITERE, "severity": "grave"}]}
    fake(as_json(bad), as_json(bad), as_json(bad))

    with pytest.raises(ParsingError):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)


@pytest.mark.parametrize(
    "criterion",
    [{**CRITERE, "id": "Pas Snake"}, {**CRITERE, "description": "  "}],
)
def test_generate_subject_rejects_malformed_criteria(tmp_path, fake, criterion):
    bad = as_json({**SPEC, "criteres": [criterion]})
    fake(bad, bad, bad)

    with pytest.raises(ParsingError):
        subject_author.generate_subject(object(), "cyber", "brief", tmp_path)


# --- refine_subject -----------------------------------------------------------


def test_refine_subject_applies_the_model_changes_and_reports_them(tmp_path, fake):
    write_subject(tmp_path)
    fake(as_json({**SPEC, "ton": "décontracté", "exclusions": ["configuration technique", "juridique"]}))

    changed = subject_author.refine_subject(object(), "cyber", "plus décontracté, sans juridique", tmp_path)

    assert changed == ["ton", "exclusions"]
    subject = load_subject("cyber", tmp_path)
    assert subject.ton == "décontracté"
    assert subject.exclusions == ["configuration technique", "juridique"]


def test_refine_subject_keeps_a_backup_of_the_previous_version(tmp_path, fake):
    directory = write_subject(tmp_path)
    original = (directory / "subject.yml").read_text(encoding="utf-8")
    fake(as_json({**SPEC, "ton": "décontracté"}))

    subject_author.refine_subject(object(), "cyber", "plus décontracté", tmp_path)

    assert (directory / "subject.yml.bak").read_text(encoding="utf-8") == original


def test_refine_subject_sends_current_content_and_instruction(tmp_path, fake):
    write_subject(tmp_path)
    client = fake(as_json(SPEC))

    subject_author.refine_subject(object(), "cyber", "ajoute un chapitre sur le juridique", tmp_path)

    content = client.calls[0][1]["content"]
    assert "ajoute un chapitre sur le juridique" in content
    assert "Tu es un RSSI expérimenté" in content
    assert "$" not in content


def test_refine_subject_passes_a_long_multiline_instruction_verbatim(tmp_path, fake):
    write_subject(tmp_path)
    instruction = "Change le ton.\n\n- plus court\n- plus concret"
    client = fake(as_json(SPEC))

    subject_author.refine_subject(object(), "cyber", instruction, tmp_path)

    assert instruction in client.calls[0][1]["content"]


def test_refine_subject_without_change_leaves_files_untouched(tmp_path, fake):
    directory = write_subject(tmp_path)
    original = (directory / "subject.yml").read_text(encoding="utf-8")
    fake(as_json(SPEC))

    assert subject_author.refine_subject(object(), "cyber", "rien à changer", tmp_path) == []

    assert (directory / "subject.yml").read_text(encoding="utf-8") == original
    assert not (directory / "subject.yml.bak").exists()


def test_refine_subject_requires_an_existing_valid_subject(tmp_path, fake):
    fake()
    with pytest.raises(SubjectError, match="introuvable"):
        subject_author.refine_subject(object(), "nope", "instruction", tmp_path)


def test_refine_subject_rejects_blank_instruction(tmp_path, fake):
    write_subject(tmp_path)
    client = fake()

    with pytest.raises(SubjectError, match="consigne"):
        subject_author.refine_subject(object(), "cyber", "  ", tmp_path)

    assert client.calls == []


def test_refine_subject_rejects_an_invalid_answer_and_keeps_the_file(tmp_path, fake):
    directory = write_subject(tmp_path)
    original = (directory / "subject.yml").read_text(encoding="utf-8")
    bad = as_json({**SPEC, "role": ""})
    fake(bad, bad, bad)

    with pytest.raises(ParsingError):
        subject_author.refine_subject(object(), "cyber", "instruction", tmp_path)

    assert (directory / "subject.yml").read_text(encoding="utf-8") == original


# --- propose_partie_criteria --------------------------------------------------


def make_manifest(output_dir, subject="cyber", parties=("Menaces", "Gouvernance")):
    toc = TocSchema(
        titre_manuel="M",
        parties=[
            Partie(
                numero="I" * (i + 1),
                titre=titre,
                chapitres=[
                    Chapitre(
                        numero=i + 1,
                        titre=f"Chapitre {i + 1}",
                        description="d",
                        sous_sections=[SousSection(numero=f"{i + 1}.1", titre="s")],
                    )
                ],
            )
            for i, titre in enumerate(parties)
        ],
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    save_state(output_dir, build_manual_state(toc, subject=subject))


def crit(id_, severity="recommande"):
    return {"id": id_, "description": f"Description de {id_}.", "severity": severity}


def test_propose_partie_criteria_adds_criteria_for_generated_parties(tmp_path, fake):
    write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("panorama_menaces")], "Gouvernance": [crit("role_comex", "bloquant")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    added = subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")

    assert added == {"Menaces": ["panorama_menaces"], "Gouvernance": ["role_comex"]}
    parties = subject.requirements()["parties"]
    assert parties["Menaces"][0]["id"] == "panorama_menaces"
    assert parties["Gouvernance"][0]["severity"] == "bloquant"


def test_propose_partie_criteria_sends_titles_and_existing_ids(tmp_path, fake):
    write_subject(tmp_path / "subjects", requirements={"generic": [crit("cas_incident")]})
    make_manifest(tmp_path / "out")
    client = fake(as_json({"parties": {}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")

    content = client.calls[0][1]["content"]
    assert "Menaces" in content and "Gouvernance" in content
    assert "cas_incident" in content and "definition_claire" in content
    assert "$" not in content


def test_propose_partie_criteria_preserves_existing_generic_criteria_and_backs_up(tmp_path, fake):
    directory = write_subject(tmp_path / "subjects", requirements={"generic": [crit("cas_incident")]})
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("panorama_menaces")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")

    assert (directory / "requirements.yml.bak").is_file()
    ids = [c["id"] for c in subject.requirements()["generic"]]
    assert "cas_incident" in ids


def test_propose_partie_criteria_skips_parties_that_already_have_criteria(tmp_path, fake):
    write_subject(tmp_path / "subjects", requirements={"parties": {"Menaces": [crit("deja_la")]}})
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("autre")], "Gouvernance": [crit("role_comex")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    added = subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")

    assert added == {"Gouvernance": ["role_comex"]}
    assert [c["id"] for c in subject.requirements()["parties"]["Menaces"]] == ["deja_la"]


def test_propose_partie_criteria_force_replaces_existing_criteria(tmp_path, fake):
    write_subject(tmp_path / "subjects", requirements={"parties": {"Menaces": [crit("deja_la")]}})
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("autre")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    added = subject_author.propose_partie_criteria(object(), subject, tmp_path / "out", force=True)

    assert added == {"Menaces": ["autre"]}
    assert [c["id"] for c in subject.requirements()["parties"]["Menaces"]] == ["autre"]


def test_propose_partie_criteria_requires_a_generated_toc(tmp_path, fake):
    write_subject(tmp_path / "subjects")
    subject = load_subject("cyber", tmp_path / "subjects")
    fake()

    with pytest.raises(SubjectError, match="manual init"):
        subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")


def test_propose_partie_criteria_refuses_a_manifest_of_another_subject(tmp_path, fake):
    write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out", subject="autre")
    subject = load_subject("cyber", tmp_path / "subjects")
    fake()

    with pytest.raises(SubjectError, match="autre"):
        subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")


def test_propose_partie_criteria_rejects_unknown_part_titles_and_writes_nothing(tmp_path, fake):
    directory = write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Partie inventée": [crit("x")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    with pytest.raises(SubjectError, match="Partie inventée"):
        subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")

    assert not (directory / "requirements.yml").exists()


def test_propose_partie_criteria_rejects_ids_clashing_with_existing_ones(tmp_path, fake):
    write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("definition_claire")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    with pytest.raises(SubjectError, match="definition_claire"):
        subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")


def test_propose_partie_criteria_rejects_duplicate_ids_within_the_answer(tmp_path, fake):
    write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {"Menaces": [crit("meme_id")], "Gouvernance": [crit("meme_id")]}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    with pytest.raises(SubjectError, match="meme_id"):
        subject_author.propose_partie_criteria(object(), subject, tmp_path / "out")


def test_propose_partie_criteria_with_nothing_to_add_leaves_files_untouched(tmp_path, fake):
    directory = write_subject(tmp_path / "subjects")
    make_manifest(tmp_path / "out")
    fake(as_json({"parties": {}}))
    subject = load_subject("cyber", tmp_path / "subjects")

    assert subject_author.propose_partie_criteria(object(), subject, tmp_path / "out") == {}

    assert not (directory / "requirements.yml").exists()


# --- client ---------------------------------------------------------------------


def test_client_uses_the_model_write_role():
    class Cfg:
        def role(self, name):
            self.asked = name
            from manual_cli.config import ModelSpec

            return ModelSpec(key="k", provider="ollama", name="n", base_url="http://x", api_key="k", timeout=1)

    cfg = Cfg()
    client = subject_author._client(cfg)

    assert cfg.asked == "model_write"
    assert client.role == "model_write"
