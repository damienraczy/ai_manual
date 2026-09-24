# Tâche : générer la table des matières du manuel

Propose la table des matières complète et détaillée du manuel décrit dans le prompt système. Elle doit couvrir : fondamentaux → techniques intermédiaires → techniques avancées → patterns experts → évaluation & optimisation → applications industrielles → frontier techniques 2025-2026.

## Format de sortie — STRICT

Réponds **uniquement** avec un unique bloc de code ```json contenant un objet conforme exactement au schéma suivant, sans aucun texte avant ou après le bloc :

```json
{
  "titre_manuel": "string",
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
            {"numero": "1.1", "titre": "string"}
          ]
        }
      ]
    }
  ]
}
```

Règles impératives :
- `numero` des parties : chiffres romains ("I", "II", "III", ...).
- `numero` des chapitres : entiers consécutifs de 1 à N sur l'ensemble du manuel (ne recommence pas à 1 à chaque partie).
- `numero` des sous-sections : `"<numero_chapitre>.<rang>"` (ex. "6.3").
- Aucun commentaire, aucune clé additionnelle, aucun texte hors du bloc JSON.
- Le JSON doit être strictement valide (guillemets doubles, pas de virgule finale).
