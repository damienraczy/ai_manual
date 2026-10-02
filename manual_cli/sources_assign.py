"""Affectation des unités de matière aux chapitres, et rendu du bloc injecté à la rédaction.

Chaque unité utile a un chapitre *principal* (il la développe : jamais deux
chapitres pour la même unité, ce qui évite les répétitions) et, facultativement,
un chapitre *secondaire* qui y renvoie en une phrase. L'affectation est écrite
dans `sources_map.yml`, éditable à la main : seules les unités nouvelles ou
orphelines sont (ré)affectées, sauf `force`. Les chapitres sont repérés par leur titre.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, model_validator

from . import sources
from .config import AppConfig
from .parsing import call_structured
from .sources import SourceIndex, SourcesError, Unite, load_index
from .state import ManualState, SectionState, render_plan

MAP_FILENAME = "sources_map.yml"
ORPHANS_KEY = "orphelines"
MAP_HEADER = (
    "# Affectation des unités de matière aux chapitres (clé = titre du chapitre dans toc.yml).\n"
    "# principal : le chapitre développe l'unité ; secondaire : il y renvoie en une phrase.\n"
    "# Éditable à la main. `orphelines` : unités laissées de côté.\n"
    "# Les identifiants viennent de `manual sources list` / `show`.\n"
)

TYPE_HEADINGS = {
    "reference": ("Références", "Cite-les avec exactement ces éléments (auteur, titre, année...) ; n'en invente aucune autre."),
    "passage": ("Passages déjà rédigés", "Reprends-les et étoffe-les dans ton style, sans les recopier mot à mot."),
    "theme": ("Thèmes et angles", "Développe-les."),
    "idee": ("Idées et arguments", "À développer avec tes propres mots et exemples."),
    "fait": ("Faits et données", "Utilise-les sans les déformer ; reformule."),
    "exemple": ("Exemples et cas", "À reformuler ou à illustrer."),
}

INTRO = (
    "## Matière fournie par l'auteur (documents de référence)\n\n"
    "Ces éléments viennent de documents fournis par l'auteur : c'est de la matière à exploiter, pas une vérité. "
    "Reformule, organise, ne recopie pas, et intègre-la comme ton propre propos : le texte ne mentionne pas ces documents "
    "(les références se citent normalement). Traite chaque élément **À COUVRIR** : ne l'écarte que s'il est hors sujet "
    "ou douteux, et dans ce cas ajoute juste avant la ligne de fin une ligne `<!-- écarté [identifiant] : motif -->`. "
    "Les autres éléments sont facultatifs. Ne cite aucune référence qui ne figure pas ici. "
    "Quand deux éléments se contredisent (⚠), présente le débat au lieu de trancher en silence. "
    "Les éléments de renvoi sont développés dans un autre chapitre : cite-les au plus en une phrase."
)


class ChapterUnits(BaseModel):
    """Unités d'un chapitre.

    Attributes:
        principal: Identifiants des unités que le chapitre développe.
        secondaire: Identifiants des unités auxquelles il renvoie seulement.
    """

    principal: list[str] = []
    secondaire: list[str] = []


class SourcesMap(BaseModel):
    """Affectation des unités aux chapitres.

    Attributes:
        chapitres: Titre du chapitre -> unités.
        orphelines: Unités utiles qu'aucun chapitre ne développe (laissées de côté).
    """

    chapitres: dict[str, ChapterUnits] = {}
    orphelines: list[str] = []


@dataclass
class AssignReport:
    """Ce qu'une affectation a fait.

    Attributes:
        assigned: Unités affectées (ou mises de côté) pendant cet appel.
        pruned: Entrées retirées de la carte (unité disparue, chapitre disparu).
        orphans: Identifiants des unités utiles sans chapitre principal.
    """

    assigned: int = 0
    pruned: int = 0
    orphans: list[str] = field(default_factory=list)


@dataclass
class SourcesBlock:
    """Bloc injecté dans le prompt d'un chapitre.

    Attributes:
        text: Texte du bloc (vide si le chapitre n'a pas de matière).
        omitted: Identifiants des unités omises faute de place.
    """

    text: str
    omitted: list[str] = field(default_factory=list)


class Affectation(BaseModel):
    """Affectation d'une unité telle que renvoyée par le modèle."""

    unite: str
    principal: str | None = None
    secondaire: str | None = None


class AssignSchema(BaseModel):
    """Réponse attendue du modèle pour un lot d'unités."""

    affectations: list[Affectation]


def _assign_schema(unit_ids: list[str], titles: set[str]) -> type[AssignSchema]:
    """Schéma qui exige une affectation cohérente pour chaque unité du lot."""

    class _Consistent(AssignSchema):
        @model_validator(mode="after")
        def _check(self):
            given = [a.unite for a in self.affectations]
            if sorted(given) != sorted(unit_ids):
                raise ValueError(
                    "Chaque unité du lot doit apparaître exactement une fois, sans identifiant inventé "
                    f"(attendu : {', '.join(unit_ids)} ; reçu : {', '.join(given) or 'rien'})."
                )
            for a in self.affectations:
                unknown = [t for t in (a.principal, a.secondaire) if t is not None and t not in titles]
                if unknown:
                    raise ValueError(f"Titre(s) de chapitre inconnu(s) : {', '.join(map(repr, unknown))}. Recopie-les exactement.")
                if a.secondaire is not None and a.principal is None:
                    raise ValueError(f"{a.unite} : un chapitre secondaire exige un chapitre principal.")
                if a.secondaire is not None and a.secondaire == a.principal:
                    raise ValueError(f"{a.unite} : le chapitre secondaire doit différer du principal.")
            return self

    return _Consistent


def load_map(output_dir: Path) -> SourcesMap:
    """Charge `sources_map.yml`.

    Args:
        output_dir: Répertoire de sortie du manuel.

    Returns:
        La carte, vide si le fichier n'existe pas ou est vide.

    Raises:
        SourcesError: Si le YAML est invalide, mal structuré ou si une unité a deux chapitres principaux.
    """
    path = output_dir / MAP_FILENAME
    if not path.is_file():
        return SourcesMap()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SourcesError(f"{MAP_FILENAME} : YAML invalide ({exc}).") from exc
    if not isinstance(raw, dict):
        raise SourcesError(f"{MAP_FILENAME} : un dictionnaire titre -> unités est attendu.")
    orphans = raw.pop(ORPHANS_KEY, None) or []
    try:
        smap = SourcesMap(chapitres={title: ChapterUnits.model_validate(value) for title, value in raw.items()}, orphelines=orphans)
    except ValidationError as exc:
        raise SourcesError(f"{MAP_FILENAME} : structure invalide ({exc}).") from exc
    seen: dict[str, str] = {}
    for title, units in smap.chapitres.items():
        for unit_id in units.principal:
            if unit_id in seen:
                raise SourcesError(f"{MAP_FILENAME} : {unit_id} est principal dans « {seen[unit_id]} » et « {title} ».")
            seen[unit_id] = title
    return smap


def save_map(output_dir: Path, smap: SourcesMap) -> None:
    """Écrit `sources_map.yml`.

    Args:
        output_dir: Répertoire de sortie du manuel.
        smap: Carte à écrire.
    """
    data = {title: units.model_dump() for title, units in smap.chapitres.items()}
    data[ORPHANS_KEY] = list(smap.orphelines)
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / MAP_FILENAME).write_text(MAP_HEADER + body, encoding="utf-8")


