"""Préparation de la publication quotidienne d'un chapitre sur LinkedIn.

Pour une section déjà rédigée (`status == "done"`) : rend le Markdown en
page HTML prête à copier dans l'éditeur d'article LinkedIn, génère un
brouillon de post d'accroche via le modèle rédacteur (`model_write`), et
(optionnellement) un visuel de couverture via le modèle de génération
d'image (`model_image`). La création de l'Article LinkedIn lui-même et sa
publication restent manuelles : l'API LinkedIn ne permet pas de créer des
Articles, seulement des posts courts.
"""

from __future__ import annotations

import string
from pathlib import Path

import markdown as md

from .config import AppConfig
from .providers import OllamaCloudClient, OpenAIImageClient
from .state import SectionState, load_state

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

HTML_TEMPLATE = string.Template(
    """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>$titre</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; max-width: 700px; margin: 40px auto; line-height: 1.6; color: #1a1a1a; padding: 0 16px; }
  h1, h2, h3 { line-height: 1.3; }
  code { background: #f2f2f2; padding: 2px 4px; border-radius: 3px; }
  blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 12px; color: #555; }
  table { border-collapse: collapse; }
  td, th { border: 1px solid #ccc; padding: 6px 10px; }
</style>
</head>
<body>
$body
</body>
</html>
"""
)


class PublishError(Exception):
    """Section non publiable (pas encore terminée)."""


def render_article_html(markdown_text: str, titre: str) -> str:
    """Convertit le Markdown d'une section en page HTML autonome, prête à copier.

    LinkedIn ne supporte pas la syntaxe Markdown tapée telle quelle dans son
    éditeur d'article ; en revanche, coller du texte déjà mis en forme (issu
    d'une page HTML rendue) y conserve généralement le gras, les titres et
    les listes. Les tableaux, en revanche, passent mal au collage et
    peuvent nécessiter une reprise manuelle.

    Args:
        markdown_text: Contenu Markdown de la section (fichier `NN_slug.md`).
        titre: Titre du chapitre, utilisé comme `<title>` de la page.

    Returns:
        Une page HTML complète, à ouvrir dans un navigateur pour sélection et copie.
    """
    body_html = md.markdown(markdown_text, extensions=["extra", "tables", "sane_lists"])
    return HTML_TEMPLATE.substitute(titre=titre, body=body_html)


def build_image_prompt(manual_titre: str, section: SectionState) -> str:
    """Construit un prompt déterministe pour le visuel de couverture du chapitre.

    Le prompt combine le sujet du chapitre et une direction artistique fixe,
    pour une identité visuelle cohérente d'un jour de publication à l'autre.

    Args:
        manual_titre: Titre général du manuel.
        section: Section publiée (titre, description, numéro).

    Returns:
        Un prompt texte à envoyer au modèle de génération d'image.
    """
    return (
        f"Couverture d'article professionnelle pour un post LinkedIn, chapitre {section.numero} "
        f"d'un manuel intitulé « {manual_titre} ». Sujet du chapitre : {section.titre} — {section.description}. "
        "Style : illustration minimaliste et moderne, palette sobre (bleu nuit, blanc, un accent), "
        "sans texte ni typographie dans l'image, composition épurée adaptée à un visuel de couverture LinkedIn 16:9."
    )


def _read_prompt(name: str) -> str:
    """Lit le contenu d'un fichier de prompt depuis `prompts/`.

    Args:
        name: Nom du fichier (ex: `"linkedin_post_instruction.md"`).

    Returns:
        Le contenu texte du fichier.
    """
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def generate_post_draft(client, manual_titre: str, section: SectionState) -> str:
    """Génère un brouillon de post LinkedIn annonçant le chapitre publié.

    Args:
        client: Client de chat du rôle `model_write` (ex: `OllamaCloudClient`).
        manual_titre: Titre général du manuel.
        section: Section publiée.

    Returns:
        Le texte brut du post, avec le jeton `{ARTICLE_URL}` à remplacer
        manuellement par le lien de l'article une fois celui-ci publié sur LinkedIn.
    """
    template = string.Template(_read_prompt("linkedin_post_instruction.md"))
    instruction = template.substitute(
        manual_titre=manual_titre,
        numero=section.numero,
        titre=section.titre,
        description=section.description,
    )
    return client.chat([{"role": "user", "content": instruction}]).strip()


def _write_client(cfg: AppConfig) -> OllamaCloudClient:
    """Construit le client LLM du rôle `model_write`.

    Args:
        cfg: Configuration applicative résolue.

    Returns:
        Un client prêt à générer le brouillon de post.
    """
    return OllamaCloudClient(cfg.role("model_write"), role="model_write")


def _image_client(cfg: AppConfig) -> OpenAIImageClient:
    """Construit le client de génération d'image du rôle `model_image`.

    Args:
        cfg: Configuration applicative résolue.

    Returns:
        Un client prêt à générer le visuel de couverture.

    Raises:
        ConfigError: Si le rôle `model_image` n'est pas configuré dans `params.yml`.
    """
    return OpenAIImageClient(cfg.role("model_image"), role="model_image")


def publish_section(
    cfg: AppConfig,
    output_dir: Path,
    numero: int,
    *,
    generate_image: bool = True,
) -> Path:
    """Prépare le paquet de publication quotidien d'un chapitre.

    Écrit dans `output_dir/publish/<slug_du_chapitre>/` : `article.html`
    (contenu prêt à copier dans l'éditeur d'article LinkedIn), `post.txt`
    (brouillon de post d'accroche) et, sauf si `generate_image` est faux,
    `cover.png` (visuel de couverture généré par IA). La publication finale
    (créer l'Article, coller le contenu, poster le lien) reste manuelle.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        numero: Numéro du chapitre à publier.
        generate_image: Si `True` (défaut), génère aussi le visuel de
            couverture via le rôle `model_image` (nécessite ce rôle
            configuré dans `params.yml` ; sinon, la génération d'image est
            simplement ignorée sans y toucher).

    Returns:
        Le répertoire contenant les fichiers préparés.

    Raises:
        PublishError: Si la section n'est pas encore terminée (`status != "done"`).
        KeyError: Si `numero` ne correspond à aucune section connue.
        ConfigError: Si `generate_image` est demandé sans que le rôle
            `model_image` soit configuré.
        ProviderError: Si un appel LLM échoue définitivement.
    """
    state = load_state(output_dir)
    section = state.section_by_numero(numero)
    if section.status != "done":
        raise PublishError(
            f"La section {numero} n'est pas terminée (statut : {section.status!r}). "
            "Lance `manual write` ou `manual redo` avant de la publier."
        )

    publish_dir = output_dir / "publish" / section.filename.removesuffix(".md")
    publish_dir.mkdir(parents=True, exist_ok=True)

    markdown_text = (output_dir / section.filename).read_text(encoding="utf-8")
    html = render_article_html(markdown_text, section.titre)
    (publish_dir / "article.html").write_text(html, encoding="utf-8")

    post_draft = generate_post_draft(_write_client(cfg), state.titre_manuel, section)
    (publish_dir / "post.txt").write_text(post_draft + "\n", encoding="utf-8")

    if generate_image:
        prompt = build_image_prompt(state.titre_manuel, section)
        image_bytes = _image_client(cfg).generate_image(prompt)
        (publish_dir / "cover.png").write_bytes(image_bytes)

    return publish_dir
