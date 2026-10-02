"""Interface en ligne de commande du générateur de manuel (`manual`).

Sous-commandes : `init` (génère la table des matières), `write`
(rédige les sections en attente ou une sélection via `-s`), `status`
(affiche l'avancement), `redo` (régénère une section précise), `improve`
(améliore des sections déjà écrites, avec une consigne facultative),
`improve-toc` (améliore la table des matières en préservant l'existant), `publish`
(prépare le paquet de publication LinkedIn d'un chapitre terminé),
`traces` (interface web de visualisation des appels LLM journalisés) et
`subject` (liste, crée, retouche, édite, contrôle et supprime les sujets de manuel,
dont trois opérations assistées par LLM : création depuis un descriptif,
retouche par consigne et critères par partie).

Le sujet traité se choisit avec `--subject` (facultatif s'il n'en existe
qu'un) ; le manuel est écrit dans `output/<sujet>/` sauf `--output`.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from . import tracing
from .config import ConfigError, load_config
from .generator import GeneratorError, generate_toc, improve_toc, run_improve, run_write
from .glossary import build_glossary
from .parsing import ParsingError
from .patterns import PatternError, parse_section_patterns
from .providers import ProviderError
from .publish import PublishError, publish_section
from .requirements_loader import RequirementsError
from .sources import (
    SOURCES_DIRNAME,
    SUFFIXES,
    SourcesError,
    list_source_files,
    load_index,
    refresh_index,
    subject_context,
)
from .sources_assign import ensure_assignment, load_map, orphan_units, render_sources
from .state import StateError, load_state, state_exists
from .subject_author import generate_subject, propose_partie_criteria, refine_subject
from .subjects import (
    SUBJECT_FILENAME,
    SUBJECTS_DIR,
    Subject,
    SubjectError,
    delete_subject,
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
        coverage = ""
        if section.sources_total:
            coverage = (
                f"  — sources : {section.sources_total - len(section.sources_ecartees)}/{section.sources_total} traitées, "
                f"{len(section.sources_ecartees)} écartée(s)"
            )
        print(f"{section.numero:>2}. [{section.status:<7}] {section.titre}{coverage}")
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


def cmd_improve(args: argparse.Namespace) -> int:
    """Améliore des sections déjà écrites, en s'en servant d'amorce pour une nouvelle génération.

    Args:
        args: Arguments parsés (`sections`, `instruction`, `instruction_file`,
            `max_rewrite`, `worker`).

    Returns:
        Toujours `0` (une version non retenue est reportée dans la sortie).

    Raises:
        PatternError: Si un motif de section est invalide (capturée par `main`).
        SubjectError: Si la consigne est donnée deux fois ou illisible (capturée par `main`).
        GeneratorError: Si une section n'a pas encore de contenu (capturée par `main`).
    """
    only_numeros = parse_section_patterns(args.sections)
    instruction = _text_argument(args.instruction, args.instruction_file, "consigne", "instruction-file")
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    results = run_improve(
        cfg,
        output_dir,
        subject,
        only_numeros=only_numeros,
        instruction=instruction,
        max_rewrite=args.max_rewrite,
        workers=args.worker,
    )
    for result in results:
        section = result.section
        if result.accepted:
            print(f"[OK] {section.numero}. {section.titre} : améliorée (ancienne version : {result.backup})")
        else:
            print(
                f"[NON RETENU] {section.numero}. {section.titre} : la nouvelle version n'a pas passé la relecture ; "
                f"l'original est conservé, version candidate dans {result.path}"
            )
    return 0


def cmd_glossary(args: argparse.Namespace) -> int:
    """Génère `glossaire.md` à partir des chapitres terminés.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        `0` en cas de succès.

    Raises:
        GeneratorError: Si aucun chapitre n'est terminé (capturée par `main`).
        SubjectError: Si le sujet ne peut pas être déterminé (capturée par `main`).
    """
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    result = build_glossary(cfg, output_dir, system_prompt=subject.system_prompt())
    print(f"Glossaire écrit : {len(result.entries)} termes, issus des chapitres {', '.join(map(str, result.chapters))} → {result.path}")
    return 0


def cmd_improve_toc(args: argparse.Namespace) -> int:
    """Améliore la table des matières en partant de l'actuelle, sans rien perdre.

    Args:
        args: Arguments parsés (`instruction`, `instruction_file`).

    Returns:
        `0` en cas de succès (y compris si le modèle ne change rien).

    Raises:
        SubjectError: Si la consigne est donnée deux fois ou illisible (capturée par `main`).
        GeneratorError: Si aucun manifeste n'existe ou s'il est d'un autre sujet (capturée par `main`).
    """
    instruction = _text_argument(args.instruction, args.instruction_file, "consigne", "instruction-file")
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    result = improve_toc(cfg, output_dir, subject, instruction)
    if not result.modified:
        print("Aucun changement : le modèle a jugé la table des matières satisfaisante.")
        return 0
    print(f"Table des matières améliorée. Version précédente archivée dans {result.history_dir}")
    for section in result.changed:
        print(f"  - à (re)rédiger : {section.numero}. {section.titre}")
    for section in result.removed:
        print(f"  - retiré : {section.numero}. {section.titre}")
    if result.orphan_files:
        print(f"Fichiers de chapitres non repris (laissés en place) : {', '.join(result.orphan_files)}")
    if result.orphan_criteria:
        print(
            f"Critères de parties sans correspondance : {', '.join(result.orphan_criteria)} "
            "(relance `manual subject criteria --force` ou corrige requirements.yml)"
        )
    print(f"Relis {output_dir / '00_toc.md'}, puis `manual write`.")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Prépare le paquet de publication LinkedIn d'un chapitre terminé.

    Args:
        args: Arguments parsés (`output`, `numero`, `no_image`).

    Returns:
        `0` en cas de succès.

    Raises:
        PublishError: Propagée si la section n'est pas terminée (capturée par `main`).
        SubjectError: Si le sujet ne peut pas être déterminé (capturée par `main`).
    """
    cfg = load_config()
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    publish_dir = publish_section(
        cfg, output_dir, args.numero, system_prompt=subject.system_prompt(), generate_image=not args.no_image
    )
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


