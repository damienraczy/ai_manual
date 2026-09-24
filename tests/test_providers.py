from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import pytest
import requests

from manual_cli import providers, tracing
from manual_cli.config import ModelSpec
from manual_cli.providers import OllamaCloudClient, OpenAIImageClient, ProviderError, _images_url


def make_spec(**overrides) -> ModelSpec:
    defaults = dict(
        key="test-model",
        provider="ollama",
        name="test-model:cloud",
        base_url="https://ollama.example",
        api_key="secret",
        timeout=30,
    )
    defaults.update(overrides)
    return ModelSpec(**defaults)


def make_image_spec(**overrides) -> ModelSpec:
    defaults = dict(
        key="gpt-image-1",
        provider="openai",
        name="gpt-image-1",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        timeout=60,
    )
    defaults.update(overrides)
    return ModelSpec(**defaults)


def _mock_response(json_data, status_ok: bool = True) -> Mock:
    resp = Mock()
    resp.raise_for_status = Mock() if status_ok else Mock(side_effect=requests.HTTPError("500"))
    resp.json = Mock(return_value=json_data)
    return resp


def test_chat_success_first_try():
    client = OllamaCloudClient(make_spec())
    response = _mock_response({"message": {"content": "bonjour"}})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        result = client.chat([{"role": "user", "content": "salut"}])

    assert result == "bonjour"
    args, kwargs = post.call_args
    assert args[0] == "https://ollama.example/api/chat"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["json"]["model"] == "test-model:cloud"
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "salut"}]
    assert kwargs["json"]["stream"] is False
    assert kwargs["timeout"] == 30


def test_chat_strips_trailing_slash_from_base_url():
    client = OllamaCloudClient(make_spec(base_url="https://ollama.example/"))
    response = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        client.chat([{"role": "user", "content": "x"}])

    assert post.call_args[0][0] == "https://ollama.example/api/chat"


def test_chat_does_not_duplicate_api_suffix_when_base_url_already_has_it():
    client = OllamaCloudClient(make_spec(base_url="https://ollama.com/api"))
    response = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        client.chat([{"role": "user", "content": "x"}])

    assert post.call_args[0][0] == "https://ollama.com/api/chat"


def test_chat_does_not_duplicate_api_suffix_with_trailing_slash():
    client = OllamaCloudClient(make_spec(base_url="https://ollama.com/api/"))
    response = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        client.chat([{"role": "user", "content": "x"}])

    assert post.call_args[0][0] == "https://ollama.com/api/chat"


def test_chat_passes_temperature_as_option():
    client = OllamaCloudClient(make_spec())
    response = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        client.chat([{"role": "user", "content": "x"}], temperature=0.2)

    assert post.call_args.kwargs["json"]["options"] == {"temperature": 0.2}


def test_chat_retries_then_succeeds(monkeypatch):
    client = OllamaCloudClient(make_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)

    bad = requests.RequestException("boom")
    good = _mock_response({"message": {"content": "ca marche"}})

    with patch("manual_cli.providers.requests.post", side_effect=[bad, bad, good]):
        result = client.chat([{"role": "user", "content": "x"}])

    assert result == "ca marche"


def test_chat_exhausts_retries_raises_provider_error(monkeypatch):
    client = OllamaCloudClient(make_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)

    with patch("manual_cli.providers.requests.post", side_effect=requests.RequestException("down")):
        with pytest.raises(ProviderError, match="test-model"):
            client.chat([{"role": "user", "content": "x"}])


def test_chat_http_error_status_triggers_retry_then_raises(monkeypatch):
    client = OllamaCloudClient(make_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)
    response = _mock_response({}, status_ok=False)

    with patch("manual_cli.providers.requests.post", return_value=response):
        with pytest.raises(ProviderError):
            client.chat([{"role": "user", "content": "x"}])


def test_chat_malformed_json_response_retries_and_raises(monkeypatch):
    client = OllamaCloudClient(make_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)
    response = _mock_response({"unexpected": "shape"})

    with patch("manual_cli.providers.requests.post", return_value=response):
        with pytest.raises(ProviderError):
            client.chat([{"role": "user", "content": "x"}])


def _mock_429_response(retry_after: str | None = None) -> Mock:
    """Réponse simulant un 429 avec (ou sans) en-tête `Retry-After`."""
    resp = Mock()
    resp.status_code = 429
    resp.headers = {"Retry-After": retry_after} if retry_after is not None else {}
    resp.raise_for_status = Mock(side_effect=requests.HTTPError("429", response=resp))
    return resp


def test_chat_429_with_numeric_retry_after_uses_exact_delay(monkeypatch):
    client = OllamaCloudClient(make_spec())
    sleep_calls: list[float] = []
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: sleep_calls.append(s))

    bad = _mock_429_response(retry_after="5")
    good = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", side_effect=[bad, good]):
        result = client.chat([{"role": "user", "content": "x"}])

    assert result == "ok"
    assert sleep_calls == [5.0]


