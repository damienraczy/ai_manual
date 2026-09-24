# Tâche : améliorer la table des matières du manuel

Voici la table des matières actuelle du manuel décrit dans le prompt système (JSON) :

```json
$toc_actuelle
```

## Consigne d'amélioration

$consigne

## Chapitres figés

Ces chapitres sont **déjà rédigés** : ils doivent figurer dans la nouvelle table des matières avec le **même numéro, le même titre et exactement les mêmes sous-sections** (numéros et titres inchangés). Le reste peut être modifié librement : réordonner, fusionner, scinder, ajouter, supprimer, renommer les parties.

$chapitres_figes

## Règles

- Pars de la table des matières actuelle : conserve ce qui est bon, ne repars pas de zéro.
- Les chapitres non figés qui ne sont pas concernés par la consigne restent identiques.
- Ne change pas la numérotation des chapitres figés : ajoute les nouveaux chapitres et réorganise uniquement parmi les numéros non figés.

## Format de sortie — STRICT

Réponds **uniquement** avec un unique bloc de code ```json contenant la table des matières **complète** mise à jour, au même schéma que la table actuelle :

- `numero` des parties : chiffres romains ("I", "II", "III", ...).
- `numero` des chapitres : entiers consécutifs de 1 à N sur l'ensemble du manuel (ne recommence pas à 1 à chaque partie), sans trou ni doublon.
- `numero` des sous-sections : `"<numero_chapitre>.<rang>"` (ex. "6.3").
- Chaque chapitre a une `description` en une phrase.
- Aucun commentaire, aucune clé additionnelle, aucun texte hors du bloc JSON. Le JSON doit être strictement valide (guillemets doubles, pas de virgule finale).
