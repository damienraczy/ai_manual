from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from manual_cli.config import AppConfig, ConfigError, load_config

PARAMS_YAML = textwrap.dedent(
    """
    models:
      writer-model:
        provider: ollama
        name: writer:cloud
        url: TEST_OLLAMA_URL
        api_key: TEST_OLLAMA_KEY
        timeout: 90
      other-provider-model:
        provider: openai
        name: gpt-test
        url: TEST_OPENAI_URL
        api_key: TEST_OPENAI_KEY
        timeout: 60

    llm_config:
      timeout: 120
      llm:
        model_write: writer-model
        model_judge: writer-model
        model_think: writer-model
        model_rewriter: writer-model
    """
)


@pytest.fixture
def params_file(tmp_path: Path) -> Path:
    p = tmp_path / "params.yml"
    p.write_text(PARAMS_YAML, encoding="utf-8")
    return p


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text("", encoding="utf-8")
    return p


def test_load_config_success(params_file, env_file, monkeypatch):
    monkeypatch.setenv("TEST_OLLAMA_URL", "https://ollama.example")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "secret-key")

    cfg = load_config(params_path=params_file, env_path=env_file)

    for role_name in ("model_write", "model_judge", "model_think", "model_rewriter"):
        assert cfg.role(role_name).key == "writer-model"
    spec = cfg.role("model_write")
    assert spec.key == "writer-model"
    assert spec.name == "writer:cloud"
    assert spec.base_url == "https://ollama.example"
    assert spec.api_key == "secret-key"
    assert spec.timeout == 90


