# Tâche : repérer les DOUBLONS et les contradictions entre unités de matière

Voici des unités extraites de plusieurs documents de référence (identifiant, type, énoncé) :

$unites

## Règles

- **Doublons** : plusieurs unités qui disent la même chose (même idée, même référence, même fait). Indique l'unité à `garde` (la plus complète) et les `doublons` à fusionner dedans. Deux unités simplement voisines ne sont pas des doublons. Une unité ne figure qu'une fois comme doublon, et une unité conservée (`garde`) ne peut pas être elle-même le doublon d'une autre : pas de chaîne de fusions.
- **Conflits** : des unités qui se contredisent (faits, chiffres ou positions incompatibles). Donne la liste des identifiants concernés, sans en supprimer aucun.
- N'utilise que les identifiants ci-dessus, tels quels. Si rien n'est à signaler, renvoie des listes vides.

Réponds uniquement avec un bloc JSON de cette forme :

```json
{"fusions": [{"garde": "a.md#1", "doublons": ["b.md#3"]}], "conflits": [["a.md#2", "c.md#1"]]}
```