def _text_argument(inline: str | None, file: str | None, what: str, flag: str) -> str | None:
    """Lit un texte long donné soit en argument, soit dans un fichier (`-` = entrée standard).

    Args:
        inline: Texte passé directement sur la ligne de commande, ou `None`.
        file: Chemin d'un fichier texte UTF-8 (ou `-` pour l'entrée standard), ou `None`.
        what: Nom de l'élément pour les messages d'erreur (ex. « descriptif »).
        flag: Nom de l'option fichier correspondante (ex. `brief-file`).

    Returns:
        Le texte, ou `None` si ni `inline` ni `file` n'est fourni.

    Raises:
        SubjectError: Si les deux sont fournis, ou si le fichier est illisible
            ou n'est pas de l'UTF-8.
    """
    if inline is not None and file is not None:
        raise SubjectError(f"Donne le {what} soit en argument, soit avec --{flag}, pas les deux.")
    if file is None:
        return inline
    if file == "-":
        return sys.stdin.read()
    try:
        return Path(file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SubjectError(f"Lecture impossible de {file} : {exc}") from exc


def cmd_subject_new(args: argparse.Namespace) -> int:
    """Crée un nouveau sujet : squelette à remplir, ou rédigé par le LLM depuis un descriptif.

    Args:
        args: Arguments parsés (`slug`, `brief`, `brief_file`).

    Returns:
        `0` en cas de succès.

    Raises:
        SubjectError: Si l'identifiant est invalide ou déjà pris, ou si le
            descriptif est donné deux fois ou illisible (capturée par `main`).
    """
    brief = _text_argument(args.brief, args.brief_file, "descriptif", "brief-file")
    if brief is not None:
        directory = generate_subject(load_config(), args.slug, brief, SUBJECTS_DIR)
        print(f"Sujet créé et rédigé par le modèle : {directory}")
        print(f"  - Relis-le : manual subject check {args.slug} --show")
        print(f'  - Retouche-le : manual subject refine {args.slug} "ta consigne"  (ou manual subject edit {args.slug})')
        print(f"  - Puis génère le plan : manual --subject {args.slug} init")
        return 0
    directory = scaffold_subject(args.slug, SUBJECTS_DIR)
    print(f"Sujet créé : {directory}")
    print(f"  1. Remplis {directory / SUBJECT_FILENAME} (les champs « À COMPLÉTER »), ou lance : manual subject edit {args.slug}")
    print(f"  2. Ajoute au besoin tes critères dans {directory / 'requirements.yml'}.")
    print(f"  3. Vérifie avec : manual subject check {args.slug}")
    return 0


def cmd_subject_refine(args: argparse.Namespace) -> int:
    """Retouche un sujet existant selon une consigne en langage naturel.

    Args:
        args: Arguments parsés (`slug`, `instruction`, `instruction_file`).

    Returns:
        `0` en cas de succès (y compris si le modèle n'a rien changé).

    Raises:
        SubjectError: Si le sujet est introuvable ou invalide, ou si la
            consigne est absente, donnée deux fois ou illisible (capturée par `main`).
    """
    instruction = _text_argument(args.instruction, args.instruction_file, "consigne", "instruction-file")
    if instruction is None:
        raise SubjectError("Donne la consigne en argument ou avec --instruction-file (`-f`).")
    changed = refine_subject(load_config(), args.slug, instruction, SUBJECTS_DIR)
    if not changed:
        print("Aucun changement : le modèle a jugé que le sujet répondait déjà à la consigne.")
        return 0
    path = SUBJECTS_DIR / args.slug / SUBJECT_FILENAME
    print(f"Champs modifiés : {', '.join(changed)}")
    print(f"  - Ancienne version conservée : {path}.bak")
    print(f"  - Relis le résultat : manual subject check {args.slug} --show")
    return 0


def _confirm(question: str) -> bool:
    """Pose une question fermée sur le terminal.

    Args:
        question: Question affichée, sans la mention des réponses possibles.

    Returns:
        `True` seulement pour une réponse explicite « o », « oui », « y » ou « yes » ;
        toute autre réponse, ou l'absence d'entrée standard, vaut refus.
    """
    try:
        answer = input(f"{question} [o/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("o", "oui", "y", "yes")


def cmd_subject_delete(args: argparse.Namespace) -> int:
    """Supprime un sujet, après confirmation, et facultativement son manuel généré.

    Args:
        args: Arguments parsés (`slug`, `yes`, `with_output`, `output`).

    Returns:
        `0` si le sujet est supprimé, `1` si la suppression est annulée.

    Raises:
        SubjectError: Si le sujet est inconnu, ou si `--with-output` est combiné
            avec l'option globale `--output` (capturée par `main`).
    """
    if args.with_output and args.output:
        raise SubjectError("--with-output ne supprime que output/<sujet>/ : retire l'option --output.")
    slug = resolve_slug(args.slug, SUBJECTS_DIR)
    manual_dir = DEFAULT_OUTPUT_ROOT / slug
    remove_manual = args.with_output and manual_dir.is_dir()
    if not args.yes:
        question = f"Supprimer définitivement le sujet {slug!r} ({SUBJECTS_DIR / slug})"
        question += f" et son manuel généré ({manual_dir}) ?" if remove_manual else " ?"
        if not _confirm(question):
            print("Suppression annulée (utilise --yes pour confirmer sans question).", file=sys.stderr)
            return 1
    delete_subject(slug, SUBJECTS_DIR)
    print(f"Sujet {slug!r} supprimé.")
    if remove_manual:
        shutil.rmtree(manual_dir)
        print(f"Manuel généré supprimé : {manual_dir}")
    elif manual_dir.is_dir():
        print(f"Le manuel généré est conservé : {manual_dir} (à supprimer avec --with-output, ou à la main).")
    return 0


def cmd_subject_criteria(args: argparse.Namespace) -> int:
    """Propose des critères de relecture par partie de la table des matières générée.

    Args:
        args: Arguments parsés (`slug`, `force`, `subject`, `output`).

    Returns:
        `0` en cas de succès (y compris si rien n'est ajouté).

    Raises:
        SubjectError: Si aucune table des matières n'existe pour ce sujet (capturée par `main`).
    """
    subject = load_subject(resolve_slug(args.slug or args.subject, SUBJECTS_DIR), SUBJECTS_DIR)
    output_dir = _output_dir(args, subject)
    tracing.configure(output_dir)
    added = propose_partie_criteria(load_config(), subject, output_dir, force=args.force)
    if not added:
        print("Aucun critère ajouté (parties déjà pourvues, ou rien de spécifique à proposer). --force remplace l'existant.")
        return 0
    for partie, ids in added.items():
        print(f"  - {partie} : {', '.join(ids)}")
    print(f"Critères enregistrés dans {subject.directory / 'requirements.yml'} (sauvegarde : .bak).")
    print(f"Relance ensuite : manual --subject {subject.slug} write")
    return 0


def cmd_subject_edit(args: argparse.Namespace) -> int:
    """Ouvre le `subject.yml` d'un sujet dans l'éditeur, puis le valide.

    Args:
        args: Arguments parsés (`slug`, `subject`).

    Returns:
        `0` si le sujet est valide après édition.

    Raises:
        SubjectError: Si aucun éditeur n'est défini (`VISUAL`/`EDITOR`), s'il
            est introuvable ou échoue, ou si le sujet est invalide après édition.
    """
    slug = resolve_slug(args.slug or args.subject, SUBJECTS_DIR)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        raise SubjectError("Aucun éditeur : définis la variable d'environnement EDITOR (ex. export EDITOR=nano).")
    path = SUBJECTS_DIR / slug / SUBJECT_FILENAME
    try:
        result = subprocess.run([*shlex.split(editor), str(path)], check=False)
    except FileNotFoundError as exc:
        raise SubjectError(f"Éditeur introuvable : {editor!r}.") from exc
    if result.returncode != 0:
        raise SubjectError(f"L'éditeur {editor!r} s'est terminé avec le code {result.returncode}.")
    _print_subject_summary(load_subject(slug, SUBJECTS_DIR), show=False)
    return 0


def _print_subject_summary(subject: Subject, show: bool) -> None:
    """Affiche le résumé d'un sujet, en construisant ses prompts et critères.

    Args:
        subject: Sujet chargé et validé.
        show: Si vrai, affiche aussi les prompts tels qu'ils seront envoyés.

    Raises:
        SubjectError: Si les critères du sujet sont mal formés.
    """
    system_prompt = subject.system_prompt()
    toc_instruction = subject.toc_instruction()
    requirements = subject.requirements()
    blocking = sum(1 for c in requirements["generic"] if c["severity"] == "bloquant")
    print(f"Sujet {subject.slug!r} valide : {subject.titre} ({subject.langue}).")
    print(f"  - {len(requirements['generic'])} critères communs ({blocking} bloquants)")
    print(f"  - {len(requirements['parties'])} partie(s) avec critères propres")
    print(f"  - prompt système : {len(system_prompt)} caractères, instruction de plan : {len(toc_instruction)}")
    if show:
        print("\n===== Prompt système =====\n")
        print(system_prompt)
        print("\n===== Instruction de plan =====\n")
        print(toc_instruction)


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
    _print_subject_summary(subject, args.show)
    return 0


def cmd_sources_add(args: argparse.Namespace) -> int:
    """Copie des documents de référence dans `subjects/<slug>/sources/`.

    Args:
        args: Arguments parsés (`files`, `force`).

    Returns:
        `0` si tous les fichiers ont été copiés.

    Raises:
        SourcesError: Si un fichier est introuvable, d'une extension non gérée ou déjà présent (capturée par `main`).
    """
    subject = _load_subject(args)
    target = subject.directory / SOURCES_DIRNAME
    sources_to_copy = []
    for raw in args.files:
        path = Path(raw)
        if not path.is_file():
            raise SourcesError(f"Fichier introuvable : {path}")
        if path.suffix.lower() not in SUFFIXES:
            raise SourcesError(f"{path.name} : extension non gérée (attendu : {', '.join(SUFFIXES)}).")
        if (target / path.name).exists() and not args.force:
            raise SourcesError(f"{path.name} existe déjà dans {target} (utilise --force pour l'écraser).")
        sources_to_copy.append(path)
    target.mkdir(exist_ok=True)
    for path in sources_to_copy:
        shutil.copyfile(path, target / path.name)
        print(f"Ajouté : {target / path.name}")
    return 0


def cmd_sources_list(args: argparse.Namespace) -> int:
    """Liste les documents de référence et l'état de leur analyse.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        `0`.
    """
    subject = _load_subject(args)
    names = list_source_files(subject.directory)
    if not names:
        print(f"Aucun document de référence (dépose des .md/.txt dans {subject.directory / SOURCES_DIRNAME}).")
        return 0
    index = load_index(_output_dir(args, subject))
    for name in names:
        entry = index.fichiers.get(name)
        if entry is None:
            print(f"- {name} : non analysé")
            continue
        useful = sum(1 for u in entry.unites if u.utilite != "nulle")
        print(f"- {name} : {len(entry.unites)} unité(s) dont {useful} utile(s)")
    return 0


def cmd_sources_extract(args: argparse.Namespace) -> int:
    """Analyse les documents de référence nouveaux ou modifiés et consolide l'index.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        `0` en cas de succès.
    """
    subject = _load_subject(args)
    output_dir = _output_dir(args, subject)
    cfg = load_config()
    tracing.configure(output_dir)
    report = refresh_index(cfg, subject.directory, output_dir, subject_context(subject))
    print(
        f"Sources : {len(report.extracted)} analysé(s), {len(report.cached)} en cache, "
        f"{len(report.removed)} retiré(s)" + (", index consolidé." if report.consolidated else ".")
    )
    return 0


def _require_sources_index(args: argparse.Namespace):
    """Charge l'index des sources du manuel, ou échoue s'il n'a pas été analysé.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        Le couple `(répertoire de sortie, index)`.

    Raises:
        SourcesError: Si aucun document n'a été analysé.
    """
    output_dir = _output_dir(args)
    index = load_index(output_dir)
    if not index.fichiers:
        raise SourcesError("Aucun document analysé : dépose des .md/.txt avec `manual sources add`, puis `manual sources extract`.")
    return output_dir, index


def cmd_sources_assign(args: argparse.Namespace) -> int:
    """Affecte les unités de matière aux chapitres (nouvelles unités seulement, sauf `--force`).

    Args:
        args: Arguments parsés (`output`, `subject`, `force`).

    Returns:
        `0` en cas de succès.

    Raises:
        SourcesError: Si le plan ou l'analyse des sources manque (capturée par `main`).
    """
    if not state_exists(_output_dir(args)):
        raise SourcesError("Aucun manifeste trouvé : lance d'abord `manual init`.")
    output_dir, index = _require_sources_index(args)
    cfg = load_config()
    tracing.configure(output_dir)
    report = ensure_assignment(cfg, load_state(output_dir), index, output_dir, force=args.force)
    print(
        f"Affectation : {report.assigned} unité(s) affectée(s), {report.pruned} entrée(s) retirée(s), "
        f"{len(report.orphans)} orpheline(s) (voir `manual sources orphans`)."
    )
    return 0


def cmd_sources_show(args: argparse.Namespace) -> int:
    """Affiche la matière que recevra un chapitre à la rédaction.

    Args:
        args: Arguments parsés (`output`, `subject`, `numero`).

    Returns:
        `0`.

    Raises:
        SourcesError: Si le chapitre est inconnu ou si rien n'a été analysé.
    """
    output_dir, index = _require_sources_index(args)
    cfg = load_config()
    state = load_state(output_dir)
    section = next((s for s in state.sections if s.numero == args.numero), None)
    if section is None:
        raise SourcesError(f"Section inconnue : {args.numero}.")
    block = render_sources(section, index, load_map(output_dir), int(cfg.setting("sources", "max_prompt_chars")))
    if not block.text:
        print(f"Aucune matière pour « {section.intitule} » (voir `manual sources orphans`).")
        return 0
    print(block.text)
    if block.omitted:
        print(f"\n{len(block.omitted)} unité(s) omise(s) faute de place : {', '.join(block.omitted)}")
    return 0


def cmd_sources_orphans(args: argparse.Namespace) -> int:
    """Liste les unités utiles qu'aucun chapitre ne développe.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        `0`.
    """
    output_dir, index = _require_sources_index(args)
    orphans = orphan_units(index, load_map(output_dir))
    if not orphans:
        print("Aucune unité orpheline : toute la matière utile est affectée.")
        return 0
    for u in orphans:
        print(f"- [{u.id}] ({u.type}, {u.utilite}) {u.enonce}")
    return 0


def cmd_sources_conflicts(args: argparse.Namespace) -> int:
    """Liste les contradictions repérées entre unités de matière.

    Args:
        args: Arguments parsés (`output`, `subject`).

    Returns:
        `0`.
    """
    _, index = _require_sources_index(args)
    units = {u.id: u for u in index.units()}
    pairs = sorted({tuple(sorted((u.id, other))) for u in units.values() for other in u.conflit_avec if other in units})
    if not pairs:
        print("Aucune contradiction repérée entre les sources.")
        return 0
    for left, right in pairs:
        print(f"- [{left}] {units[left].enonce}\n  ↔ [{right}] {units[right].enonce}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments du CLI `manual`.

    Returns:
        Le parseur configuré avec toutes les sous-commandes
        (`init`, `write`, `status`, `redo`, `improve`, `improve-toc`, `glossary`, `publish`, `traces`, `subject`).
    """
    parser = argparse.ArgumentParser(
        prog="manual", description="Génère un manuel de référence section par section, sur le sujet de votre choix."
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

    p_improve = sub.add_parser(
        "improve",
        help="Améliore des sections déjà écrites (le texte existant sert d'amorce, avec une consigne facultative).",
    )
    p_improve.add_argument("sections", nargs="+", metavar="N", help="Numéros et/ou intervalles de sections, ex: 3 5-8.")
    p_improve.add_argument(
        "-i", "--instruction", default=None, help='Consigne d\'amélioration (défaut : « relis et améliore »).'
    )
    p_improve.add_argument(
        "-f",
        "--instruction-file",
        default=None,
        metavar="FICHIER",
        help="Lit la consigne dans un fichier texte UTF-8 ; `-` = entrée standard.",
    )
    p_improve.add_argument("--max-rewrite", type=int, default=2, help="Nombre max de réécritures après rejet du juge.")
    p_improve.add_argument("-w", "--worker", type=int, default=4, help="Nombre de workers en parallèle (défaut : 4).")
    p_improve.set_defaults(func=cmd_improve)

    p_improve_toc = sub.add_parser(
        "improve-toc",
        help="Améliore la table des matières en préservant l'existant (chapitres rédigés figés, version précédente archivée).",
    )
    p_improve_toc.add_argument(
        "-i", "--instruction", default=None, help="Consigne d'amélioration (défaut : « relis et améliore »)."
    )
    p_improve_toc.add_argument(
        "-f",
        "--instruction-file",
        default=None,
        metavar="FICHIER",
        help="Lit la consigne dans un fichier texte UTF-8 ; `-` = entrée standard.",
    )
    p_improve_toc.set_defaults(func=cmd_improve_toc)

    p_glossary = sub.add_parser(
        "glossary", help="Génère glossaire.md à partir des chapitres terminés (extraction par chapitre, puis consolidation)."
    )
    p_glossary.set_defaults(func=cmd_glossary)

    p_sources = sub.add_parser(
        "sources", help="Documents de référence du sujet (bibliographie, thèmes, textes) : ajout, liste, analyse."
    )
    sources_sub = p_sources.add_subparsers(dest="sources_command", required=True)
    p_sources_add = sources_sub.add_parser("add", help="Copie des fichiers .md/.txt dans subjects/<sujet>/sources/.")
    p_sources_add.add_argument("files", nargs="+", metavar="FICHIER")
    p_sources_add.add_argument("--force", action="store_true", help="Écrase un fichier du même nom.")
    p_sources_add.set_defaults(func=cmd_sources_add)
    p_sources_list = sources_sub.add_parser("list", help="Liste les documents et l'état de leur analyse.")
    p_sources_list.set_defaults(func=cmd_sources_list)
    p_sources_extract = sources_sub.add_parser(
        "extract", help="Analyse les documents nouveaux ou modifiés (unités de matière) et consolide l'index."
    )
    p_sources_extract.set_defaults(func=cmd_sources_extract)
    p_sources_assign = sources_sub.add_parser(
        "assign", help="Affecte les unités de matière aux chapitres (nouvelles unités seulement)."
    )
    p_sources_assign.add_argument("--force", action="store_true", help="Recalcule toute l'affectation (ancienne carte en .bak).")
    p_sources_assign.set_defaults(func=cmd_sources_assign)
    p_sources_show = sources_sub.add_parser("show", help="Affiche la matière que recevra un chapitre à la rédaction.")
    p_sources_show.add_argument("numero", type=int, help="Numéro de la section (0 = introduction).")
    p_sources_show.set_defaults(func=cmd_sources_show)
    p_sources_orphans = sources_sub.add_parser("orphans", help="Liste les unités utiles qu'aucun chapitre ne développe.")
    p_sources_orphans.set_defaults(func=cmd_sources_orphans)
    p_sources_conflicts = sources_sub.add_parser("conflicts", help="Liste les contradictions entre sources.")
    p_sources_conflicts.set_defaults(func=cmd_sources_conflicts)

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

    p_subject = sub.add_parser("subject", help="Gère les sujets de manuel (liste, création, contrôle, suppression).")
    subject_sub = p_subject.add_subparsers(dest="subject_command", required=True)

    p_subject_list = subject_sub.add_parser("list", help="Liste les sujets disponibles.")
    p_subject_list.set_defaults(func=cmd_subject_list)

    p_subject_new = subject_sub.add_parser(
        "new", help="Crée un sujet : squelette à remplir, ou rédigé par le LLM si un descriptif est donné."
    )
    p_subject_new.add_argument("slug", help="Identifiant du sujet : minuscules, chiffres et tirets.")
    p_subject_new.add_argument(
        "brief", nargs="?", default=None, help="Descriptif libre du manuel voulu : le LLM rédige alors le sujet."
    )
    p_subject_new.add_argument(
        "-f",
        "--brief-file",
        default=None,
        metavar="FICHIER",
        help="Lit le descriptif (aussi long que nécessaire) dans un fichier texte UTF-8 ; `-` = entrée standard.",
    )
    p_subject_new.set_defaults(func=cmd_subject_new)

    p_subject_refine = subject_sub.add_parser("refine", help="Retouche un sujet selon une consigne (LLM).")
    p_subject_refine.add_argument("slug", help="Sujet à retoucher.")
    p_subject_refine.add_argument(
        "instruction", nargs="?", default=None, help='Consigne libre, ex. « ton plus décontracté, sans juridique ».'
    )
    p_subject_refine.add_argument(
        "-f",
        "--instruction-file",
        default=None,
        metavar="FICHIER",
        help="Lit la consigne (aussi longue que nécessaire) dans un fichier texte UTF-8 ; `-` = entrée standard.",
    )
    p_subject_refine.set_defaults(func=cmd_subject_refine)

    p_subject_criteria = subject_sub.add_parser(
        "criteria", help="Propose des critères de relecture par partie de la TOC générée (LLM)."
    )
    p_subject_criteria.add_argument("slug", nargs="?", default=None, help="Sujet concerné (défaut : --subject ou l'unique sujet).")
    p_subject_criteria.add_argument("--force", action="store_true", help="Remplace les critères déjà présents pour ces parties.")
    p_subject_criteria.set_defaults(func=cmd_subject_criteria)

    p_subject_edit = subject_sub.add_parser("edit", help="Ouvre subject.yml dans l'éditeur ($VISUAL / $EDITOR), puis le valide.")
    p_subject_edit.add_argument("slug", nargs="?", default=None, help="Sujet à éditer (défaut : --subject ou l'unique sujet).")
    p_subject_edit.set_defaults(func=cmd_subject_edit)

    p_subject_delete = subject_sub.add_parser(
        "delete", help="Supprime définitivement un sujet (et, avec --with-output, son manuel généré)."
    )
    p_subject_delete.add_argument("slug", help="Sujet à supprimer (obligatoire : pas de choix par défaut).")
    p_subject_delete.add_argument("-y", "--yes", action="store_true", help="Ne demande pas de confirmation.")
    p_subject_delete.add_argument(
        "--with-output", action="store_true", help="Supprime aussi le manuel généré dans output/<sujet>/."
    )
    p_subject_delete.set_defaults(func=cmd_subject_delete)

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
        SourcesError,
        StateError,
        SubjectError,
    ) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
