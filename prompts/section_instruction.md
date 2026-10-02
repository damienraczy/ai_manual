# Tâche : rédiger une section du manuel

Rédige **uniquement** le chapitre suivant, en respectant exactement son titre et ses sous-sections tels que fixés dans la table des matières validée :

- Numéro : $numero
- Titre : $titre
- Description : $description
- Sous-sections attendues (numéro, titre, puis ce que chacune doit couvrir) :
$sous_sections

## Plan complet de l'ouvrage

Voici le plan de tout l'ouvrage. Situe ce chapitre dans l'ensemble : ne développe pas ce qui relève d'un autre chapitre (renvoie-y brièvement si utile) et appuie-toi sur ce que les chapitres précédents ont posé.

$plan

## Mémoire du manuel (ce qui a déjà été écrit)

Utilise ce résumé pour rester cohérent (terminologie, niveau déjà atteint) et pour ne pas te répéter : ne reprends ni les idées déjà développées, ni les métaphores et images déjà utilisées, ni les exemples déjà donnés — choisis-en de nouveaux ; renvoie plutôt au chapitre concerné. Ne recopie pas ce résumé dans ta réponse.

$digest

$sources

## Contraintes de sortie — STRICT

$role_note

- Commence directement par `## $intitule` (pas de titre de niveau supérieur, pas de préambule).
- Rédige un résumé exécutif représentant environ 7 % à 10 % du volume total de la section, formaté en bloc de citation Markdown (chaque ligne débutant par `>`).
- Traite chaque sous-section annoncée, dans l'ordre, avec un titre `###` par sous-section, en couvrant ce que sa description annonce (le titre `###` ne reprend que le numéro et le titre, sans la description).
- Termine ta réponse par exactement cette ligne, sans rien après :

`--- Fin de la section $numero — Dis « continue » pour la suivante ---`

- Ne rédige aucune autre section, n'ajoute pas de résumé général du manuel, n'ajoute pas de texte après la ligne de fin.
