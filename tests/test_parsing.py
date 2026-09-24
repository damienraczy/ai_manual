from __future__ import annotations

import pytest
from pydantic import BaseModel

from manual_cli.parsing import ParsingError, call_structured


class Dummy(BaseModel):
    value: int


class FakeClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def chat(self, messages: list[dict]) -> str:
        self.calls.append([m["content"] for m in messages])
        return self._responses.pop(0)


def test_call_structured_parses_fenced_json_first_try():
    client = FakeClient(['```json\n{"value": 42}\n```'])
    result = call_structured(client, [{"role": "user", "content": "go"}], Dummy)
    assert result.value == 42
    assert len(client.calls) == 1


def test_call_structured_parses_bare_braces_fallback():
    client = FakeClient(['noise before {"value": 7} noise after'])
    result = call_structured(client, [{"role": "user", "content": "go"}], Dummy)
    assert result.value == 7


def test_call_structured_retries_on_invalid_json_then_succeeds():
    client = FakeClient(["not json at all", '```json\n{"value": 1}\n```'])
    result = call_structured(client, [{"role": "user", "content": "go"}], Dummy, max_attempts=3)
    assert result.value == 1
    assert len(client.calls) == 2
    assert "JSON valide" in client.calls[1][-1]


def test_call_structured_retries_on_schema_violation():
    client = FakeClient(['```json\n{"wrong_key": 1}\n```', '```json\n{"value": 9}\n```'])
    result = call_structured(client, [{"role": "user", "content": "go"}], Dummy, max_attempts=3)
    assert result.value == 9


def test_call_structured_raises_after_max_attempts():
    client = FakeClient(["nope", "still nope", "nope again"])
    with pytest.raises(ParsingError):
        call_structured(client, [{"role": "user", "content": "go"}], Dummy, max_attempts=3)
    assert len(client.calls) == 3


def test_call_structured_raises_when_no_braces_at_all():
    client = FakeClient(["rien du tout"])
    with pytest.raises(ParsingError):
        call_structured(client, [{"role": "user", "content": "go"}], Dummy, max_attempts=1)
