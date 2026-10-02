# Tâche : extraire les termes à définir d'un chapitre

Voici le chapitre $numero (« $titre ») d'un manuel. Repère les termes techniques, concepts et sigles que le lecteur peut avoir besoin de retrouver dans un glossaire, en ne retenant que ceux que ce chapitre définit ou emploie de façon importante.

# Règles :
- Écris dans la langue du chapitre.
- Une définition = 1 à 2 phrases claires, autonomes, basées exclusivement sur le texte fourni (aucune connaissance externe).
- Forme des termes : une entrée par terme, sans doublon, au singulier, casse naturelle (pas de majuscule arbitraire). Pour un sigle, utilise la forme abrégée suivie du nom complet entre parenthèses, si mentionné.
- Pertinence : exclus les mots du langage courant, les notions seulement mentionnées au passage sans explication, et les doublons.
- Pas de mots courants ni de termes qui ne sont pas expliqués dans le chapitre.
- Si aucun terme ne justifie une entrée, renvoie : `{"entrees": []}`.

# Format de sortie
Réponds uniquement avec un bloc JSON de cette forme :

```json
{
  "entrees": [
    {
      "terme": "Nom du terme ou Sigle",
      "definition": "Définition concise et fidèle."
    }
  ]
}
```

## Chapitre

$texte
