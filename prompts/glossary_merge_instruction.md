# Tâche : consolider le glossaire d'un manuel

Voici les termes extraits chapitre par chapitre, une ligne par terme : `terme : définition (chap. N)`. Produis le glossaire final du manuel.

## Règles

- Fusion : regroupe les doublons et variantes (casse, singulier/pluriel, sigle et forme développée) sous une seule entrée normalisée.
- Définition : une seule, fluide et autonome, qui combine fidèlement les extraits. N'invente aucun terme ni aucune définition qui ne découle pas des extraits.
- Chapitres : pour chaque entrée, la liste des numéros de chapitres associés, en entiers, sans doublon, triés par ordre croissant (ex. `[1, 3, 5]`).
- Filtrage : retire les termes triviaux ou sans intérêt pour un glossaire de référence.
- Langue : celle des extraits.

## Format de sortie

Réponds uniquement avec un bloc JSON strictement valide, sans texte avant ni après, de cette forme :

```json
{"entrees": [{"terme": "Terme normalisé", "definition": "Définition consolidée.", "chapitres": [1, 3]}]}
```

## Termes extraits

$entrees
