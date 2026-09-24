# Tâche : modifier le cadrage d'un manuel selon une consigne

Voici le cadrage actuel du manuel (fichier `subject.yml`) :

```yaml
$current
```

Consigne de l'auteur (elle peut comporter plusieurs demandes : applique-les toutes) :

<consigne>
$instruction
</consigne>

Renvoie le cadrage **complet** mis à jour, avec exactement les mêmes clés que le cadrage actuel : `titre`, `langue`, `role`, `objectif`, `public`, `niveau`, `ton`, `plan_directeur`, `exclusions` (liste de textes), `instructions` (texte).

- Ne modifie que ce que la consigne implique ; recopie tout le reste à l'identique.
- Si la consigne demande d'ajouter une consigne de rédaction, complète `instructions` sans effacer l'existant.
- Si la consigne concerne la structure du manuel, adapte `plan_directeur`.

```json
{
  "titre": "...", "langue": "...", "role": "...", "objectif": "...", "public": "...",
  "niveau": "...", "ton": "...", "plan_directeur": "...", "exclusions": ["..."], "instructions": "..."
}
```
