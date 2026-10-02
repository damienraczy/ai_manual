from __future__ import annotations

import io
from pathlib import Path

import pytest

from manual_cli import cli, tracing
from manual_cli.config import ConfigError
from manual_cli.schemas import Chapitre, Partie, TocSchema
from manual_cli.state import build_manual_state

SUBJECT_SPEC = """\
titre: Sujet de test
langue: français
role: Tu es un expert.
objectif: Écrire un manuel.
public: débutants
niveau: débutant
ton: clair
plan_directeur: a → b
"""


def add_subject(root, slug, spec=SUBJECT_SPEC):
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "subject.yml").write_text(spec, encoding="utf-8")
    return directory


@pytest.fixture(autouse=True)
def subjects_dir(tmp_path, monkeypatch):
    """Isole les tests du dossier `subjects/` réel et des sorties par défaut."""
    root = tmp_path / "_subjects"
    add_subject(root, "test-sujet")
    monkeypatch.setattr(cli, "SUBJECTS_DIR", root)
    monkeypatch.setattr(cli, "DEFAULT_OUTPUT_ROOT", tmp_path / "_output")
    return root


def make_manual_state():
    toc = TocSchema(
        titre_manuel="M",
        parties=[Partie(numero="I", titre="P", chapitres=[Chapitre(numero=1, titre="Un", description="d", sous_sections=[])])],
    )
    return build_manual_state(toc)


def test_cmd_init_skips_when_state_exists_without_force(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: True)
    called = {"generate_toc": False}
    monkeypatch.setattr(
        cli, "generate_toc", lambda cfg, out, subject: called.__setitem__("generate_toc", True) or make_manual_state()
    )

    rc = cli.main(["--output", str(tmp_path), "init"])

    assert rc == 1
    assert called["generate_toc"] is False
    assert "déjà" in capsys.readouterr().out


def test_cmd_init_generates_toc(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    state = make_manual_state()
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out, subject: state)

    rc = cli.main(["--output", str(tmp_path), "init"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "1 chapitres" in out


def test_cmd_init_force_regenerates_even_if_state_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: True)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    state = make_manual_state()
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out, subject: state)

    rc = cli.main(["--output", str(tmp_path), "init", "--force"])

    assert rc == 0


def test_cmd_write_reports_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    section = make_manual_state().sections[0]
    section.status = "done"
    section.attempts = 1
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "[OK]" in capsys.readouterr().out


def test_cmd_write_reports_section_needing_review(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    section = make_manual_state().sections[0]
    section.status = "failed"
    section.attempts = 3
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "A REVOIR" in capsys.readouterr().out


def test_cmd_write_no_pending_sections(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "Rien à rédiger" in capsys.readouterr().out


def test_cmd_write_passes_none_when_no_section_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, subject, only_numeros, max_rewrite, workers):
        received["only_numeros"] = only_numeros
        received["max_rewrite"] = max_rewrite
        received["workers"] = workers
        return []

    monkeypatch.setattr(cli, "run_write", fake_run_write)

    cli.main(["--output", str(tmp_path), "write"])

    assert received["only_numeros"] is None
    assert received["max_rewrite"] == 2
    assert received["workers"] == 4


def test_cmd_write_parses_enumeration_and_ranges_via_short_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, subject, only_numeros, max_rewrite, workers):
        received["only_numeros"] = only_numeros
        received["workers"] = workers
        return []

    monkeypatch.setattr(cli, "run_write", fake_run_write)

    cli.main(["--output", str(tmp_path), "write", "-s", "1", "3", "5-7", "-w", "8"])

    assert received["only_numeros"] == [1, 3, 5, 6, 7]
    assert received["workers"] == 8


def test_cmd_write_invalid_pattern_reports_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())

    rc = cli.main(["--output", str(tmp_path), "write", "-s", "abc"])

    assert rc == 1
    assert "Erreur" in capsys.readouterr().err


def test_cmd_status_no_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)

    rc = cli.main(["--output", str(tmp_path), "status"])

    assert rc == 1
    assert "Aucune table" in capsys.readouterr().out


def test_cmd_status_prints_progress(tmp_path, monkeypatch, capsys):
    state = make_manual_state()
    state.sections[0].status = "done"
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: True)
    monkeypatch.setattr(cli, "load_state", lambda output_dir: state)

    rc = cli.main(["--output", str(tmp_path), "status"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "1/1 sections" in out


def test_cmd_redo_reports_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    section = make_manual_state().sections[0]
    section.status = "failed"
    section.attempts = 3
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "redo", "1"])

    assert rc == 0
    assert "A REVOIR" in capsys.readouterr().out


def test_cmd_redo_passes_single_numero_and_one_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, subject, only_numeros, max_rewrite, workers):
        received["only_numeros"] = only_numeros
        received["workers"] = workers
        return []

    monkeypatch.setattr(cli, "run_write", fake_run_write)

    cli.main(["--output", str(tmp_path), "redo", "7"])

    assert received["only_numeros"] == [7]
    assert received["workers"] == 1


