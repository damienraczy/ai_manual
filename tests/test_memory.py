from __future__ import annotations

from manual_cli.memory import (
    INITIAL_DIGEST,
    MAX_DIGEST_CHARS,
    ensure_budget,
    load_digest,
    save_digest,
    update_digest,
)


class FakeClient:
    def __init__(self, response: str):
        self._response = response
        self.received_messages: list[dict] | None = None

    def chat(self, messages: list[dict]) -> str:
        self.received_messages = messages
        return self._response


def test_load_digest_default_when_missing(tmp_path):
    assert load_digest(tmp_path) == INITIAL_DIGEST


def test_save_and_load_digest_round_trip(tmp_path):
    save_digest(tmp_path, "mon résumé")
    assert load_digest(tmp_path) == "mon résumé"


def test_update_digest_returns_stripped_response():
    client = FakeClient("  nouveau résumé  \n")
    result = update_digest(client, "ancien", "Titre", "texte de la section")
    assert result == "nouveau résumé"
    prompt = client.received_messages[0]["content"]
    assert "ancien" in prompt
    assert "texte de la section" in prompt


def test_update_digest_falls_back_to_current_on_empty_response():
    client = FakeClient("   ")
    result = update_digest(client, "ancien résumé", "Titre", "texte")
    assert result == "ancien résumé"


def test_ensure_budget_keeps_short_digest_untouched():
    client = FakeClient("ne doit pas être appelé")
    short_digest = "x" * 100
    result = ensure_budget(client, short_digest)
    assert result == short_digest
    assert client.received_messages is None


def test_ensure_budget_compresses_long_digest():
    client = FakeClient("résumé compressé")
    long_digest = "x" * (MAX_DIGEST_CHARS + 1)
    result = ensure_budget(client, long_digest)
    assert result == "résumé compressé"
    assert client.received_messages is not None


def test_ensure_budget_falls_back_to_truncation_on_empty_response():
    client = FakeClient("")
    long_digest = "y" * (MAX_DIGEST_CHARS + 500)
    result = ensure_budget(client, long_digest)
    assert result == long_digest[:MAX_DIGEST_CHARS]
