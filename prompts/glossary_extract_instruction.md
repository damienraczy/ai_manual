# Tâche : extraire les termes à définir d'un chapitre

Voici le chapitre $numero (« $titre ») d'un manuel. Repère les termes techniques, concepts et sigles que le lecteur peut avoir besoin de retrouver dans un glossaire, en ne retenant que ceux que ce chapitre définit ou emploie de façon importante.

## Règles

- Écris dans la langue du chapitre.
- Une définition = une à deux phrases claires et autonomes, basées exclusivement sur le texte fourni (aucune connaissance externe).
- Une entrée par terme, sans doublon, au singulier, en casse naturelle (pas de majuscule arbitraire). Pour un sigle : la forme abrégée suivie du nom complet entre parenthèses, s'il est donné dans le chapitre.
- Exclus les mots du langage courant et les notions seulement citées au passage, sans explication dans le chapitre.
- Si aucun terme ne justifie une entrée, réponds `{"entrees": []}`.

## Format de sortie

Réponds uniquement avec un bloc JSON de cette forme, sans texte avant ni après :

```json
{"entrees": [{"terme": "Nom du terme ou sigle", "definition": "Définition concise et fidèle."}]}
```

## Chapitre

$texte