def test_cmd_publish_reports_generated_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    publish_dir = tmp_path / "publish" / "01_intro"
    monkeypatch.setattr(cli, "publish_section", lambda cfg, out, numero, system_prompt, generate_image: publish_dir)

    rc = cli.main(["--output", str(tmp_path), "publish", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert str(publish_dir) in out


def test_cmd_publish_forwards_no_image_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_publish_section(cfg, out, numero, system_prompt, generate_image):
        received["numero"] = numero
        received["system_prompt"] = system_prompt
        received["generate_image"] = generate_image
        return tmp_path / "publish" / "01_intro"

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    cli.main(["--output", str(tmp_path), "publish", "3", "--no-image"])

    assert received["numero"] == 3
    assert "Tu es un expert." in received["system_prompt"]
    assert received["generate_image"] is False


def test_cmd_publish_generates_image_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_publish_section(cfg, out, numero, system_prompt, generate_image):
        received["generate_image"] = generate_image
        return tmp_path / "publish" / "01_intro"

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    cli.main(["--output", str(tmp_path), "publish", "1"])

    assert received["generate_image"] is True


def test_cmd_publish_reports_not_done_section_as_error(tmp_path, monkeypatch, capsys):
    from manual_cli.publish import PublishError

    monkeypatch.setattr(cli, "load_config", lambda: object())

    def fake_publish_section(cfg, out, numero, system_prompt, generate_image):
        raise PublishError(f"La section {numero} n'est pas terminée (statut : 'pending').")

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    rc = cli.main(["--output", str(tmp_path), "publish", "2"])

    assert rc == 1
    assert "Erreur" in capsys.readouterr().err


def test_publish_parses_numero_and_no_image_flag():
    parser = cli.build_parser()
    args = parser.parse_args(["publish", "4", "--no-image"])
    assert args.numero == 4
    assert args.no_image is True
    assert args.func is cli.cmd_publish


def test_publish_default_includes_image():
    parser = cli.build_parser()
    args = parser.parse_args(["publish", "4"])
    assert args.no_image is False


def test_cmd_init_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out, subject: make_manual_state())

    cli.main(["--output", str(tmp_path), "init"])

    assert tracing.is_configured() is True


def test_cmd_write_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [])

    cli.main(["--output", str(tmp_path), "write"])

    assert tracing.is_configured() is True


def test_cmd_redo_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, subject, only_numeros, max_rewrite, workers: [])

    cli.main(["--output", str(tmp_path), "redo", "1"])

    assert tracing.is_configured() is True


def test_cmd_publish_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "publish_section", lambda cfg, out, numero, system_prompt, generate_image: tmp_path / "publish" / "x")

    cli.main(["--output", str(tmp_path), "publish", "1"])

    assert tracing.is_configured() is True


def test_traces_parses_default_host_and_port():
    parser = cli.build_parser()
    args = parser.parse_args(["traces"])
    assert args.host == "127.0.0.1"
    assert args.port == 8787
    assert args.func is cli.cmd_traces


def test_traces_parses_custom_host_and_port():
    parser = cli.build_parser()
    args = parser.parse_args(["traces", "--host", "0.0.0.0", "--port", "9000"])
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_cmd_traces_reports_missing_flask(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "create_app", None)

    rc = cli.main(["--output", str(tmp_path), "traces"])

    assert rc == 1
    assert "flask" in capsys.readouterr().err.lower()


def test_cmd_traces_starts_app_with_trace_path(tmp_path, monkeypatch, capsys):
    received = {}

    class FakeApp:
        def run(self, *, host, port):
            received["host"] = host
            received["port"] = port

    def fake_create_app(trace_path):
        received["trace_path"] = trace_path
        return FakeApp()

    monkeypatch.setattr(cli, "create_app", fake_create_app)

    rc = cli.main(["--output", str(tmp_path), "traces", "--host", "0.0.0.0", "--port", "9000"])

    assert rc == 0
    assert received["trace_path"] == tmp_path / "traces" / "calls.jsonl"
    assert received["host"] == "0.0.0.0"
    assert received["port"] == 9000
    assert "9000" in capsys.readouterr().out


def test_main_catches_known_errors(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)
    monkeypatch.setattr(cli, "load_config", lambda: (_ for _ in ()).throw(ConfigError("boom")))

    rc = cli.main(["--output", str(tmp_path), "init"])

    assert rc == 1
    assert "Erreur : boom" in capsys.readouterr().err


def test_build_parser_requires_command():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_write_parses_section_and_max_rewrite():
    parser = cli.build_parser()
    args = parser.parse_args(["write", "--section", "5", "--max-rewrite", "1"])
    assert args.section == ["5"]
    assert args.max_rewrite == 1
    assert args.func is cli.cmd_write


def test_write_parses_short_section_flag_with_multiple_tokens():
    parser = cli.build_parser()
    args = parser.parse_args(["write", "-s", "1", "3", "5-8"])
    assert args.section == ["1", "3", "5-8"]


def test_write_default_worker_count_is_four():
    parser = cli.build_parser()
    args = parser.parse_args(["write"])
    assert args.worker == 4
    assert args.section is None


def test_write_parses_short_worker_flag():
    parser = cli.build_parser()
    args = parser.parse_args(["write", "-w", "8"])
    assert args.worker == 8


def test_redo_parses_numero_positional():
    parser = cli.build_parser()
    args = parser.parse_args(["redo", "3"])
    assert args.numero == 3
    assert args.func is cli.cmd_redo


# --- sujets ---------------------------------------------------------------------


def test_init_passes_the_loaded_subject_to_generate_toc(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_generate_toc(cfg, out, subject):
        received["subject"] = subject
        return make_manual_state()

    monkeypatch.setattr(cli, "generate_toc", fake_generate_toc)

    rc = cli.main(["--output", str(tmp_path / "out"), "init"])

    assert rc == 0
    assert received["subject"].slug == "test-sujet"
    assert received["subject"].titre == "Sujet de test"


def test_write_passes_the_loaded_subject_to_run_write(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, subject, only_numeros, max_rewrite, workers):
        received["slug"] = subject.slug
        return []

    monkeypatch.setattr(cli, "run_write", fake_run_write)

    cli.main(["--output", str(tmp_path), "write"])

    assert received["slug"] == "test-sujet"


def test_default_output_directory_depends_on_the_subject(tmp_path, subjects_dir, monkeypatch):
    add_subject(subjects_dir, "autre")
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_generate_toc(cfg, out, subject):
        received["out"] = out
        return make_manual_state()

    monkeypatch.setattr(cli, "generate_toc", fake_generate_toc)
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)

    cli.main(["--subject", "autre", "init"])

    assert received["out"] == tmp_path / "_output" / "autre"


def test_explicit_output_overrides_the_subject_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_generate_toc(cfg, out, subject):
        received["out"] = out
        return make_manual_state()

    monkeypatch.setattr(cli, "generate_toc", fake_generate_toc)

    cli.main(["--output", str(tmp_path / "ailleurs"), "init"])

    assert received["out"] == tmp_path / "ailleurs"


