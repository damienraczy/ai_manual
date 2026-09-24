from __future__ import annotations

import pytest

from manual_cli import cli, tracing
from manual_cli.config import ConfigError
from manual_cli.schemas import Chapitre, Partie, TocSchema
from manual_cli.state import build_manual_state


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
        cli, "generate_toc", lambda cfg, out: called.__setitem__("generate_toc", True) or make_manual_state()
    )

    rc = cli.main(["--output", str(tmp_path), "init"])

    assert rc == 1
    assert called["generate_toc"] is False
    assert "déjà" in capsys.readouterr().out


def test_cmd_init_generates_toc(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: False)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    state = make_manual_state()
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out: state)

    rc = cli.main(["--output", str(tmp_path), "init"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "1 chapitres" in out


def test_cmd_init_force_regenerates_even_if_state_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "state_exists", lambda output_dir: True)
    monkeypatch.setattr(cli, "load_config", lambda: object())
    state = make_manual_state()
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out: state)

    rc = cli.main(["--output", str(tmp_path), "init", "--force"])

    assert rc == 0


def test_cmd_write_reports_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    section = make_manual_state().sections[0]
    section.status = "done"
    section.attempts = 1
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "[OK]" in capsys.readouterr().out


def test_cmd_write_reports_section_needing_review(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    section = make_manual_state().sections[0]
    section.status = "failed"
    section.attempts = 3
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "A REVOIR" in capsys.readouterr().out


def test_cmd_write_no_pending_sections(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [])

    rc = cli.main(["--output", str(tmp_path), "write"])

    assert rc == 0
    assert "Rien à rédiger" in capsys.readouterr().out


def test_cmd_write_passes_none_when_no_section_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, only_numeros, max_rewrite, workers):
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

    def fake_run_write(cfg, out, only_numeros, max_rewrite, workers):
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
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [section])

    rc = cli.main(["--output", str(tmp_path), "redo", "1"])

    assert rc == 0
    assert "A REVOIR" in capsys.readouterr().out


def test_cmd_redo_passes_single_numero_and_one_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_run_write(cfg, out, only_numeros, max_rewrite, workers):
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
    monkeypatch.setattr(cli, "publish_section", lambda cfg, out, numero, generate_image: publish_dir)

    rc = cli.main(["--output", str(tmp_path), "publish", "1"])

    assert rc == 0
    out = capsys.readouterr().out
    assert str(publish_dir) in out


def test_cmd_publish_forwards_no_image_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_publish_section(cfg, out, numero, generate_image):
        received["numero"] = numero
        received["generate_image"] = generate_image
        return tmp_path / "publish" / "01_intro"

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    cli.main(["--output", str(tmp_path), "publish", "3", "--no-image"])

    assert received["numero"] == 3
    assert received["generate_image"] is False


def test_cmd_publish_generates_image_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    received = {}

    def fake_publish_section(cfg, out, numero, generate_image):
        received["generate_image"] = generate_image
        return tmp_path / "publish" / "01_intro"

    monkeypatch.setattr(cli, "publish_section", fake_publish_section)

    cli.main(["--output", str(tmp_path), "publish", "1"])

    assert received["generate_image"] is True


def test_cmd_publish_reports_not_done_section_as_error(tmp_path, monkeypatch, capsys):
    from manual_cli.publish import PublishError

    monkeypatch.setattr(cli, "load_config", lambda: object())

    def fake_publish_section(cfg, out, numero, generate_image):
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
    monkeypatch.setattr(cli, "generate_toc", lambda cfg, out: make_manual_state())

    cli.main(["--output", str(tmp_path), "init"])

    assert tracing.is_configured() is True


def test_cmd_write_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [])

    cli.main(["--output", str(tmp_path), "write"])

    assert tracing.is_configured() is True


def test_cmd_redo_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "run_write", lambda cfg, out, only_numeros, max_rewrite, workers: [])

    cli.main(["--output", str(tmp_path), "redo", "1"])

    assert tracing.is_configured() is True


def test_cmd_publish_configures_tracing(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(cli, "publish_section", lambda cfg, out, numero, generate_image: tmp_path / "publish" / "x")

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
