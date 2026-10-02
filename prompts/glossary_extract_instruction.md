# Tâche : extraire les termes à définir d'un chapitre

Voici le chapitre $numero (« $titre ») d'un manuel. Repère les termes techniques, concepts et sigles que le lecteur peut avoir besoin de retrouver dans un glossaire, en ne retenant que ceux que ce chapitre définit ou emploie de façon importante.

Règles :
- Écris dans la langue du chapitre.
- Une définition = une à deux phrases, autonome, fidèle à ce que dit le chapitre (n'invente rien).
- Pas de mots courants ni de termes qui ne sont pas expliqués dans le chapitre.
- Une entrée par terme, au singulier, sans doublon.

Réponds uniquement avec un bloc JSON de cette forme :

```json
{"entrees": [{"terme": "...", "definition": "..."}]}
```

## Chapitre

$texte