def test_unknown_subject_is_reported_as_error(capsys):
    rc = cli.main(["--subject", "nope", "init"])

    assert rc == 1
    assert "Sujet inconnu" in capsys.readouterr().err


def test_several_subjects_require_an_explicit_choice(subjects_dir, capsys):
    add_subject(subjects_dir, "autre")

    rc = cli.main(["init"])

    assert rc == 1
    assert "--subject" in capsys.readouterr().err


def test_status_uses_the_default_directory_of_the_only_subject(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_state_exists(output_dir):
        seen["out"] = output_dir
        return False

    monkeypatch.setattr(cli, "state_exists", fake_state_exists)

    rc = cli.main(["status"])

    assert rc == 1
    assert seen["out"] == tmp_path / "_output" / "test-sujet"


def test_status_with_explicit_output_does_not_need_a_subject(tmp_path, subjects_dir, monkeypatch):
    add_subject(subjects_dir, "autre")
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)

    assert cli.main(["--output", str(tmp_path), "status"]) == 1


def test_publish_and_traces_use_the_subject_default_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    seen = {}

    def fake_publish_section(cfg, out, numero, system_prompt, generate_image):
        seen["publish"] = out
        return out / "publish" / "x"

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    class FakeApp:
        def run(self, *, host, port):
            pass

    monkeypatch.setattr(cli, "create_app", lambda trace_path: seen.__setitem__("traces", trace_path) or FakeApp())

    cli.main(["publish", "1"])
    cli.main(["traces"])

    expected = tmp_path / "_output" / "test-sujet"
    assert seen["publish"] == expected
    assert seen["traces"] == expected / "traces" / "calls.jsonl"


def test_subject_list_shows_titles_and_flags_invalid_subjects(subjects_dir, capsys):
    add_subject(subjects_dir, "casse", spec="titre: seulement un titre\n")

    rc = cli.main(["subject", "list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "test-sujet" in out and "Sujet de test" in out
    assert "casse" in out and "INVALIDE" in out


def test_subject_list_without_subjects(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SUBJECTS_DIR", tmp_path / "vide")

    rc = cli.main(["subject", "list"])

    assert rc == 0
    assert "Aucun sujet" in capsys.readouterr().out


def test_subject_new_creates_a_skeleton_and_explains_next_steps(subjects_dir, capsys):
    rc = cli.main(["subject", "new", "cyber"])

    assert rc == 0
    assert (subjects_dir / "cyber" / "subject.yml").is_file()
    out = capsys.readouterr().out
    assert "subject.yml" in out
    assert "manual subject check cyber" in out


def test_subject_new_rejects_existing_subject(capsys):
    rc = cli.main(["subject", "new", "test-sujet"])

    assert rc == 1
    assert "existe déjà" in capsys.readouterr().err


def test_subject_check_summarises_a_valid_subject(capsys):
    rc = cli.main(["subject", "check", "test-sujet"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "test-sujet" in out
    assert "critères" in out
    assert "SYSTEM" not in out


def test_subject_check_defaults_to_the_only_subject(capsys):
    assert cli.main(["subject", "check"]) == 0


def test_subject_check_show_prints_the_rendered_prompts(capsys):
    rc = cli.main(["subject", "check", "test-sujet", "--show"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "Prompt système" in out
    assert "Tu es un expert." in out
    assert "Instruction de plan" in out
    assert "a → b" in out


def test_subject_check_reports_an_incomplete_subject(subjects_dir, capsys):
    scaffold = subjects_dir / "brouillon"
    scaffold.mkdir()
    (scaffold / "subject.yml").write_text(SUBJECT_SPEC.replace("clair", "À COMPLÉTER"), encoding="utf-8")

    rc = cli.main(["subject", "check", "brouillon"])

    assert rc == 1
    assert "À COMPLÉTER" in capsys.readouterr().err


def test_subject_delete_removes_the_subject_when_confirmed(subjects_dir, monkeypatch, capsys):
    add_subject(subjects_dir, "autre")
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "o")

    rc = cli.main(["subject", "delete", "test-sujet"])

    assert rc == 0
    assert not (subjects_dir / "test-sujet").exists()
    assert (subjects_dir / "autre").is_dir()
    assert "test-sujet" in asked[0]
    assert "supprimé" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["", "n", "non", "peut-être"])
def test_subject_delete_is_cancelled_unless_confirmed(subjects_dir, monkeypatch, capsys, answer):
    monkeypatch.setattr("builtins.input", lambda prompt="": answer)

    rc = cli.main(["subject", "delete", "test-sujet"])

    assert rc == 1
    assert (subjects_dir / "test-sujet" / "subject.yml").is_file()
    assert "annulée" in capsys.readouterr().err


def test_subject_delete_is_cancelled_without_a_terminal(subjects_dir, monkeypatch, capsys):
    def no_stdin(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_stdin)

    rc = cli.main(["subject", "delete", "test-sujet"])

    assert rc == 1
    assert (subjects_dir / "test-sujet").is_dir()
    assert "--yes" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["-y", "--yes"])
def test_subject_delete_skips_the_prompt_with_yes(subjects_dir, monkeypatch, flag):
    def forbidden(prompt=""):
        raise AssertionError("aucune confirmation attendue")

    monkeypatch.setattr("builtins.input", forbidden)

    assert cli.main(["subject", "delete", "test-sujet", flag]) == 0
    assert not (subjects_dir / "test-sujet").exists()


def test_subject_delete_requires_a_slug_even_with_a_single_subject(subjects_dir):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["subject", "delete"])


def test_subject_delete_does_not_take_a_slug_from_flags(subjects_dir):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["subject", "delete", "-y"])


def test_subject_delete_reports_an_unknown_subject(subjects_dir, capsys):
    rc = cli.main(["subject", "delete", "fantome", "-y"])

    assert rc == 1
    assert "Sujet inconnu" in capsys.readouterr().err
    assert (subjects_dir / "test-sujet").is_dir()


def test_subject_delete_keeps_the_generated_manual_by_default(tmp_path, subjects_dir, capsys):
    output = tmp_path / "_output" / "test-sujet"
    output.mkdir(parents=True)
    (output / "00_toc.md").write_text("plan", encoding="utf-8")

    rc = cli.main(["subject", "delete", "test-sujet", "-y"])

    assert rc == 0
    assert (output / "00_toc.md").is_file()
    assert "--with-output" in capsys.readouterr().out


def test_subject_delete_with_output_removes_the_generated_manual(tmp_path, subjects_dir, capsys):
    output = tmp_path / "_output" / "test-sujet"
    output.mkdir(parents=True)
    (output / "00_toc.md").write_text("plan", encoding="utf-8")
    other = tmp_path / "_output" / "autre"
    other.mkdir()

    rc = cli.main(["subject", "delete", "test-sujet", "-y", "--with-output"])

    assert rc == 0
    assert not output.exists()
    assert other.is_dir()
    assert "Manuel généré supprimé" in capsys.readouterr().out


def test_subject_delete_with_output_tolerates_a_missing_manual(subjects_dir):
    assert cli.main(["subject", "delete", "test-sujet", "-y", "--with-output"]) == 0


def test_subject_delete_prompt_mentions_the_manual_when_it_will_be_removed(tmp_path, subjects_dir, monkeypatch):
    (tmp_path / "_output" / "test-sujet").mkdir(parents=True)
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or "n")

    cli.main(["subject", "delete", "test-sujet", "--with-output"])

    assert "manuel généré" in asked[0]


def test_subject_delete_refuses_an_explicit_output_option(tmp_path, subjects_dir, capsys):
    rc = cli.main(["--output", str(tmp_path / "ailleurs"), "subject", "delete", "test-sujet", "-y", "--with-output"])

    assert rc == 1
    assert "--output" in capsys.readouterr().err
    assert (subjects_dir / "test-sujet").is_dir()


def test_subject_requires_an_action():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["subject"])