def _placed(smap: SourcesMap) -> set[str]:
    """Identifiants des unités déjà traitées : principales quelque part, ou mises de côté."""
    return {i for units in smap.chapitres.values() for i in units.principal} | set(smap.orphelines)


def orphan_units(index: SourceIndex, smap: SourcesMap) -> list[Unite]:
    """Unités utiles qu'aucun chapitre ne développe.

    Args:
        index: Index des sources.
        smap: Carte d'affectation.

    Returns:
        Les unités actives sans chapitre principal (mises de côté, ou seulement en renvoi).
    """
    principal = {i for units in smap.chapitres.values() for i in units.principal}
    return [u for u in index.active_units() if u.id not in principal]


def _prune(smap: SourcesMap, active_ids: set[str], titles: set[str]) -> int:
    """Retire de la carte les chapitres disparus et les unités disparues ; renvoie le nombre d'entrées retirées."""
    removed = 0
    for title in list(smap.chapitres):
        units = smap.chapitres[title]
        if title not in titles:
            removed += len(units.principal) + len(units.secondaire)
            del smap.chapitres[title]
            continue
        for attr in ("principal", "secondaire"):
            kept = [i for i in getattr(units, attr) if i in active_ids]
            removed += len(getattr(units, attr)) - len(kept)
            setattr(units, attr, kept)
    kept_orphans = [i for i in smap.orphelines if i in active_ids]
    removed += len(smap.orphelines) - len(kept_orphans)
    smap.orphelines = kept_orphans
    return removed


