from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manual_cli import tracing


def test_not_configured_by_default():
    assert tracing.is_configured() is False


def test_configure_creates_trace_directory_and_returns_path(tmp_path):
    trace_path = tracing.configure(tmp_path)

    assert tracing.is_configured() is True
    assert trace_path == tmp_path / "traces" / "calls.jsonl"
    assert trace_path.parent.is_dir()
    assert not trace_path.exists()  # rien n'est écrit tant qu'aucun appel n'est journalisé


def test_record_call_noop_when_not_configured(tmp_path):
    started = datetime.now(timezone.utc)
    tracing.record_call(
        role="model_write",
        model_key="m",
        model_name="m:cloud",
        attempt=1,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        success=True,
        input_data=[{"role": "user", "content": "x"}],
        output="ok",
    )
    # Rien à vérifier de plus : l'absence d'exception et l'absence de fichier créé suffisent.
    assert not (tmp_path / "traces").exists()


def test_record_call_writes_one_json_line(tmp_path):
    trace_path = tracing.configure(tmp_path)
    started = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=2.5)

    tracing.record_call(
        role="model_write",
        model_key="glm-5.3",
        model_name="glm-5.3:cloud",
        attempt=1,
        started_at=started,
        ended_at=ended,
        success=True,
        input_data=[{"role": "user", "content": "salut"}],
        output="bonjour",
    )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["role"] == "model_write"
    assert record["model_key"] == "glm-5.3"
    assert record["model_name"] == "glm-5.3:cloud"
    assert record["attempt"] == 1
    assert record["success"] is True
    assert record["duration_seconds"] == 2.5
    assert record["input"] == [{"role": "user", "content": "salut"}]
    assert record["output"] == "bonjour"
    assert record["error"] is None
    assert record["started_at"].startswith("2026-01-01T10:00:00")


def test_record_call_appends_multiple_lines(tmp_path):
    trace_path = tracing.configure(tmp_path)
    started = datetime.now(timezone.utc)

    for i in range(3):
        tracing.record_call(
            role="model_judge",
            model_key="m",
            model_name="m:cloud",
            attempt=i + 1,
            started_at=started,
            ended_at=started,
            success=False,
            input_data="x",
            error="boom",
        )

    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(l)["attempt"] for l in lines] == [1, 2, 3]


def test_record_call_is_thread_safe(tmp_path):
    tracing.configure(tmp_path)
    started = datetime.now(timezone.utc)

    def _record(i: int) -> None:
        tracing.record_call(
            role="model_write",
            model_key="m",
            model_name="m:cloud",
            attempt=i,
            started_at=started,
            ended_at=started,
            success=True,
            input_data="x",
            output="y",
        )

    threads = [threading.Thread(target=_record, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    calls = tracing.read_calls(tracing.configure(tmp_path))
    assert len(calls) == 50
    assert sorted(c["attempt"] for c in calls) == list(range(50))


def test_read_calls_returns_empty_list_when_file_missing(tmp_path):
    assert tracing.read_calls(tmp_path / "does-not-exist.jsonl") == []


def test_read_calls_skips_malformed_lines(tmp_path):
    trace_path = tmp_path / "calls.jsonl"
    trace_path.write_text('{"a": 1}\nnot json\n\n{"a": 2}\n', encoding="utf-8")

    calls = tracing.read_calls(trace_path)

    assert calls == [{"a": 1}, {"a": 2}]


def test_reset_disables_tracing(tmp_path):
    tracing.configure(tmp_path)
    assert tracing.is_configured() is True

    tracing.reset()

    assert tracing.is_configured() is False