# --- rédaction assistée ---------------------------------------------------------


def test_subject_new_with_brief_calls_the_llm_author(subjects_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    received = {}

    def fake_generate(cfg, slug, brief, dir_):
        received.update(cfg=cfg, slug=slug, brief=brief, dir=dir_)
        return dir_ / slug

    monkeypatch.setattr(cli, "generate_subject", fake_generate)

    rc = cli.main(["subject", "new", "cyber", "Manuel de cybersécurité"])

    assert rc == 0
    assert received == {"cfg": "cfg", "slug": "cyber", "brief": "Manuel de cybersécurité", "dir": subjects_dir}
    out = capsys.readouterr().out
    assert "manual subject check cyber --show" in out
    assert "manual subject refine cyber" in out


def test_subject_new_without_brief_does_not_call_the_llm(monkeypatch):
    monkeypatch.setattr(cli, "generate_subject", lambda *a, **k: pytest.fail("LLM appelé sans brief"))

    assert cli.main(["subject", "new", "vide"]) == 0


def test_subject_refine_reports_changed_fields(subjects_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    received = {}

    def fake_refine(cfg, slug, instruction, dir_):
        received.update(slug=slug, instruction=instruction, dir=dir_)
        return ["ton", "exclusions"]

    monkeypatch.setattr(cli, "refine_subject", fake_refine)

    rc = cli.main(["subject", "refine", "test-sujet", "plus décontracté"])

    assert rc == 0
    assert received == {"slug": "test-sujet", "instruction": "plus décontracté", "dir": subjects_dir}
    out = capsys.readouterr().out
    assert "ton, exclusions" in out
    assert "subject.yml.bak" in out


def test_subject_refine_reports_no_change(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    monkeypatch.setattr(cli, "refine_subject", lambda cfg, slug, instruction, dir_: [])

    rc = cli.main(["subject", "refine", "test-sujet", "rien"])

    assert rc == 0
    assert "Aucun changement" in capsys.readouterr().out


def test_subject_criteria_proposes_criteria_for_the_toc_parties(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    received = {}

    def fake_propose(cfg, subject, output_dir, force):
        received.update(slug=subject.slug, out=output_dir, force=force)
        return {"Menaces": ["panorama"], "Gouvernance": ["role_comex"]}

    monkeypatch.setattr(cli, "propose_partie_criteria", fake_propose)

    rc = cli.main(["subject", "criteria"])

    assert rc == 0
    assert received == {"slug": "test-sujet", "out": tmp_path / "_output" / "test-sujet", "force": False}
    out = capsys.readouterr().out
    assert "Menaces" in out and "panorama" in out
    assert tracing.is_configured() is True


def test_subject_criteria_forwards_force_and_explicit_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    received = {}

    def fake_propose(cfg, subject, output_dir, force):
        received.update(out=output_dir, force=force)
        return {}

    monkeypatch.setattr(cli, "propose_partie_criteria", fake_propose)

    rc = cli.main(["--output", str(tmp_path / "ailleurs"), "subject", "criteria", "test-sujet", "--force"])

    assert rc == 0
    assert received == {"out": tmp_path / "ailleurs", "force": True}
    assert "Aucun critère ajouté" in capsys.readouterr().out


def test_subject_edit_opens_the_editor_then_checks_the_subject(subjects_dir, monkeypatch, capsys):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "monediteur --wait")
    ran = {}

    def fake_run(command, check):
        ran["command"] = command
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["subject", "edit", "test-sujet"])

    assert rc == 0
    assert ran["command"] == ["monediteur", "--wait", str(subjects_dir / "test-sujet" / "subject.yml")]
    assert "valide" in capsys.readouterr().out


def test_subject_edit_prefers_visual_over_editor(monkeypatch):
    monkeypatch.setenv("VISUAL", "visuel")
    monkeypatch.setenv("EDITOR", "editeur")
    ran = {}

    def fake_run(command, check):
        ran["command"] = command
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli.main(["subject", "edit"])

    assert ran["command"][0] == "visuel"


def test_subject_edit_requires_an_editor(monkeypatch, capsys):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)

    rc = cli.main(["subject", "edit", "test-sujet"])

    assert rc == 1
    assert "EDITOR" in capsys.readouterr().err


def test_subject_edit_reports_editor_failure(monkeypatch, capsys):
    monkeypatch.setenv("EDITOR", "editeur")
    monkeypatch.setattr(cli.subprocess, "run", lambda command, check: type("R", (), {"returncode": 3})())

    rc = cli.main(["subject", "edit", "test-sujet"])

    assert rc == 1
    assert "code 3" in capsys.readouterr().err


def test_subject_edit_reports_a_subject_left_incomplete(subjects_dir, monkeypatch, capsys):
    monkeypatch.setenv("EDITOR", "editeur")

    def fake_run(command, check):
        (subjects_dir / "test-sujet" / "subject.yml").write_text("titre: seul\n", encoding="utf-8")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["subject", "edit", "test-sujet"])

    assert rc == 1
    assert "invalide" in capsys.readouterr().err


