"""Mémoire glissante du manuel, pour assurer la cohérence entre sections.

Plutôt que de renvoyer tout le manuel déjà rédigé à chaque appel (ce qui
saturerait rapidement la fenêtre de contexte), un résumé condensé
(« digest ») est maintenu dans `memory.md` et mis à jour par le modèle
`model_think` après chaque section acceptée. Il est automatiquement
recompressé s'il dépasse `MAX_DIGEST_CHARS`.
"""

from __future__ import annotations

from pathlib import Path

from .providers import OllamaCloudClient

MEMORY_FILENAME = "memory.md"
MAX_DIGEST_CHARS = 6000  # ~1500 tokens, seuil avant recompression forcée
INITIAL_DIGEST = "(Aucune section rédigée pour l'instant.)"

UPDATE_PROMPT = """# Tâche : mettre à jour la mémoire du manuel

Voici le résumé mémoire actuel du manuel en cours de rédaction, suivi de la section qui vient d'être validée.
Mets à jour ce résumé pour qu'il reste utile aux sections suivantes, en 400 mots maximum. Il doit contenir :
- les termes et concepts déjà définis (liste courte, 1 ligne chacun) ;
- les décisions de terminologie ou de style à respecter ;
- les exemples déjà utilisés, à ne pas répéter à l'identique ;
- une phrase de continuité sur ce que le manuel vient de couvrir.

Réponds uniquement avec le résumé mis à jour, en texte brut ou Markdown léger, sans préambule ni commentaire.

## Résumé actuel
{digest}

## Section qui vient d'être validée
{section_text}
"""

COMPRESS_PROMPT = """Le résumé mémoire suivant est trop long. Compresse-le à 400 mots maximum en gardant \
uniquement l'essentiel (termes définis, décisions de style, continuité).

{digest}
"""


def memory_path(output_dir: Path) -> Path:
    """Calcule le chemin du fichier de mémoire pour un répertoire de sortie donné.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le chemin `output_dir / "memory.md"`.
    """
    return output_dir / MEMORY_FILENAME


def load_digest(output_dir: Path) -> str:
    """Charge le résumé mémoire courant.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        Le contenu de `memory.md`, ou `INITIAL_DIGEST` si le fichier
        n'existe pas encore (avant la première section rédigée).
    """
    path = memory_path(output_dir)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return INITIAL_DIGEST


def save_digest(output_dir: Path, digest: str) -> None:
    """Sauvegarde le résumé mémoire courant.

    Args:
        output_dir: Répertoire de sortie du manuel.
        digest: Contenu à écrire dans `memory.md`.
    """
    memory_path(output_dir).write_text(digest, encoding="utf-8")


def update_digest(
    client: OllamaCloudClient,
    current_digest: str,
    section_title: str,
    section_text: str,
) -> str:
    """Demande au modèle mémoire une version mise à jour du résumé.

    Args:
        client: Client LLM du rôle `model_think`.
        current_digest: Résumé mémoire avant intégration de la nouvelle section.
        section_title: Titre de la section qui vient d'être validée (non
            utilisé dans le prompt actuel, conservé pour le contexte appelant).
        section_text: Texte final de la section validée à intégrer au résumé.

    Returns:
        Le résumé mis à jour, ou `current_digest` inchangé si le modèle a
        répondu une chaîne vide.
    """
    prompt = UPDATE_PROMPT.format(digest=current_digest, section_text=section_text)
    new_digest = client.chat([{"role": "user", "content": prompt}]).strip()
    return new_digest or current_digest


def ensure_budget(client: OllamaCloudClient, digest: str) -> str:
    """Recompresse le résumé mémoire s'il dépasse le budget de taille.

    Args:
        client: Client LLM du rôle `model_think`.
        digest: Résumé mémoire courant.

    Returns:
        `digest` inchangé s'il tient dans `MAX_DIGEST_CHARS` ; sinon une
        version compressée par le modèle, ou à défaut `digest` tronqué à
        `MAX_DIGEST_CHARS` si le modèle répond une chaîne vide.
    """
    if len(digest) <= MAX_DIGEST_CHARS:
        return digest
    compressed = client.chat(
        [{"role": "user", "content": COMPRESS_PROMPT.format(digest=digest)}]
    ).strip()
    return compressed or digest[:MAX_DIGEST_CHARS]
