"""Interface en ligne de commande du générateur de manuel (`manual`).

Sous-commandes : `init` (génère la table des matières), `write`
(rédige les sections en attente ou une sélection via `-s`), `status`
(affiche l'avancement), `redo` (régénère une section précise), `publish`
(prépare le paquet de publication LinkedIn d'un chapitre terminé),
`traces` (interface web de visualisation des appels LLM journalisés) et
`subject` (liste, crée et contrôle les sujets de manuel).

Le sujet traité se choisit avec `--subject` (facultatif s'il n'en existe
qu'un) ; le manuel est écrit dans `output/<sujet>/` sauf `--output`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import tracing
from .config import ConfigError, load_config
from .generator import GeneratorError, generate_toc, run_write
from .parsing import ParsingError
from .patterns import PatternError, parse_section_patterns
from .providers import ProviderError
from .publish import PublishError, publish_section
from .requirements_loader import RequirementsError
from .state import load_state, state_exists
from .subjects import (
    SUBJECTS_DIR,
    Subject,
    SubjectError,
    list_subjects,
    load_subject,
    resolve_slug,
    scaffold_subject,
)

try:
    from .web.app import create_app
except ImportError:  # pragma: no cover - flask non installé (extra optionnel "web")
    create_app = None

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "output"


def _load_subject(args: argparse.Namespace) -> Subject:
    """Charge le sujet demandé par `--subject` (ou l'unique sujet existant).

    Args:
        args: Arguments parsés (`subject`).

    Returns:
        Le sujet chargé et validé.

    Raises:
        SubjectError: Si le sujet est inconnu, ambigu ou invalide.
    """
    return load_subject(resolve_slug(args.subject, SUBJECTS_DIR), SUBJECTS_DIR)


def _output_dir(args: argparse.Namespace, subject: Subject | None = None) -> Path:
    """Détermine le répertoire de sortie du manuel.

    Args:
        args: Arguments parsés (`output`, `subject`).
        subject: Sujet déjà chargé, s'il l'a été (évite de le résoudre deux fois).

    Returns:
        `--output` s'il est fourni ; sinon `output/<identifiant du sujet>`.

    Raises:
        SubjectError: Si `--output` est absent et que le sujet ne peut pas
            être déterminé.
    """
    if args.output:
        return Path(args.output)
    slug = subject.slug if subject is not None else resolve_slug(args.subject, SUBJECTS_DIR)
    return DEFAULT_OUTPUT_ROOT / slug


def cmd_init(args: argparse.Namespace) -> int:
    """Génère la table des matières et initialise l'état du manuel.

    Args:
        args: Arguments parsés (`output`, `force`).

    Returns:
        `0` en cas de succès, `1` si une table des matières existe déjà et
        que `--force` n'a pas été passé.
    """
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    if state_exists(output_dir) and not args.force:
        print(f"Une table des matières existe déjà dans {output_dir}. Utilise --force pour la régénérer.")
        return 1
    tracing.configure(output_dir)
    cfg = load_config()
    state = generate_toc(cfg, output_dir, subject)
    print(f"Table des matières générée : {len(state.sections)} chapitres. Voir {output_dir / '00_toc.md'}")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    """Rédige les sections en attente, ou une sélection donnée via `-s`.

    Args:
        args: Arguments parsés (`output`, `section`, `max_rewrite`, `worker`).

    Returns:
        Toujours `0` (les échecs de sections individuelles sont reportés
        dans la sortie, pas dans le code de retour).

    Raises:
        PatternError: Propagée si `args.section` contient un motif invalide
            (capturée par `main`).
    """
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    only_numeros = parse_section_patterns(args.section) if args.section else None
    results = run_write(
        cfg, output_dir, subject, only_numeros=only_numeros, max_rewrite=args.max_rewrite, workers=args.worker
    )
    if not results:
        print("Rien à rédiger : toutes les sections sont déjà terminées.")
        return 0
    for section in results:
        status = "OK" if section.status == "done" else "A REVOIR"
        print(f"[{status}] {section.numero}. {section.titre} (tentatives: {section.attempts})")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Affiche l'avancement de la génération du manuel.

    Args:
        args: Arguments parsés (`output`).

    Returns:
        `0` si un manifeste existe, `1` sinon.
    """
    output_dir = _output_dir(args)
    if not state_exists(output_dir):
        print("Aucune table des matières générée. Lance `manual init`.")
        return 1
    state = load_state(output_dir)
    for section in state.sections:
        print(f"{section.numero:>2}. [{section.status:<7}] {section.titre}")
    done = sum(1 for s in state.sections if s.status == "done")
    print(f"\n{done}/{len(state.sections)} sections terminées.")
    return 0


def cmd_redo(args: argparse.Namespace) -> int:
    """Régénère une section précise depuis zéro.

    Args:
        args: Arguments parsés (`output`, `numero`, `max_rewrite`).

    Returns:
        Toujours `0` (voir `cmd_write`).
    """
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    results = run_write(cfg, output_dir, subject, only_numeros=[args.numero], max_rewrite=args.max_rewrite, workers=1)
    for section in results:
        status = "OK" if section.status == "done" else "A REVOIR"
        print(f"[{status}] {section.numero}. {section.titre} (tentatives: {section.attempts})")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Prépare le paquet de publication LinkedIn d'un chapitre terminé.

    Args:
        args: Arguments parsés (`output`, `numero`, `no_image`).

    Returns:
        `0` en cas de succès.

    Raises:
        PublishError: Propagée si la section n'est pas terminée (capturée par `main`).
    """
    cfg = load_config()
    output_dir = _output_dir(args)
    tracing.configure(output_dir)
    publish_dir = publish_section(cfg, output_dir, args.numero, generate_image=not args.no_image)
    print(f"Paquet de publication prêt : {publish_dir}")
    print("  - article.html : à ouvrir puis coller dans l'éditeur d'article LinkedIn")
    print("  - post.txt     : brouillon de post (remplace {ARTICLE_URL} par le lien de l'article)")
    if not args.no_image:
        print("  - cover.png    : visuel de couverture à joindre manuellement")
    return 0


def cmd_traces(args: argparse.Namespace) -> int:
    """Lance l'interface web de visualisation des traces d'appels LLM.

    Args:
        args: Arguments parsés (`output`, `host`, `port`).

    Returns:
        `1` si Flask n'est pas installé (extra optionnel `web`). Sinon ne
        retourne pas en fonctionnement normal : le serveur bloque le
        processus jusqu'à interruption (Ctrl+C).
    """
    if create_app is None:
        print(
            "L'interface web nécessite Flask. Installe-le avec : pip install -e '.[web]'",
            file=sys.stderr,
        )
        return 1

    output_dir = _output_dir(args)
    trace_path = output_dir / tracing.TRACE_RELATIVE_PATH
    app = create_app(trace_path)
    print(f"Interface de traces sur http://{args.host}:{args.port} (Ctrl+C pour arrêter)")
    print(f"Fichier de trace : {trace_path}")
    app.run(host=args.host, port=args.port)
    return 0


def cmd_subject_list(args: argparse.Namespace) -> int:
    """Liste les sujets disponibles avec leur titre.

    Args:
        args: Arguments parsés (inutilisés).

    Returns:
        Toujours `0` ; un sujet invalide est signalé dans la liste.
    """
    slugs = list_subjects(SUBJECTS_DIR)
    if not slugs:
        print("Aucun sujet. Crée-en un avec `manual subject new <identifiant>`.")
        return 0
    for slug in slugs:
        try:
            print(f"{slug:<28} {load_subject(slug, SUBJECTS_DIR).titre}")
        except SubjectError:
            print(f"{slug:<28} INVALIDE (détail : `manual subject check {slug}`)")
    return 0


def cmd_subject_new(args: argparse.Namespace) -> int:
    """Crée le squelette d'un nouveau sujet.

    Args:
        args: Arguments parsés (`slug`).

    Returns:
        `0` en cas de succès.

    Raises:
        SubjectError: Si l'identifiant est invalide ou déjà pris (capturée par `main`).
    """
    directory = scaffold_subject(args.slug, SUBJECTS_DIR)
    print(f"Sujet créé : {directory}")
    print(f"  1. Remplis {directory / 'subject.yml'} (les champs « À COMPLÉTER »).")
    print(f"  2. Ajoute au besoin tes critères dans {directory / 'requirements.yml'}.")
    print(f"  3. Vérifie avec : manual subject check {args.slug}")
    return 0


def cmd_subject_check(args: argparse.Namespace) -> int:
    """Valide un sujet et vérifie que ses prompts et critères se construisent.

    Args:
        args: Arguments parsés (`slug`, `show`).

    Returns:
        `0` si le sujet est complet et cohérent.

    Raises:
        SubjectError: Si le sujet est incomplet ou mal formé (capturée par `main`).
    """
    subject = load_subject(resolve_slug(args.slug, SUBJECTS_DIR), SUBJECTS_DIR)
    system_prompt = subject.system_prompt()
    toc_instruction = subject.toc_instruction()
    requirements = subject.requirements()
    blocking = sum(1 for c in requirements["generic"] if c["severity"] == "bloquant")
    print(f"Sujet {subject.slug!r} valide : {subject.titre} ({subject.langue}).")
    print(f"  - {len(requirements['generic'])} critères communs ({blocking} bloquants)")
    print(f"  - {len(requirements['parties'])} partie(s) avec critères propres")
    print(f"  - prompt système : {len(system_prompt)} caractères, instruction de plan : {len(toc_instruction)}")
    if args.show:
        print("\n===== Prompt système =====\n")
        print(system_prompt)
        print("\n===== Instruction de plan =====\n")
        print(toc_instruction)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments du CLI `manual`.

    Returns:
        Le parseur configuré avec toutes les sous-commandes
        (`init`, `write`, `status`, `redo`, `publish`, `traces`, `subject`).
    """
    parser = argparse.ArgumentParser(
        prog="manual", description="Génère le manuel de Prompt Engineering section par section."
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Sujet du manuel (dossier de `subjects/`). Facultatif s'il n'en existe qu'un.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Répertoire de sortie du manuel (défaut : output/<sujet>).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Génère la table des matières.")
    p_init.add_argument("--force", action="store_true", help="Régénère la TOC même si elle existe déjà.")
    p_init.set_defaults(func=cmd_init)

    p_write = sub.add_parser("write", help="Rédige les sections en attente (ou une sélection de sections).")
    p_write.add_argument(
        "-s",
        "--section",
        nargs="+",
        default=None,
        metavar="N",
        help=(
            "Numéros et/ou intervalles de sections à rédiger, ex: -s 1 3 5-8. "
            "Par défaut : toutes les sections en attente."
        ),
    )
    p_write.add_argument("--max-rewrite", type=int, default=2, help="Nombre max de réécritures après rejet du juge.")
    p_write.add_argument("-w", "--worker", type=int, default=4, help="Nombre de workers en parallèle (défaut : 4).")
    p_write.set_defaults(func=cmd_write)

    p_status = sub.add_parser("status", help="Affiche l'avancement.")
    p_status.set_defaults(func=cmd_status)

    p_redo = sub.add_parser("redo", help="Régénère une section précise depuis zéro.")
    p_redo.add_argument("numero", type=int)
    p_redo.add_argument("--max-rewrite", type=int, default=2)
    p_redo.set_defaults(func=cmd_redo)

    p_publish = sub.add_parser(
        "publish", help="Prépare le paquet de publication LinkedIn d'un chapitre terminé (article, post, visuel)."
    )
    p_publish.add_argument("numero", type=int, help="Numéro du chapitre à publier.")
    p_publish.add_argument(
        "--no-image", action="store_true", help="Ne génère pas de visuel de couverture (rôle model_image ignoré)."
    )
    p_publish.set_defaults(func=cmd_publish)

    p_traces = sub.add_parser("traces", help="Lance l'interface web de visualisation des appels LLM journalisés.")
    p_traces.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute (défaut : 127.0.0.1).")
    p_traces.add_argument("--port", type=int, default=8787, help="Port d'écoute (défaut : 8787).")
    p_traces.set_defaults(func=cmd_traces)

    p_subject = sub.add_parser("subject", help="Gère les sujets de manuel (liste, création, contrôle).")
    subject_sub = p_subject.add_subparsers(dest="subject_command", required=True)

    p_subject_list = subject_sub.add_parser("list", help="Liste les sujets disponibles.")
    p_subject_list.set_defaults(func=cmd_subject_list)

    p_subject_new = subject_sub.add_parser("new", help="Crée le squelette d'un nouveau sujet.")
    p_subject_new.add_argument("slug", help="Identifiant du sujet : minuscules, chiffres et tirets.")
    p_subject_new.set_defaults(func=cmd_subject_new)

    p_subject_check = subject_sub.add_parser("check", help="Valide un sujet et ses prompts.")
    p_subject_check.add_argument("slug", nargs="?", default=None, help="Sujet à contrôler (défaut : l'unique sujet).")
    p_subject_check.add_argument("--show", action="store_true", help="Affiche les prompts tels qu'ils seront envoyés.")
    p_subject_check.set_defaults(func=cmd_subject_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée du CLI.

    Args:
        argv: Arguments de ligne de commande, ou `None` pour utiliser
            `sys.argv` (comportement par défaut d'argparse).

    Returns:
        Le code de sortie du processus (`0` succès, `1` erreur connue).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (
        ConfigError,
        GeneratorError,
        ParsingError,
        PatternError,
        ProviderError,
        PublishError,
        RequirementsError,
        SubjectError,
    ) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