def test_subject_edit_reports_a_missing_editor_program(monkeypatch, capsys):
    monkeypatch.setenv("EDITOR", "editeur-inexistant")

    def fake_run(command, check):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    rc = cli.main(["subject", "edit", "test-sujet"])

    assert rc == 1
    assert "introuvable" in capsys.readouterr().err


# --- descriptif / consigne lus dans un fichier -------------------------------------


LONG_BRIEF = "Manuel de cybersécurité.\n\nPublic : COMEX.\nInsister sur les cas réels d'incidents.\n"


def capture_generate(monkeypatch):
    received = {}

    def fake_generate(cfg, slug, brief, dir_):
        received["brief"] = brief
        return dir_ / slug

    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    monkeypatch.setattr(cli, "generate_subject", fake_generate)
    return received


@pytest.mark.parametrize("flag", ["--brief-file", "-f"])
def test_subject_new_reads_a_long_brief_from_a_file(tmp_path, monkeypatch, flag):
    received = capture_generate(monkeypatch)
    brief_file = tmp_path / "brief.txt"
    brief_file.write_text(LONG_BRIEF, encoding="utf-8")

    rc = cli.main(["subject", "new", "cyber", flag, str(brief_file)])

    assert rc == 0
    assert received["brief"] == LONG_BRIEF


def test_subject_new_reads_the_brief_from_stdin_with_a_dash(monkeypatch):
    received = capture_generate(monkeypatch)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(LONG_BRIEF))

    rc = cli.main(["subject", "new", "cyber", "-f", "-"])

    assert rc == 0
    assert received["brief"] == LONG_BRIEF


def test_subject_new_refuses_inline_brief_and_file_together(tmp_path, monkeypatch, capsys):
    capture_generate(monkeypatch)
    brief_file = tmp_path / "brief.txt"
    brief_file.write_text("x", encoding="utf-8")

    rc = cli.main(["subject", "new", "cyber", "brief en ligne", "-f", str(brief_file)])

    assert rc == 1
    assert "pas les deux" in capsys.readouterr().err


def test_subject_new_reports_an_unreadable_brief_file(tmp_path, monkeypatch, capsys):
    capture_generate(monkeypatch)

    rc = cli.main(["subject", "new", "cyber", "-f", str(tmp_path / "absent.txt")])

    assert rc == 1
    assert "absent.txt" in capsys.readouterr().err


def test_subject_new_reports_a_brief_file_that_is_not_utf8(tmp_path, monkeypatch, capsys):
    capture_generate(monkeypatch)
    brief_file = tmp_path / "brief.txt"
    brief_file.write_bytes(b"caf\xe9")

    rc = cli.main(["subject", "new", "cyber", "-f", str(brief_file)])

    assert rc == 1
    assert "brief.txt" in capsys.readouterr().err


def test_subject_refine_reads_a_long_instruction_from_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    received = {}

    def fake_refine(cfg, slug, instruction, dir_):
        received["instruction"] = instruction
        return []

    monkeypatch.setattr(cli, "refine_subject", fake_refine)
    instruction_file = tmp_path / "consigne.txt"
    instruction_file.write_text(LONG_BRIEF, encoding="utf-8")

    rc = cli.main(["subject", "refine", "test-sujet", "-f", str(instruction_file)])

    assert rc == 0
    assert received["instruction"] == LONG_BRIEF


