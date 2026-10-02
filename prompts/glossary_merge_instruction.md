# Tâche : consolider le glossaire d'un manuel

Voici les termes extraits chapitre par chapitre (`terme — définition (chap. N)`). Produis le glossaire final du manuel :

- Fusion : regroupe les doublons et variantes (casse, singulier/pluriel, sigle et forme développée) sous une seule entrée normalisée :
- Synthèse : rédige une définition unique, fluide et autonome combinant fidèlement les données des extraits, sans rien inventer.
- Références : pour chaque entrée, liste les numéros de chapitres associés sous forme d'entiers, dédoublonnés et triés par ordre croissant (ex. `[1, 3, 5]`).
- Filtrage : retire les termes triviaux ou non pertinents pour un glossaire de référence.
- n'invente aucun terme ni aucune définition qui ne découle pas des extraits ;
- Langue : conserve la langue des extraits fournis.

## Format de sortie :
Réponds uniquement avec un bloc ```json``` strictement valide,  sans texte avant ni après, de cette forme :

```json
{
  "entrees": [
    {
      "terme": "Terme normalisé",
      "definition": "Définition consolidée.",
      "chapitres": [1, 3]
    }
  ]
}
```

## Termes extraits

$entrees


