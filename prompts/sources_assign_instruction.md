# Tâche : affecter des unités de matière aux chapitres du manuel

Un auteur a fourni des documents de référence, découpés en unités de matière. Place chaque unité dans le chapitre où elle sera **développée** : un seul chapitre principal par unité, pour qu'une même idée ne soit pas traitée deux fois.

## Plan du manuel

$plan

## Titres exacts des chapitres

Utilise uniquement ces titres, recopiés à l'identique :

$chapitres

## Unités à affecter

Une par ligne : identifiant | type | énoncé.

$unites

## Règles

- Pour **chaque** unité ci-dessus, une affectation (ni oubli ni doublon).
- `principal` : le titre du chapitre qui doit développer l'unité, ou `null` si aucun chapitre du plan ne s'y prête (l'unité restera de côté).
- `secondaire` : facultatif, le titre d'un autre chapitre qui peut simplement y **renvoyer** en une phrase, sans la développer. Jamais le même que `principal`, et seulement si `principal` n'est pas `null`.
- Choisis le chapitre dont la description et les sous-sections correspondent le mieux au contenu de l'unité. L'introduction ne reçoit que du cadrage, la conclusion que de la synthèse ou des perspectives.

Réponds uniquement avec un bloc JSON de cette forme :

```json
{"affectations": [{"unite": "a.md#1", "principal": "Titre du chapitre", "secondaire": null}]}
```
