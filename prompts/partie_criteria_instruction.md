# Tâche : proposer des critères de relecture par grande partie

Voici le cadrage du manuel :

```yaml
$subject_yaml
```

Voici les grandes parties de la table des matières générée (titre exact, puis chapitres) :

$parties

Critères déjà appliqués à toutes les sections (ne les répète pas) :

$criteres_existants

Propose, pour les parties où cela a du sens, 1 à 3 critères de relecture **propres à cette partie** (ce qui distingue ses chapitres des autres : niveau de prérequis, type d'exemple attendu, tableau de synthèse, mesure chiffrée...). Omets les parties pour lesquelles aucun critère spécifique ne se justifie.

- La clé de chaque partie doit être son **titre exact**, recopié caractère pour caractère.
- `id` : identifiant en snake_case, unique et différent des critères existants.
- `severity` : `"bloquant"` (force une réécriture) ou `"recommande"`. Réserve `"bloquant"` à l'essentiel.

```json
{
  "parties": {
    "Titre exact de la partie": [
      {"id": "identifiant_en_snake_case", "description": "une phrase", "severity": "recommande"}
    ]
  }
}
```