def ensure_assignment(
    cfg: AppConfig, state: ManualState, index: SourceIndex, output_dir: Path, *, force: bool = False
) -> AssignReport:
    """Complète l'affectation : place les unités nouvelles ou sans chapitre, retire ce qui a disparu.

    Une carte à jour n'est pas réécrite (les commentaires et retouches manuelles restent).

    Args:
        cfg: Configuration applicative résolue.
        state: État du manuel (plan et titres des chapitres).
        index: Index des sources.
        output_dir: Répertoire de sortie du manuel.
        force: Recalcule tout depuis zéro (l'ancienne carte est gardée en `.bak`).

    Returns:
        Le compte rendu de l'affectation.

    Raises:
        SourcesError: Si la carte existante est invalide ou si `sources.assign_batch` est invalide.
        ParsingError: Si le modèle ne renvoie pas d'affectations cohérentes.
    """
    batch = int(cfg.setting("sources", "assign_batch"))
    if batch <= 0:
        raise SourcesError(f"sources.assign_batch doit être positif (reçu {batch}).")
    path = output_dir / MAP_FILENAME
    smap = load_map(output_dir)
    if force and path.is_file():
        path.with_name(path.name + ".bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        smap = SourcesMap()

    active = index.active_units()
    titles = [s.titre for s in state.sections]
    report = AssignReport(pruned=_prune(smap, {u.id for u in active}, set(titles)))
    placed = _placed(smap)
    pending = [u for u in active if u.id not in placed]

    if pending:
        client = sources._client(cfg, "model_think")
        template = string.Template(sources._read_prompt("sources_assign_instruction.md"))
        plan = render_plan(state, -1)
        chapters = "\n".join(f"- {t}" for t in titles)
        for start in range(0, len(pending), batch):
            chunk = pending[start : start + batch]
            lines = "\n".join(f"- {u.id} | {u.type} | {u.enonce}" for u in chunk)
            prompt = template.substitute(plan=plan, chapitres=chapters, unites=lines)
            answer = call_structured(
                client, [{"role": "user", "content": prompt}], _assign_schema([u.id for u in chunk], set(titles))
            )
            for a in answer.affectations:
                if a.principal is None:
                    smap.orphelines.append(a.unite)
                    continue
                smap.chapitres.setdefault(a.principal, ChapterUnits()).principal.append(a.unite)
                if a.secondaire is not None:
                    smap.chapitres.setdefault(a.secondaire, ChapterUnits()).secondaire.append(a.unite)
        report.assigned = len(pending)

    if pending or report.pruned or force:
        save_map(output_dir, smap)
    report.orphans = [u.id for u in orphan_units(index, smap)]
    return report


def _unit_line(unit: Unite, *, short: bool) -> str:
    """Ligne d'une unité principale."""
    must = "**À COUVRIR** " if unit.utilite == "haute" else ""
    line = f"- [{unit.id}] {must}{unit.enonce.strip()}"
    if not short:
        line += f" — « {unit.extrait.strip()} » ({unit.source}, l.{unit.ligne})"
    if unit.autres_sources:
        line += f" ; aussi dans {', '.join(unit.autres_sources)}"
    return line


def _compose(
    principal: list[Unite],
    secondary: list[tuple[Unite, str]],
    short: set[str],
    hidden: set[str],
    by_id: dict[str, Unite],
) -> str:
    """Assemble le bloc à partir des unités visibles."""
    parts = [INTRO]
    for type_, (heading, instruction) in TYPE_HEADINGS.items():
        lines = []
        for u in principal:
            if u.type != type_ or u.id in hidden:
                continue
            lines.append(_unit_line(u, short=u.id in short))
            for other in u.conflit_avec:
                if other in by_id:
                    lines.append(f"  ⚠ contredit [{other}] : {by_id[other].enonce.strip()}")
        if lines:
            parts.append(f"### {heading}\n{instruction}\n\n" + "\n".join(lines))
    pointers = [f"- [{u.id}] {u.enonce.strip()} → traité au chapitre « {title} »" for u, title in secondary if u.id not in hidden]
    if pointers:
        parts.append("### Renvois (développés dans un autre chapitre)\n\n" + "\n".join(pointers))
    if hidden:
        parts.append(f"*Omis faute de place : {', '.join(sorted(hidden))}.*")
    return "\n\n".join(parts)


def render_sources(section: SectionState, index: SourceIndex, smap: SourcesMap, budget: int) -> SourcesBlock:
    """Rend le bloc de matière d'un chapitre, dans la limite d'un budget de caractères.

    Si le bloc dépasse `budget`, les unités de moindre priorité (renvois, puis
    unités moyennes, puis hautes en dernier recours) perdent d'abord leur extrait,
    puis sont omises ; ce qui est omis est signalé dans le bloc et dans le résultat.

    Args:
        section: Chapitre à rédiger.
        index: Index des sources.
        smap: Carte d'affectation.
        budget: Taille maximale du bloc, en caractères.

    Returns:
        Le bloc (texte vide si le chapitre n'a pas de matière).
    """
    units = smap.chapitres.get(section.titre)
    if units is None:
        return SourcesBlock("")
    by_id = {u.id: u for u in index.units()}
    principal = [by_id[i] for i in units.principal if i in by_id and by_id[i].utilite != "nulle"]
    principal.sort(key=lambda u: u.utilite != "haute")
    titles_of = {i: title for title, cu in smap.chapitres.items() for i in cu.principal}
    secondary = [
        (by_id[i], titles_of.get(i, "non affecté"))
        for i in units.secondaire
        if i in by_id and by_id[i].utilite != "nulle"
    ]
    if not principal and not secondary:
        return SourcesBlock("")

    short: set[str] = set()
    hidden: set[str] = set()

    def text() -> str:
        return _compose(principal, secondary, short, hidden, by_id)

    if len(text()) > budget:
        for u in reversed(principal):
            short.add(u.id)
            if len(text()) <= budget:
                break
    if len(text()) > budget:
        for u in [s for s, _ in reversed(secondary)] + list(reversed(principal)):
            hidden.add(u.id)
            if len(text()) <= budget:
                break
    omitted = [u.id for u in principal if u.id in hidden] + [u.id for u, _ in secondary if u.id in hidden]
    return SourcesBlock(text(), omitted)


@dataclass
class SectionMatter:
    """Matière d'un chapitre pour la rédaction et le jugement.

    Attributes:
        text: Bloc injecté dans le prompt de rédaction (vide s'il n'y a rien).
        must_cover: Unités « À COUVRIR » effectivement montrées au rédacteur.
        omitted: Unités omises faute de place (non exigées du rédacteur).
    """

    text: str = ""
    must_cover: list[Unite] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)


