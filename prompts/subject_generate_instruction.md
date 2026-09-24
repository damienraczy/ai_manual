# Tâche : cadrer un nouveau manuel à partir d'un court descriptif

Voici le descriptif fourni par l'auteur :

> $brief

Propose le cadrage complet du manuel : tous les champs ci-dessous doivent être renseignés, sauf `exclusions` et `instructions` qui peuvent rester vides (`[]` et `""`).

```json
{
  "titre": "titre du sujet, tel qu'il figurera dans le manuel",
  "langue": "langue de rédaction (ex. français)",
  "role": "personnage de l'auteur, à la deuxième personne : « Tu es un expert en ... » (expertise, expérience, références)",
  "objectif": "ce que le manuel doit apporter, en une ou deux phrases",
  "public": "lecteurs visés",
  "niveau": "niveau atteint (ex. débutant → expert)",
  "ton": "ton de la rédaction",
  "plan_directeur": "progression attendue des grandes parties, séparées par des flèches « → » (5 à 8 étapes)",
  "exclusions": ["sujets à ne pas traiter"],
  "instructions": "consignes libres supplémentaires (sources à privilégier, style, exemples attendus)",
  "criteres": [
    {"id": "identifiant_en_snake_case", "description": "une phrase décrivant ce que chaque section doit contenir", "severity": "recommande"}
  ]
}
```

Règles pour `criteres` :
- 2 à 5 critères de relecture propres à ce sujet, à appliquer à toutes les sections.
- `severity` vaut `"bloquant"` (force une réécriture si non rempli) ou `"recommande"`. Au plus 2 critères bloquants.
- N'en propose aucun qui recoupe les critères communs déjà appliqués :

$criteres_communs

Ne mets jamais de texte du type « À COMPLÉTER » : chaque champ doit être réellement rédigé.