def test_subject_refine_requires_an_instruction(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")

    rc = cli.main(["subject", "refine", "test-sujet"])

    assert rc == 1
    assert "consigne" in capsys.readouterr().err


def test_subject_refine_refuses_inline_instruction_and_file_together(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    f = tmp_path / "c.txt"
    f.write_text("x", encoding="utf-8")

    rc = cli.main(["subject", "refine", "test-sujet", "en ligne", "-f", str(f)])

    assert rc == 1
    assert "pas les deux" in capsys.readouterr().err


# --- improve ---------------------------------------------------------------------


def make_improve_result(accepted=True, tmp=None):
    from manual_cli.generator import ImproveResult

    section = make_manual_state().sections[0]
    base = (tmp or Path("/x")) / section.filename
    if accepted:
        return ImproveResult(section=section, accepted=True, path=base, backup=Path(str(base) + ".bak"))
    return ImproveResult(section=section, accepted=False, path=base.with_name("01_un.candidate.md"), backup=None)


def capture_improve(monkeypatch, results):
    received = {}

    def fake_run_improve(cfg, out, subject, only_numeros, instruction, max_rewrite, workers):
        received.update(
            slug=subject.slug, out=out, only_numeros=only_numeros, instruction=instruction,
            max_rewrite=max_rewrite, workers=workers,
        )
        return results

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_improve", fake_run_improve)
    return received


def test_improve_selects_sections_with_defaults(tmp_path, monkeypatch, capsys):
    received = capture_improve(monkeypatch, [make_improve_result(tmp=tmp_path)])

    rc = cli.main(["--output", str(tmp_path), "improve", "1", "3-4"])

    assert rc == 0
    assert received == {
        "slug": "test-sujet", "out": tmp_path, "only_numeros": [1, 3, 4],
        "instruction": None, "max_rewrite": 2, "workers": 4,
    }
    out = capsys.readouterr().out
    assert "[OK]" in out and ".bak" in out
    assert tracing.is_configured() is True


def test_improve_forwards_inline_instruction_and_options(tmp_path, monkeypatch):
    received = capture_improve(monkeypatch, [])

    cli.main(["--output", str(tmp_path), "improve", "2", "-i", "Plus d'exemples chiffrés", "--max-rewrite", "3", "-w", "2"])

    assert received["instruction"] == "Plus d'exemples chiffrés"
    assert received["max_rewrite"] == 3
    assert received["workers"] == 2


def test_improve_reads_the_instruction_from_a_file(tmp_path, monkeypatch):
    received = capture_improve(monkeypatch, [])
    instruction_file = tmp_path / "consigne.txt"
    instruction_file.write_text(LONG_BRIEF, encoding="utf-8")

    cli.main(["--output", str(tmp_path), "improve", "1", "-f", str(instruction_file)])

    assert received["instruction"] == LONG_BRIEF


def test_improve_refuses_inline_instruction_and_file_together(tmp_path, monkeypatch, capsys):
    capture_improve(monkeypatch, [])
    f = tmp_path / "c.txt"
    f.write_text("x", encoding="utf-8")

    rc = cli.main(["--output", str(tmp_path), "improve", "1", "-i", "a", "-f", str(f)])

    assert rc == 1
    assert "pas les deux" in capsys.readouterr().err


def test_improve_reports_a_version_that_was_not_retained(tmp_path, monkeypatch, capsys):
    capture_improve(monkeypatch, [make_improve_result(accepted=False, tmp=tmp_path)])

    rc = cli.main(["--output", str(tmp_path), "improve", "1"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "NON RETENU" in out
    assert "candidate" in out and "conservé" in out


def test_improve_reports_an_invalid_section_pattern(tmp_path, monkeypatch, capsys):
    capture_improve(monkeypatch, [])

    rc = cli.main(["--output", str(tmp_path), "improve", "abc"])

    assert rc == 1
    assert "Erreur" in capsys.readouterr().err


def test_improve_requires_at_least_one_section():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["improve"])


# --- improve-toc -------------------------------------------------------------------


def make_toc_result(modified=True, tmp=None):
    from manual_cli.generator import TocImproveResult

    state = make_manual_state()
    if not modified:
        return TocImproveResult(state, False, [], [], [], [], None)
    return TocImproveResult(
        state=state,
        modified=True,
        changed=state.sections,
        removed=state.sections,
        orphan_files=["03_trois.md"],
        orphan_criteria=["Bases"],
        history_dir=(tmp or Path("/x")) / "toc_history" / "20260924-120000",
    )


def capture_improve_toc(monkeypatch, result):
    received = {}

    def fake_improve_toc(cfg, out, subject, instruction):
        received.update(slug=subject.slug, out=out, instruction=instruction)
        return result

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "improve_toc", fake_improve_toc)
    return received


def test_improve_toc_defaults_and_summary(tmp_path, monkeypatch, capsys):
    received = capture_improve_toc(monkeypatch, make_toc_result(tmp=tmp_path))

    rc = cli.main(["--output", str(tmp_path), "improve-toc"])

    assert rc == 0
    assert received == {"slug": "test-sujet", "out": tmp_path, "instruction": None}
    out = capsys.readouterr().out
    assert "toc_history" in out
    assert "1. Un" in out
    assert "03_trois.md" in out
    assert "Bases" in out and "manual subject criteria" in out
    assert tracing.is_configured() is True


def test_improve_toc_forwards_inline_instruction(tmp_path, monkeypatch):
    received = capture_improve_toc(monkeypatch, make_toc_result(tmp=tmp_path))

    cli.main(["--output", str(tmp_path), "improve-toc", "-i", "Ajoute un chapitre sur l'éthique"])

    assert received["instruction"] == "Ajoute un chapitre sur l'éthique"


def test_improve_toc_reads_instruction_from_file(tmp_path, monkeypatch):
    received = capture_improve_toc(monkeypatch, make_toc_result(tmp=tmp_path))
    f = tmp_path / "consigne.txt"
    f.write_text(LONG_BRIEF, encoding="utf-8")

    cli.main(["--output", str(tmp_path), "improve-toc", "-f", str(f)])

    assert received["instruction"] == LONG_BRIEF


def test_improve_toc_refuses_inline_instruction_and_file_together(tmp_path, monkeypatch, capsys):
    capture_improve_toc(monkeypatch, make_toc_result(tmp=tmp_path))
    f = tmp_path / "c.txt"
    f.write_text("x", encoding="utf-8")

    rc = cli.main(["--output", str(tmp_path), "improve-toc", "-i", "a", "-f", str(f)])

    assert rc == 1
    assert "pas les deux" in capsys.readouterr().err


def test_improve_toc_reports_no_change(tmp_path, monkeypatch, capsys):
    capture_improve_toc(monkeypatch, make_toc_result(modified=False))

    rc = cli.main(["--output", str(tmp_path), "improve-toc"])

    assert rc == 0
    assert "Aucun changement" in capsys.readouterr().out


def test_improve_toc_summary_omits_empty_sections(tmp_path, monkeypatch, capsys):
    from manual_cli.generator import TocImproveResult

    state = make_manual_state()
    result = TocImproveResult(state, True, [], [], [], [], tmp_path / "toc_history" / "x")
    capture_improve_toc(monkeypatch, result)

    rc = cli.main(["--output", str(tmp_path), "improve-toc"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "toc_history" in out
    assert "Fichiers de chapitres" not in out
    assert "Critères" not in out


# --- glossary ----------------------------------------------------------------------


def test_glossary_command_reports_the_written_file(tmp_path, monkeypatch, capsys):
    from manual_cli.glossary import GlossaryResult

    received = {}

    def fake_build(cfg, out, system_prompt):
        received["out"] = out
        received["system_prompt"] = system_prompt
        return GlossaryResult(path=out / "glossaire.md", entries=[object(), object()], chapters=[1, 2])

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "build_glossary", fake_build)

    rc = cli.main(["--output", str(tmp_path), "glossary"])

    assert rc == 0
    assert received["out"] == tmp_path
    assert "Tu es un expert." in received["system_prompt"]
    out = capsys.readouterr().out
    assert "2 termes" in out and "glossaire.md" in out


# --- sources ------------------------------------------------------------------------


def test_sources_add_copies_files_into_the_subject(subjects_dir, tmp_path, capsys):
    doc = tmp_path / "biblio.md"
    doc.write_text("contenu", encoding="utf-8")

    rc = cli.main(["sources", "add", str(doc)])

    assert rc == 0
    assert (subjects_dir / "test-sujet" / "sources" / "biblio.md").read_text(encoding="utf-8") == "contenu"
    assert "biblio.md" in capsys.readouterr().out


def test_sources_add_refuses_a_missing_file_and_a_bad_extension(subjects_dir, tmp_path, capsys):
    pdf = tmp_path / "x.pdf"
    pdf.write_text("x", encoding="utf-8")

    assert cli.main(["sources", "add", str(tmp_path / "absent.md")]) == 1
    assert cli.main(["sources", "add", str(pdf)]) == 1
    assert ".md" in capsys.readouterr().err


def test_sources_add_does_not_overwrite_without_force(subjects_dir, tmp_path, capsys):
    doc = tmp_path / "a.md"
    doc.write_text("un", encoding="utf-8")
    cli.main(["sources", "add", str(doc)])
    doc.write_text("deux", encoding="utf-8")

    assert cli.main(["sources", "add", str(doc)]) == 1
    assert (subjects_dir / "test-sujet" / "sources" / "a.md").read_text(encoding="utf-8") == "un"
    assert cli.main(["sources", "add", "--force", str(doc)]) == 0
    assert (subjects_dir / "test-sujet" / "sources" / "a.md").read_text(encoding="utf-8") == "deux"


def test_sources_list_without_documents(capsys):
    rc = cli.main(["sources", "list"])

    assert rc == 0
    assert "Aucun document" in capsys.readouterr().out


def test_sources_list_shows_files_with_unit_counts_when_extracted(subjects_dir, tmp_path, capsys):
    from manual_cli import sources as src

    directory = subjects_dir / "test-sujet" / "sources"
    directory.mkdir()
    (directory / "a.md").write_text("alpha", encoding="utf-8")
    (directory / "b.md").write_text("beta", encoding="utf-8")
    index = src.SourceIndex(
        fichiers={
            "a.md": src.FileEntry(
                hash="h",
                unites=[
                    src.Unite(id="a.md#1", source="a.md", ligne=1, type="idee", enonce="E", extrait="alpha", utilite="haute"),
                    src.Unite(id="a.md#2", source="a.md", ligne=1, type="fait", enonce="F", extrait="alpha", utilite="nulle"),
                ],
            )
        }
    )
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "sources_index.json").write_text(index.model_dump_json(), encoding="utf-8")

    rc = cli.main(["--output", str(tmp_path / "out"), "sources", "list"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "a.md" in out and "2 unité(s) dont 1 utile(s)" in out
    assert "b.md" in out and "non analysé" in out


def test_sources_extract_reports_what_was_done(subjects_dir, tmp_path, monkeypatch, capsys):
    from manual_cli.sources import RefreshReport

    seen = {}

    def fake_refresh(cfg, subject_dir, out, contexte=""):
        seen.update(subject_dir=subject_dir, out=out, contexte=contexte)
        return RefreshReport(extracted=["a.md"], cached=["b.md"], removed=["c.md"], consolidated=True)

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "refresh_index", fake_refresh)

    rc = cli.main(["--output", str(tmp_path / "out"), "sources", "extract"])

    out = capsys.readouterr().out
    assert rc == 0
    assert seen["subject_dir"] == subjects_dir / "test-sujet" and seen["out"] == tmp_path / "out"
    assert "Sujet de test" in seen["contexte"]
    assert "1 analysé(s)" in out and "1 en cache" in out and "1 retiré(s)" in out


def _write_index(out, units):
    from manual_cli import sources as src

    out.mkdir(parents=True, exist_ok=True)
    by_file = {}
    for u in units:
        by_file.setdefault(u.source, []).append(u)
    index = src.SourceIndex(fichiers={n: src.FileEntry(hash="h", unites=us) for n, us in by_file.items()})
    (out / "sources_index.json").write_text(index.model_dump_json(), encoding="utf-8")


def _unit(n, **extra):
    from manual_cli import sources as src

    fields = dict(id=f"a.md#{n}", source="a.md", ligne=n, type="idee", enonce=f"énoncé {n}", extrait=f"x{n}", utilite="haute")
    return src.Unite(**{**fields, **extra})


def test_sources_assign_runs_the_assignment_and_reports(tmp_path, monkeypatch, capsys):
    from manual_cli.sources_assign import AssignReport

    out = tmp_path / "out"
    _write_index(out, [_unit(1)])
    seen = {}

    def fake_assign(cfg, state, index, output_dir, *, force=False):
        seen.update(force=force, units=[u.id for u in index.units()])
        return AssignReport(assigned=1, pruned=0, orphans=["a.md#9"])

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "load_state", lambda o: make_manual_state())
    monkeypatch.setattr(cli, "state_exists", lambda o: True)
    monkeypatch.setattr(cli, "ensure_assignment", fake_assign)

    rc = cli.main(["--output", str(out), "sources", "assign", "--force"])

    assert rc == 0 and seen == {"force": True, "units": ["a.md#1"]}
    text = capsys.readouterr().out
    assert "1 unité(s) affectée(s)" in text and "1 orpheline(s)" in text


def test_sources_assign_requires_an_analysis_and_a_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda o: False)
    assert cli.main(["--output", str(tmp_path / "o1"), "sources", "assign"]) == 1
    assert "manual init" in capsys.readouterr().err

    monkeypatch.setattr(cli, "state_exists", lambda o: True)
    assert cli.main(["--output", str(tmp_path / "o2"), "sources", "assign"]) == 1
    assert "sources extract" in capsys.readouterr().err


def test_sources_show_prints_what_a_chapter_will_receive(tmp_path, monkeypatch, capsys):
    from manual_cli import sources_assign as sa

    out = tmp_path / "out"
    _write_index(out, [_unit(1, enonce="matière du un")])
    sa.save_map(out, sa.SourcesMap(chapitres={"Un": sa.ChapterUnits(principal=["a.md#1"])}))
    save = __import__("manual_cli.state", fromlist=["save_state"]).save_state
    save(out, make_manual_state())
    monkeypatch.setattr(cli, "load_config", lambda: __import__("manual_cli.config", fromlist=["AppConfig"]).AppConfig(settings={"sources": {"max_prompt_chars": 5000}}))

    rc = cli.main(["--output", str(out), "sources", "show", "1"])

    assert rc == 0
    assert "matière du un" in capsys.readouterr().out


def test_sources_show_says_when_a_chapter_has_no_matter(tmp_path, monkeypatch, capsys):
    from manual_cli.config import AppConfig
    from manual_cli.state import save_state

    out = tmp_path / "out"
    _write_index(out, [_unit(1)])
    save_state(out, make_manual_state())
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(settings={"sources": {"max_prompt_chars": 5000}}))

    rc = cli.main(["--output", str(out), "sources", "show", "1"])

    assert rc == 0 and "Aucune matière" in capsys.readouterr().out


