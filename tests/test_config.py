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


def params_with_think(tmp_path: Path, think_line: str) -> Path:
    p = tmp_path / "params.yml"
    p.write_text(
        PARAMS_YAML.replace("    timeout: 90\n", f"    timeout: 90\n{think_line}", 1), encoding="utf-8"
    )
    return p


def test_model_without_think_leaves_it_unset(params_file, env_file, monkeypatch):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")

    assert load_config(params_path=params_file, env_path=env_file).role("model_write").think is None


@pytest.mark.parametrize(
    ("yaml_value", "expected"), [("low", "low"), ("max", "max"), ("true", True), ("false", False), ("off", False)]
)
def test_model_think_level_or_boolean_is_read_as_is(tmp_path, env_file, monkeypatch, yaml_value, expected):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    p = params_with_think(tmp_path, f"    think: {yaml_value}\n")

    think = load_config(params_path=p, env_path=env_file).role("model_write").think
    assert think == expected and type(think) is type(expected)


@pytest.mark.parametrize("yaml_value", ["3", '""', "[low]", "1.5"])
def test_model_think_of_another_type_is_rejected(tmp_path, env_file, monkeypatch, yaml_value):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    p = params_with_think(tmp_path, f"    think: {yaml_value}\n")

    with pytest.raises(ConfigError, match="think"):
        load_config(params_path=p, env_path=env_file)


@pytest.mark.parametrize("key", ["effort", "reasoning_effort", "disable_thinking", "timout"])
def test_model_with_an_unknown_key_is_rejected_instead_of_silently_ignored(tmp_path, env_file, monkeypatch, key):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    p = params_with_think(tmp_path, f"    {key}: low\n")

    with pytest.raises(ConfigError, match=rf"writer-model.*{key}"):
        load_config(params_path=p, env_path=env_file)


def test_unknown_key_error_points_to_think_and_lists_known_keys(tmp_path, env_file, monkeypatch):
    monkeypatch.setenv("TEST_OLLAMA_URL", "u")
    monkeypatch.setenv("TEST_OLLAMA_KEY", "k")
    p = params_with_think(tmp_path, "    effort: low\n")

    with pytest.raises(ConfigError) as excinfo:
        load_config(params_path=p, env_path=env_file)

    message = str(excinfo.value)
    assert "think" in message and "timeout" in message


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


# --- réglages (section libre de params.yml) ------------------------------------------


def test_setting_reads_a_value_from_params_yml_on_each_call(tmp_path, env_file):
    params = tmp_path / "params.yml"
    params.write_text(PARAMS_YAML + "\nsources:\n  max_chunk_chars: 500\n", encoding="utf-8")
    cfg = AppConfig(params_path=params, env_path=env_file)

    assert cfg.setting("sources", "max_chunk_chars") == 500

    params.write_text(PARAMS_YAML + "\nsources:\n  max_chunk_chars: 900\n", encoding="utf-8")
    assert cfg.setting("sources", "max_chunk_chars") == 900


def test_setting_missing_raises_an_explicit_error(tmp_path, env_file):
    params = tmp_path / "params.yml"
    params.write_text(PARAMS_YAML, encoding="utf-8")
    cfg = AppConfig(params_path=params, env_path=env_file)

    with pytest.raises(ConfigError, match="sources.max_chunk_chars"):
        cfg.setting("sources", "max_chunk_chars")


def test_setting_in_static_mode_reads_the_settings_mapping():
    cfg = AppConfig(settings={"sources": {"max_chunk_chars": 10}})

    assert cfg.setting("sources", "max_chunk_chars") == 10
    with pytest.raises(ConfigError):
        cfg.setting("sources", "absent")
