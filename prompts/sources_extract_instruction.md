# Tâche : extraire la matière d'un document de référence

Un auteur fournit ce document pour aider à rédiger un manuel. Découpe-le en **unités de matière** : des éléments autonomes, que l'on pourra affecter chacun à un chapitre précis.

$contexte

## Types d'unités

- `idee` : une idée, un argument ou une thèse.
- `fait` : une donnée, un chiffre, un constat vérifiable.
- `reference` : une source bibliographique (auteur, titre, année, éditeur...) avec son éventuel commentaire.
- `exemple` : un exemple, un cas, une anecdote.
- `passage` : un texte déjà rédigé, qu'il faudra reprendre et étoffer.
- `theme` : un thème ou un angle à traiter, sans contenu développé.

## Règles

- `enonce` : l'unité reformulée en une ou deux phrases autonomes, dans la langue du document.
- `extrait` : un passage **copié mot pour mot** du document (quelques mots à quelques phrases), qui permet de retrouver l'unité. Ne le modifie pas, ne le complète pas : il sera vérifié dans le texte.
- `utilite` : `haute` si l'unité apporte clairement de la matière au manuel visé ; `moyenne` si elle peut servir ; `nulle` si elle est hors sujet, redondante ou sans valeur (ne l'invente pas : omets-la plutôt).
- `themes` : un à trois mots-clés courts, pour regrouper les unités entre elles.
- N'invente rien : chaque unité vient du document. Un document sans intérêt donne une liste vide.

Réponds uniquement avec un bloc JSON de cette forme :

```json
{"unites": [{"type": "idee", "enonce": "...", "extrait": "...", "utilite": "haute", "themes": ["..."]}]}
```

## Document : $fichier

$texte
