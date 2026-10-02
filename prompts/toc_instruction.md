# Tâche : générer la table des matières du manuel

Propose la table des matières complète et détaillée du manuel décrit dans le prompt système. Elle doit suivre cette progression : $plan_directeur.

## Format de sortie — STRICT

Réponds **uniquement** avec un unique bloc de code ```json contenant un objet conforme exactement au schéma suivant, sans aucun texte avant ou après le bloc :

```json
{
  "titre_manuel": "string",
  "introduction": {
    "titre": "Introduction",
    "description": "une phrase résumant l'introduction",
    "sous_sections": [
      {"numero": "0.1", "titre": "string", "description": "une phrase résumant la sous section"}
    ]
  },
  "parties": [
    {
      "numero": "I",
      "titre": "string",
      "chapitres": [
        {
          "numero": 1,
          "titre": "string",
          "description": "une phrase résumant le chapitre",
          "sous_sections": [
            {"numero": "1.1", "titre": "string", "description": "une phrase résumant la sous section"}
          ]
        }
      ]
    }
  ],
  "conclusion": {
    "titre": "Conclusion",
    "description": "une phrase résumant la conclusion",
    "sous_sections": []
  }
}
```

Règles impératives :
- Structure et numérotation :
    - `numero` des parties : chiffres romains ("I", "II", "III", ...).
    - `numero` des chapitres : entiers consécutifs de 1 à N sur l'ensemble du manuel (ne recommence pas à 1 à chaque partie).
    - `numero` des sous-sections : `"<numero_chapitre>.<rang>"` (ex. "6.3").
    - `introduction` et `conclusion` sont deux sections du manuel **hors des parties** (numérotées automatiquement 0 et après le dernier chapitre) : ne crée donc pas de partie introductive ni de partie conclusive. Leurs sous-sections sont facultatives (`[]` accepté), celles de l'introduction se numérotent `"0.<rang>"`.
    - Équilibre des parties : chaque partie du corps de texte doit contenir au moins 2 chapitres (jamais de chapitre unique). 
    - Équilibre des sous-sections : si un chapitre est subdivisé, il doit comporter au minimum 2 sous-sections (jamais de sous-section orpheline type "X.1" sans "X.2"). Viser entre 2 et 5 sous-sections par chapitre.
- Format de sortie
    - Format JSON strictement valide (guillemets doubles, pas de virgule finale / trailing comma).
    - Aucun commentaire, aucune clé additionnelle, aucun texte ni balise Markdown hors du bloc JSON brut.
- Les titres et sous titres :
    - Casse française stricte : majuscule uniquement au premier mot et aux noms propres (proscrire absolument la capitalisation anglo-saxonne / "Title Case"). Accents obligatoires sur les majuscules.
    - Parallélisme syntaxique : stricte homogénéité grammaticale entre entrées de même niveau (privilégier le style nominal ; réserver l'infinitif aux guides pratiques ; proscrire le style interrogatif).
    - Intitulés : concis, explicites, autonomes (compréhensibles hors contexte) et sans point final.