def test_chat_429_without_retry_after_falls_back_to_backoff(monkeypatch):
    client = OllamaCloudClient(make_spec())
    sleep_calls: list[float] = []
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr("manual_cli.providers.random.uniform", lambda a, b: b)

    bad = _mock_429_response()  # pas d'en-tête Retry-After
    good = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", side_effect=[bad, good]):
        client.chat([{"role": "user", "content": "x"}])

    assert sleep_calls == [providers.BACKOFF_BASE_SECONDS]  # plafond de la tentative 1


# --- _retry_after_seconds -------------------------------------------------------


def test_retry_after_seconds_parses_numeric_header():
    resp = Mock(status_code=429, headers={"Retry-After": "12"})
    exc = requests.HTTPError("429", response=resp)
    assert providers._retry_after_seconds(exc) == 12.0


def test_retry_after_seconds_parses_http_date_header():
    target = datetime.now(timezone.utc) + timedelta(seconds=10)
    resp = Mock(status_code=429, headers={"Retry-After": format_datetime(target, usegmt=True)})
    exc = requests.HTTPError("429", response=resp)

    delay = providers._retry_after_seconds(exc)

    assert delay is not None
    assert 8 <= delay <= 11  # tolérance pour le temps d'exécution du test


def test_retry_after_seconds_parses_naive_http_date_as_utc():
    # Certains serveurs omettent le fuseau ("GMT"/"+0000") — traité comme UTC.
    naive = (datetime.now(timezone.utc) + timedelta(seconds=10)).strftime("%a, %d %b %Y %H:%M:%S")
    resp = Mock(status_code=429, headers={"Retry-After": naive})
    exc = requests.HTTPError("429", response=resp)

    delay = providers._retry_after_seconds(exc)

    assert delay is not None
    assert 8 <= delay <= 11


def test_retry_after_seconds_none_when_not_an_http_error():
    assert providers._retry_after_seconds(requests.RequestException("boom")) is None


def test_retry_after_seconds_none_when_status_is_not_429():
    resp = Mock(status_code=500, headers={"Retry-After": "5"})
    exc = requests.HTTPError("500", response=resp)
    assert providers._retry_after_seconds(exc) is None


def test_retry_after_seconds_none_when_header_missing():
    resp = Mock(status_code=429, headers={})
    exc = requests.HTTPError("429", response=resp)
    assert providers._retry_after_seconds(exc) is None


def test_retry_after_seconds_none_when_header_unparseable():
    resp = Mock(status_code=429, headers={"Retry-After": "not-a-date"})
    exc = requests.HTTPError("429", response=resp)
    assert providers._retry_after_seconds(exc) is None


# --- _backoff_seconds ------------------------------------------------------------


def test_backoff_seconds_ceiling_doubles_each_attempt(monkeypatch):
    captured: list[tuple[float, float]] = []
    monkeypatch.setattr("manual_cli.providers.random.uniform", lambda a, b: captured.append((a, b)) or b)

    providers._backoff_seconds(1)
    providers._backoff_seconds(2)
    providers._backoff_seconds(3)

    assert captured == [(0, 2.0), (0, 4.0), (0, 8.0)]


def test_backoff_seconds_capped_at_max(monkeypatch):
    captured: list[tuple[float, float]] = []
    monkeypatch.setattr("manual_cli.providers.random.uniform", lambda a, b: captured.append((a, b)) or b)

    providers._backoff_seconds(10)

    assert captured == [(0, providers.BACKOFF_MAX_SECONDS)]


# --- _images_url --------------------------------------------------------------


def test_images_url_appends_suffix_to_plain_v1_base():
    assert _images_url("https://api.openai.com/v1") == "https://api.openai.com/v1/images/generations"


def test_images_url_truncates_after_v1_when_base_has_extra_path():
    # Cas réel observé : OPENAI_URL pointe vers .../v1/responses dans ~/.env.
    assert _images_url("https://api.openai.com/v1/responses") == "https://api.openai.com/v1/images/generations"


def test_images_url_handles_trailing_slash():
    assert _images_url("https://api.openai.com/v1/responses/") == "https://api.openai.com/v1/images/generations"


def test_images_url_falls_back_when_no_v1_segment():
    assert _images_url("https://images.example.com/") == "https://images.example.com/images/generations"


# --- OpenAIImageClient ----------------------------------------------------------