def test_sources_show_reports_omitted_units(tmp_path, monkeypatch, capsys):
    from manual_cli import sources_assign as sa
    from manual_cli.config import AppConfig
    from manual_cli.state import save_state

    out = tmp_path / "out"
    _write_index(out, [_unit(1), _unit(2)])
    sa.save_map(out, sa.SourcesMap(chapitres={"Un": sa.ChapterUnits(principal=["a.md#1", "a.md#2"])}))
    save_state(out, make_manual_state())
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(settings={"sources": {"max_prompt_chars": 10}}))

    cli.main(["--output", str(out), "sources", "show", "1"])

    assert "omise(s) faute de place" in capsys.readouterr().out


def test_sources_orphans_lists_useful_units_without_a_chapter(tmp_path, capsys):
    from manual_cli import sources_assign as sa

    out = tmp_path / "out"
    _write_index(out, [_unit(1), _unit(2)])
    sa.save_map(out, sa.SourcesMap(chapitres={"Un": sa.ChapterUnits(principal=["a.md#1"])}, orphelines=["a.md#2"]))

    rc = cli.main(["--output", str(out), "sources", "orphans"])

    text = capsys.readouterr().out
    assert rc == 0 and "a.md#2" in text and "a.md#1" not in text


def test_sources_orphans_when_there_are_none(tmp_path, capsys):
    from manual_cli import sources_assign as sa

    out = tmp_path / "out"
    _write_index(out, [_unit(1)])
    sa.save_map(out, sa.SourcesMap(chapitres={"Un": sa.ChapterUnits(principal=["a.md#1"])}))

    assert cli.main(["--output", str(out), "sources", "orphans"]) == 0
    assert "Aucune unité orpheline" in capsys.readouterr().out