def section_matter(cfg: AppConfig, output_dir: Path, section: SectionState) -> SectionMatter:
    """Matière d'un chapitre : bloc à injecter et unités que le juge exigera.

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        section: Chapitre à rédiger.

    Returns:
        La matière ; vide si le manuel n'a pas de sources analysées ou si le chapitre n'en a pas.

    Raises:
        SourcesError: Si l'index ou la carte sont invalides.
        ConfigError: Si `sources.max_prompt_chars` manque alors que des sources existent.
    """
    index = load_index(output_dir)
    if not index.fichiers:
        return SectionMatter()
    smap = load_map(output_dir)
    block = render_sources(section, index, smap, int(cfg.setting("sources", "max_prompt_chars")))
    if not block.text:
        return SectionMatter()
    by_id = {u.id: u for u in index.units()}
    chapter = smap.chapitres[section.titre]
    must = [by_id[i] for i in chapter.principal if i in by_id and by_id[i].utilite == "haute" and i not in block.omitted]
    return SectionMatter(block.text, must, block.omitted)


def sources_for_section(cfg: AppConfig, output_dir: Path, section: SectionState) -> str:
    """Bloc de matière à injecter dans le prompt d'un chapitre (voir `section_matter`).

    Args:
        cfg: Configuration applicative résolue.
        output_dir: Répertoire de sortie du manuel.
        section: Chapitre à rédiger.

    Returns:
        Le bloc, ou une chaîne vide.
    """
    return section_matter(cfg, output_dir, section).text


def plan_summary(index: SourceIndex, budget: int) -> str:
    """Résumé de la matière par thème, pour orienter la génération ou l'amélioration du plan.

    Args:
        index: Index des sources.
        budget: Taille maximale du résumé, en caractères.

    Returns:
        Un paragraphe suivi d'une ligne par thème (nombre d'unités, types, exemples), les thèmes
        les plus fournis d'abord ; vide s'il n'y a aucune unité utile.
    """
    groups: dict[str, list[Unite]] = {}
    for u in index.active_units():
        theme = u.themes[0].strip().lower() if u.themes and u.themes[0].strip() else "divers"
        groups.setdefault(theme, []).append(u)
    if not groups:
        return ""
    intro = (
        "## Matière fournie par l'auteur\n\n"
        "L'auteur a fourni des documents de référence. Tiens-en compte dans la structure du plan : "
        "les thèmes utiles ci-dessous doivent y trouver leur place, sans forcer ce qui serait hors sujet.\n"
    )
    lines = []
    for theme, units in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = len(units)
        types = ", ".join(sorted({u.type for u in units}))
        examples = " ; ".join(f"« {u.enonce.strip()} »" for u in units[:2])
        lines.append(f"- {theme} ({n} unité{'s' if n > 1 else ''} : {types}) : {examples}")
    kept: list[str] = []
    for line in lines:
        rest = len(lines) - len(kept) - 1
        tail = f"\n- … et {rest} autre(s) thème(s) non listé(s)" if rest else ""
        if kept and len("\n".join([intro, *kept, line]) + tail) > budget:
            break
        kept.append(line)
    dropped = len(lines) - len(kept)
    tail = f"\n- … et {dropped} autre(s) thème(s) non listé(s)" if dropped else ""
    return intro + "\n" + "\n".join(kept) + tail
