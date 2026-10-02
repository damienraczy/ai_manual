# Tâche : consolider le glossaire d'un manuel

Voici les termes extraits chapitre par chapitre (`terme — définition (chap. N)`). Produis le glossaire final du manuel :

- fusionne les doublons et variantes d'un même terme (casse, pluriel, sigle et forme développée) en une seule entrée, avec une définition unique, claire et cohérente ;
- conserve pour chaque entrée la liste exacte des chapitres où le terme est traité (`chapitres`, numéros entiers) ;
- retire les entrées triviales ou redondantes ;
- n'invente aucun terme ni aucune définition qui ne découle pas des extraits ;
- écris dans la langue des extraits.

Réponds uniquement avec un bloc JSON de cette forme :

```json
{"entrees": [{"terme": "...", "definition": "...", "chapitres": [1, 3]}]}
```

## Termes extraits

$entrees
