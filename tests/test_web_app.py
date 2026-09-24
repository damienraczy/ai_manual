from __future__ import annotations

import json

import pytest

flask = pytest.importorskip("flask")

from manual_cli.web.app import create_app


@pytest.fixture
def client(tmp_path):
    trace_path = tmp_path / "traces" / "calls.jsonl"
    app = create_app(trace_path)
    app.config.update(TESTING=True)
    return app.test_client(), trace_path


def test_index_serves_html_page(client):
    test_client, _ = client
    resp = test_client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert b"<html" in resp.data.lower()


def test_api_calls_returns_empty_list_when_no_trace_file(client):
    test_client, _ = client
    resp = test_client.get("/api/calls")

    assert resp.status_code == 200
    assert resp.json == []


def test_api_calls_returns_journaled_records(client):
    test_client, trace_path = client
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "role": "model_write",
        "model_key": "m",
        "model_name": "m:cloud",
        "attempt": 1,
        "started_at": "2026-01-01T10:00:00+00:00",
        "ended_at": "2026-01-01T10:00:02+00:00",
        "duration_seconds": 2.0,
        "success": True,
        "input": [{"role": "user", "content": "salut"}],
        "output": "bonjour",
        "error": None,
    }
    trace_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    resp = test_client.get("/api/calls")

    assert resp.status_code == 200
    assert resp.json == [record]
