# Tâche : évaluer une section du manuel

Évalue la section ci-dessous au regard des seuls critères listés. Un critère rempli ne donne lieu à aucune remarque.

## Section attendue

- Titre : `## $intitule`
- Sous-sections, dans l'ordre :
$sous_sections

## Critères

$requirements

$regles

## Section à évaluer

<section>
$section_text
</section>

## Format de sortie — STRICT

Réponds uniquement avec un bloc de code ```json, sans texte avant ni après, conforme à ce schéma :

```json
{
  "verdict": "accept",
  "issues": [
    {"id": "identifiant_du_critere", "severity": "bloquant", "detail": "problème localisé et correction attendue"}
  ]
}
```

- `verdict` : `"revise"` si au moins un critère `bloquant` n'est pas rempli, sinon `"accept"`.
- `issues` : un élément par critère non rempli, `[]` si tous le sont. `id` : l'identifiant exact d'un critère ci-dessus ; `severity` : celle de ce critère (`"bloquant"` ou `"recommande"`) ; `detail` : où se trouve le problème (sous-section, phrase citée) et ce qu'il faut corriger.
- Aucune autre clé.
