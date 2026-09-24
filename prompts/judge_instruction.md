# Tâche : évaluer une section du manuel

Tu es un relecteur exigeant. Évalue la section ci-dessous **uniquement** au regard des critères fournis (n'invente pas d'autres critères).

## Critères à vérifier

$requirements

## Section à évaluer

$section_text

## Format de sortie — STRICT

Réponds **uniquement** avec un unique bloc de code ```json contenant un objet conforme exactement au schéma suivant, sans aucun texte avant ou après le bloc :

```json
{
  "verdict": "accept" | "revise",
  "issues": [
    {"id": "identifiant_du_critere", "severity": "bloquant" | "recommande", "detail": "explication précise et actionnable du problème"}
  ]
}
```

Règles :
- `verdict` = `"revise"` si au moins un critère `bloquant` n'est pas rempli. Sinon `"accept"` (même si des critères `recommande` restent perfectibles : liste-les dans `issues` mais le verdict reste `accept`).
- Chaque `issue` doit référencer un `id` de critère fourni ci-dessus.
- N'invente aucune clé additionnelle, JSON strictement valide.
