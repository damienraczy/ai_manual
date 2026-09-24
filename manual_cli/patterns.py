"""Parsing des motifs de sélection de sections passés en ligne de commande.

Gère la syntaxe acceptée par `manual write -s ...` : numéros isolés,
intervalles inclusifs (`a-b`), et combinaisons des deux, énumérés en
plusieurs jetons.
"""

from __future__ import annotations

import re

_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
_SINGLE_RE = re.compile(r"^(\d+)$")


class PatternError(Exception):
    """Motif de sélection de section invalide ou vide."""


def parse_section_patterns(tokens: list[str]) -> list[int]:
    """Convertit une liste de jetons en numéros de sections triés et uniques.

    Chaque jeton est soit un entier isolé (« 3 »), soit un intervalle
    inclusif « début-fin » (« 5-8 »). Les valeurs qui se chevauchent entre
    plusieurs jetons sont dédupliquées.

    Args:
        tokens: Jetons bruts issus de l'argument `-s`/`--section` (ex:
            `["1", "3", "5-8"]`).

    Returns:
        Liste triée des numéros de sections correspondants, sans doublon.

    Raises:
        PatternError: Si un jeton n'est ni un entier ni un intervalle
            valide, si un intervalle est inversé (début > fin), ou si la
            liste de jetons ne produit aucun numéro.
    """
    numbers: set[int] = set()
    for token in tokens:
        range_match = _RANGE_RE.match(token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                raise PatternError(f"Intervalle invalide : {token!r} (début > fin).")
            numbers.update(range(start, end + 1))
            continue

        single_match = _SINGLE_RE.match(token)
        if single_match:
            numbers.add(int(single_match.group(1)))
            continue

        raise PatternError(f"Motif de section invalide : {token!r} (attendu un entier ou un intervalle 'a-b').")

    if not numbers:
        raise PatternError("Aucun numéro de section fourni.")

    return sorted(numbers)
