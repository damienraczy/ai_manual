# Tâche : générer la table des matières du manuel

Propose la table des matières complète et détaillée du manuel décrit dans le prompt système. Elle doit suivre cette progression : $plan_directeur.

## Format de sortie — STRICT

Réponds **uniquement** avec un unique bloc de code ```json contenant un objet conforme exactement au schéma suivant, sans aucun texte avant ou après le bloc :

```json
{
  "titre_manuel": "string",
  "introduction": {
    "titre": "Introduction",
    "description": "une phrase",
    "sous_sections": [
      {"numero": "0.1", "titre": "string", "description": "une phrase"}
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
          "description": "une phrase",
          "sous_sections": [
            {"numero": "1.1", "titre": "string", "description": "une phrase"}
          ]
        }
      ]
    }
  ],
  "conclusion": {
    "titre": "Conclusion",
    "description": "une phrase",
    "sous_sections": []
  }
}
```

Règles :
- Numérotation :
    - parties : chiffres romains ("I", "II", "III", ...) ;
    - chapitres : entiers consécutifs de 1 à N sur l'ensemble du manuel (ne recommence pas à 1 à chaque partie) ;
    - sous-sections : `"<numero_chapitre>.<rang>"` (ex. "6.3"), `"0.<rang>"` pour l'introduction.
- `introduction` et `conclusion` sont deux sections **hors des parties** (numérotées automatiquement) : ne crée ni partie introductive ni partie conclusive. Leurs sous-sections sont facultatives (`[]` accepté).
- Équilibre : chaque partie compte au moins 2 chapitres ; un chapitre subdivisé compte de 2 à 5 sous-sections.
- Descriptions : une phrase qui dit ce que l'élément couvre ; elles guideront la rédaction de chaque chapitre.
- Intitulés : concis, compréhensibles hors contexte, sans point final ; même construction grammaticale entre entrées de même niveau (style nominal de préférence, infinitif pour un guide pratique, jamais de question).
- JSON strictement valide (guillemets doubles, pas de virgule finale), sans commentaire ni clé additionnelle.