def test_generate_image_success_from_b64_json():
    client = OpenAIImageClient(make_image_spec())
    png_bytes = b"\x89PNG-fake-bytes"
    response = _mock_response(
        {"data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}]}
    )

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        result = client.generate_image("un chat")

    assert result == png_bytes
    args, kwargs = post.call_args
    assert args[0] == "https://api.openai.com/v1/images/generations"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert kwargs["json"]["model"] == "gpt-image-1"
    assert kwargs["json"]["prompt"] == "un chat"
    assert kwargs["json"]["n"] == 1


def test_generate_image_falls_back_to_url_download():
    client = OpenAIImageClient(make_image_spec())
    gen_response = _mock_response({"data": [{"url": "https://cdn.example.com/img.png"}]})
    png_bytes = b"downloaded-bytes"
    download_response = Mock()
    download_response.raise_for_status = Mock()
    download_response.content = png_bytes

    with patch(
        "manual_cli.providers.requests.post", return_value=gen_response
    ), patch("manual_cli.providers.requests.get", return_value=download_response) as get:
        result = client.generate_image("un chat")

    assert result == png_bytes
    assert get.call_args[0][0] == "https://cdn.example.com/img.png"


def test_generate_image_custom_size_is_forwarded():
    client = OpenAIImageClient(make_image_spec())
    png_bytes = b"bytes"
    response = _mock_response({"data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}]})

    with patch("manual_cli.providers.requests.post", return_value=response) as post:
        client.generate_image("un chat", size="1536x1024")

    assert post.call_args.kwargs["json"]["size"] == "1536x1024"


def test_generate_image_exhausts_retries_raises_provider_error(monkeypatch):
    client = OpenAIImageClient(make_image_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)

    with patch("manual_cli.providers.requests.post", side_effect=requests.RequestException("down")):
        with pytest.raises(ProviderError, match="gpt-image-1"):
            client.generate_image("un chat")


def test_generate_image_raises_when_response_has_no_usable_data(monkeypatch):
    client = OpenAIImageClient(make_image_spec())
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)
    response = _mock_response({"data": [{}]})

    with patch("manual_cli.providers.requests.post", return_value=response):
        with pytest.raises(ProviderError):
            client.generate_image("un chat")


# --- Traçage des appels -----------------------------------------------------


def test_client_default_role_is_unspecified():
    assert OllamaCloudClient(make_spec()).role == "unspecified"


def test_client_accepts_custom_role():
    assert OllamaCloudClient(make_spec(), role="model_write").role == "model_write"


def test_chat_does_not_write_trace_when_not_configured(tmp_path):
    client = OllamaCloudClient(make_spec())
    response = _mock_response({"message": {"content": "bonjour"}})

    with patch("manual_cli.providers.requests.post", return_value=response):
        client.chat([{"role": "user", "content": "salut"}])

    assert not (tmp_path / "traces").exists()


def test_chat_records_trace_on_success(tmp_path):
    tracing.configure(tmp_path)
    client = OllamaCloudClient(make_spec(), role="model_write")
    response = _mock_response({"message": {"content": "bonjour"}})
    messages = [{"role": "user", "content": "salut"}]

    with patch("manual_cli.providers.requests.post", return_value=response):
        client.chat(messages)

    calls = tracing.read_calls(tmp_path / "traces" / "calls.jsonl")
    assert len(calls) == 1
    record = calls[0]
    assert record["role"] == "model_write"
    assert record["model_key"] == "test-model"
    assert record["model_name"] == "test-model:cloud"
    assert record["attempt"] == 1
    assert record["success"] is True
    assert record["input"] == messages
    assert record["output"] == "bonjour"
    assert record["error"] is None
    assert record["duration_seconds"] >= 0


def test_chat_records_one_trace_per_attempt(tmp_path, monkeypatch):
    tracing.configure(tmp_path)
    monkeypatch.setattr("manual_cli.providers.time.sleep", lambda s: None)
    client = OllamaCloudClient(make_spec(), role="model_judge")

    bad = requests.RequestException("boom")
    good = _mock_response({"message": {"content": "ok"}})

    with patch("manual_cli.providers.requests.post", side_effect=[bad, bad, good]):
        client.chat([{"role": "user", "content": "x"}])

    calls = tracing.read_calls(tmp_path / "traces" / "calls.jsonl")
    assert len(calls) == 3
    assert [c["attempt"] for c in calls] == [1, 2, 3]
    assert [c["success"] for c in calls] == [False, False, True]
    assert "boom" in calls[0]["error"]
    assert calls[2]["output"] == "ok"


def test_generate_image_records_trace_with_short_output_descriptor(tmp_path):
    tracing.configure(tmp_path)
    client = OpenAIImageClient(make_image_spec(), role="model_image")
    png_bytes = b"\x89PNG-fake-bytes"
    response = _mock_response({"data": [{"b64_json": base64.b64encode(png_bytes).decode("ascii")}]})

    with patch("manual_cli.providers.requests.post", return_value=response):
        client.generate_image("un prompt d'image")

    calls = tracing.read_calls(tmp_path / "traces" / "calls.jsonl")
    assert len(calls) == 1
    record = calls[0]
    assert record["role"] == "model_image"
    assert record["input"] == "un prompt d'image"
    assert record["output"] == f"<image binaire, {len(png_bytes)} octets>"