def test_sources_conflicts_lists_contradicting_units(tmp_path, capsys):
    out = tmp_path / "out"
    _write_index(out, [_unit(1, conflit_avec=["a.md#2"]), _unit(2, conflit_avec=["a.md#1"]), _unit(3)])

    rc = cli.main(["--output", str(out), "sources", "conflicts"])

    text = capsys.readouterr().out
    assert rc == 0 and "a.md#1" in text and "a.md#2" in text and "a.md#3" not in text
    assert text.count("↔") == 1


def test_sources_conflicts_when_there_are_none(tmp_path, capsys):
    out = tmp_path / "out"
    _write_index(out, [_unit(1)])

    assert cli.main(["--output", str(out), "sources", "conflicts"]) == 0
    assert "Aucune contradiction" in capsys.readouterr().out


def test_sources_show_rejects_an_unknown_section(tmp_path, monkeypatch, capsys):
    from manual_cli.config import AppConfig
    from manual_cli.state import save_state

    out = tmp_path / "out"
    _write_index(out, [_unit(1)])
    save_state(out, make_manual_state())
    monkeypatch.setattr(cli, "load_config", lambda: AppConfig(settings={"sources": {"max_prompt_chars": 5000}}))

    assert cli.main(["--output", str(out), "sources", "show", "42"]) == 1
    assert "Section inconnue : 42" in capsys.readouterr().err


def test_sources_commands_need_an_analysed_index(tmp_path, capsys):
    for command in ("show", "orphans", "conflicts"):
        argv = ["--output", str(tmp_path / "vide"), "sources", command] + (["1"] if command == "show" else [])
        assert cli.main(argv) == 1
        assert "sources extract" in capsys.readouterr().err


def test_status_shows_source_coverage_only_when_there_is_matter(tmp_path, capsys):
    from manual_cli.state import save_state

    state = make_manual_state()
    state.sections[0].sources_total = 3
    state.sections[0].sources_ecartees = ["a.md#2 : hors sujet"]
    save_state(tmp_path, state)

    assert cli.main(["--output", str(tmp_path), "status"]) == 0
    assert "sources : 2/3 traitées, 1 écartée(s)" in capsys.readouterr().out

    state.sections[0].sources_total = 0
    save_state(tmp_path, state)
    cli.main(["--output", str(tmp_path), "status"])
    assert "sources" not in capsys.readouterr().out
