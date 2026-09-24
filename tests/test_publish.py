from __future__ import annotations

import pytest

from manual_cli import publish
from manual_cli.config import AppConfig, ModelSpec
from manual_cli.schemas import Chapitre, Partie, SousSection, TocSchema
from manual_cli.state import build_manual_state, save_state


def make_spec(key: str, provider: str = "ollama") -> ModelSpec:
    return ModelSpec(key=key, provider=provider, name=f"{key}:model", base_url="http://x", api_key="k", timeout=30)


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig(
        roles={
            "model_write": make_spec("writer"),
            "model_judge": make_spec("judge"),
            "model_think": make_spec("think"),
            "model_rewriter": make_spec("rewriter"),
            "model_image": make_spec("image-model", provider="openai"),
        }
    )


def make_state():
    toc = TocSchema(
        titre_manuel="Manuel Test",
        parties=[
            Partie(
                numero="I",
                titre="Fondamentaux",
                chapitres=[
                    Chapitre(
                        numero=1,
                        titre="Introduction",
                        description="Une intro.",
                        sous_sections=[SousSection(numero="1.1", titre="Def")],
                    ),
                    Chapitre(numero=2, titre="Non terminé", description="d", sous_sections=[]),
                ],
            )
        ],
    )
    return build_manual_state(toc)


# --- _write_client / _image_client ---------------------------------------------


def test_write_client_builds_ollama_cloud_client_from_role(cfg):
    from manual_cli.providers import OllamaCloudClient

    client = publish._write_client(cfg)

    assert isinstance(client, OllamaCloudClient)
    assert client.spec.key == "writer"
    assert client.role == "model_write"


def test_image_client_builds_openai_image_client_from_role(cfg):
    from manual_cli.providers import OpenAIImageClient

    client = publish._image_client(cfg)

    assert isinstance(client, OpenAIImageClient)
    assert client.spec.key == "image-model"
    assert client.role == "model_image"


# --- render_article_html -------------------------------------------------------


def test_render_article_html_converts_headings_bold_and_lists():
    markdown_text = "## 1. Introduction\n\nUn **concept clé** :\n\n- premier point\n- second point\n"

    html = publish.render_article_html(markdown_text, "Introduction")

    assert "<h2>1. Introduction</h2>" in html
    assert "<strong>concept clé</strong>" in html
    assert "<li>premier point</li>" in html
    assert "<title>Introduction</title>" in html


# --- build_image_prompt ---------------------------------------------------------


def test_build_image_prompt_includes_manual_and_section_context():
    state = make_state()
    section = state.section_by_numero(1)

    prompt = publish.build_image_prompt(state.titre_manuel, section)

    assert "Manuel Test" in prompt
    assert "Introduction" in prompt
    assert "Une intro." in prompt
    assert "1" in prompt


# --- generate_post_draft ---------------------------------------------------------


class FakeChatClient:
    def __init__(self, response: str):
        self._response = response
        self.received_messages = None

    def chat(self, messages):
        self.received_messages = messages
        return self._response


def test_generate_post_draft_substitutes_section_context_and_strips_response():
    state = make_state()
    section = state.section_by_numero(1)
    client = FakeChatClient("  Un brouillon de post.\n{ARTICLE_URL}\n  ")

    draft = publish.generate_post_draft(client, state.titre_manuel, section)

    assert draft == "Un brouillon de post.\n{ARTICLE_URL}"
    prompt = client.received_messages[0]["content"]
    assert "Manuel Test" in prompt
    assert "Introduction" in prompt
    assert "Une intro." in prompt


# --- publish_section --------------------------------------------------------------


def test_publish_section_raises_if_section_not_done(tmp_path, cfg):
    state = make_state()
    save_state(tmp_path, state)

    with pytest.raises(publish.PublishError, match="2"):
        publish.publish_section(cfg, tmp_path, 2)


def test_publish_section_creates_expected_files(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    section.status = "done"
    save_state(tmp_path, state)
    (tmp_path / section.filename).write_text("## 1. Introduction\n\nContenu **important**.\n", encoding="utf-8")

    monkeypatch.setattr(publish, "_write_client", lambda cfg: FakeChatClient("Mon post.\n{ARTICLE_URL}"))

    class FakeImageClient:
        def __init__(self):
            self.received_prompt = None

        def generate_image(self, prompt):
            self.received_prompt = prompt
            return b"fake-png-bytes"

    fake_image_client = FakeImageClient()
    monkeypatch.setattr(publish, "_image_client", lambda cfg: fake_image_client)

    publish_dir = publish.publish_section(cfg, tmp_path, 1)

    assert publish_dir == tmp_path / "publish" / "01_introduction"
    html = (publish_dir / "article.html").read_text(encoding="utf-8")
    assert "<strong>important</strong>" in html
    assert (publish_dir / "post.txt").read_text(encoding="utf-8") == "Mon post.\n{ARTICLE_URL}\n"
    assert (publish_dir / "cover.png").read_bytes() == b"fake-png-bytes"
    assert "Introduction" in fake_image_client.received_prompt


def test_publish_section_skips_image_when_disabled(tmp_path, cfg, monkeypatch):
    state = make_state()
    section = state.section_by_numero(1)
    section.status = "done"
    save_state(tmp_path, state)
    (tmp_path / section.filename).write_text("## 1. Introduction\n\ncontenu\n", encoding="utf-8")

    monkeypatch.setattr(publish, "_write_client", lambda cfg: FakeChatClient("post.\n{ARTICLE_URL}"))

    def _fail_image_client(cfg):
        raise AssertionError("model_image ne doit pas être sollicité quand generate_image=False")

    monkeypatch.setattr(publish, "_image_client", _fail_image_client)

    publish_dir = publish.publish_section(cfg, tmp_path, 1, generate_image=False)

    assert not (publish_dir / "cover.png").exists()
    assert (publish_dir / "article.html").exists()
    assert (publish_dir / "post.txt").exists()