def test_load_config_uses_fallback_timeout_when_model_has_none(tmp_path, env_file, monkeypatch):
    p = tmp_path / "params.yml"
    p.write_text(
        textwrap.dedent(
            """
            models:
              writer-model:
                provider: ollama
                name: writer:cloud
                url: TEST_OLLAMA_URL
                api_key: TEST_OLLAMA_KEY
            llm_config:
              timeout: 77
              llm:
                model_write: writer-model
                model_judge: writer-model
                model_think: writer-model
                model_rewriter: writer-model
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    cfg = load_config(params_path=p, env_path=env_file)

    assert cfg.role("model_write").timeout == 77


def test_load_config_missing_role(tmp_path, env_file, monkeypatch):
    incomplete = tmp_path / "params.yml"
    incomplete.write_text(
        textwrap.dedent(
            """
            models:
              writer-model:
                provider: ollama
                name: writer:cloud
                url: TEST_OLLAMA_URL
                api_key: TEST_OLLAMA_KEY
            llm_config:
              llm:
                model_write: writer-model
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    with pytest.raises(ConfigError, match="model_judge"):
        load_config(params_path=incomplete, env_path=env_file)


def test_load_config_unknown_model_reference(tmp_path, env_file, monkeypatch):
    bad = tmp_path / "params.yml"
    bad.write_text(
        textwrap.dedent(
            """
            models:
              writer-model:
                provider: ollama
                name: writer:cloud
                url: TEST_OLLAMA_URL
                api_key: TEST_OLLAMA_KEY
            llm_config:
              llm:
                model_write: does-not-exist
                model_judge: writer-model
                model_think: writer-model
                model_rewriter: writer-model
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    with pytest.raises(ConfigError, match="does-not-exist"):
        load_config(params_path=bad, env_path=env_file)


def test_load_config_unsupported_provider(tmp_path, env_file, monkeypatch):
    p = tmp_path / "params.yml"
    p.write_text(
        PARAMS_YAML.replace("model_judge: writer-model", "model_judge: other-provider-model"),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    monkeypatch.setenv("TEST_OPENAI_URL", "u2")
    monkeypatch.setenv("TEST_OPENAI_KEY", "k2")

    with pytest.raises(ConfigError, match="openai"):
        load_config(params_path=p, env_path=env_file)


def test_load_config_missing_env_vars(params_file, env_file):
    with pytest.raises(ConfigError, match="TEST_OLLAMA_URL"):
        load_config(params_path=params_file, env_path=env_file)


def test_role_unknown_raises():
    cfg = AppConfig(roles={})
    with pytest.raises(ConfigError):
        cfg.role("model_write")


def test_load_config_without_model_image_role_still_succeeds(params_file, env_file, monkeypatch):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    cfg = load_config(params_path=params_file, env_path=env_file)

    with pytest.raises(ConfigError):
        cfg.role("model_image")


def test_load_config_resolves_optional_model_image_role_with_openai_provider(tmp_path, env_file, monkeypatch):
    p = tmp_path / "params.yml"
    p.write_text(
        PARAMS_YAML.replace(
            "model_rewriter: writer-model",
            "model_rewriter: writer-model\n    model_image: other-provider-model",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    monkeypatch.setenv("TEST_OPENAI_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test")

    cfg = load_config(params_path=p, env_path=env_file)

    spec = cfg.role("model_image")
    assert spec.provider == "openai"
    assert spec.name == "gpt-test"
    assert spec.base_url == "https://api.openai.com/v1"


def test_load_config_rejects_model_image_with_unsupported_provider(tmp_path, env_file, monkeypatch):
    p = tmp_path / "params.yml"
    p.write_text(
        PARAMS_YAML.replace(
            "model_rewriter: writer-model",
            "model_rewriter: writer-model\n    model_image: writer-model",
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    with pytest.raises(ConfigError, match="model_image"):
        load_config(params_path=p, env_path=env_file)


# --- Rechargement à la demande (params.yml lu à chaque appel de rôle) ----------


def test_role_reloads_timeout_from_params_yml_on_each_call(params_file, env_file, monkeypatch):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    cfg = load_config(params_path=params_file, env_path=env_file)
    assert cfg.role("model_write").timeout == 90

    # Le fichier est modifié après le chargement initial, sans recréer `cfg`
    # (simule l'édition de params.yml pendant qu'une longue exécution est en cours).
    params_file.write_text(PARAMS_YAML.replace("timeout: 90", "timeout: 900"), encoding="utf-8")

    assert cfg.role("model_write").timeout == 900


def test_role_reflects_model_key_change_between_calls(tmp_path, env_file, monkeypatch):
    # writer-model et alt-model partagent le même provider (ollama) pour que seul le
    # nom du modèle cible change d'un appel à l'autre, sans toucher à la validation du provider.
    yaml_text = textwrap.dedent(
        """
        models:
          writer-model:
            provider: ollama
            name: writer:cloud
            url: TEST_OLLAMA_URL
            api_key: TEST_OLLAMA_KEY
            timeout: 90
          alt-model:
            provider: ollama
            name: alt:cloud
            url: TEST_OLLAMA_URL
            api_key: TEST_OLLAMA_KEY
            timeout: 90

        llm_config:
          llm:
            model_write: writer-model
            model_judge: writer-model
            model_think: writer-model
            model_rewriter: writer-model
        """
    )
    p = tmp_path / "params.yml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    cfg = load_config(params_path=p, env_path=env_file)
    assert cfg.role("model_judge").key == "writer-model"

    p.write_text(yaml_text.replace("model_judge: writer-model", "model_judge: alt-model"), encoding="utf-8")

    assert cfg.role("model_judge").key == "alt-model"
    # Les autres rôles, non modifiés dans le fichier, restent inchangés.
    assert cfg.role("model_write").key == "writer-model"


def test_load_config_reports_all_missing_roles_at_once(tmp_path, env_file, monkeypatch):
    p = tmp_path / "params.yml"
    p.write_text(
        textwrap.dedent(
            """
            models:
              writer-model:
                provider: ollama
                name: writer:cloud
                url: TEST_OLLAMA_URL
                api_key: TEST_OLLAMA_KEY
            llm_config:
              llm:
                model_write: writer-model
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    with pytest.raises(ConfigError) as exc_info:
        load_config(params_path=p, env_path=env_file)

    message = str(exc_info.value)
    assert "model_judge" in message
    assert "model_think" in message
    assert "model_rewriter" in message
