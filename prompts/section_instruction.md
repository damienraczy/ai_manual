# Tâche : rédiger une section du manuel

Rédige la section suivante, avec exactement le titre et les sous-sections fixés par la table des matières :

- Numéro : $numero
- Titre : $titre
- Description : $description
- Sous-sections (numéro, titre, puis ce que chacune doit couvrir) :
$sous_sections

## Plan complet de l'ouvrage

Ce que les autres chapitres traitent ne se développe pas ici ; ce que les chapitres précédents ont posé est acquis.

$plan

## Mémoire du manuel

Résumé de ce qui est déjà écrit. Garde la même terminologie ; ne reprends ni les idées développées, ni les images, ni les exemples déjà utilisés : choisis-en d'autres. Ce résumé ne figure pas dans ta réponse.

$digest

$sources

## Contraintes de sortie — STRICT

$role_note

- Première ligne : `## $intitule`.
- Juste après : une synthèse du chapitre en un ou deux paragraphes (environ 7 à 10 % de sa longueur), en bloc de citation Markdown (chaque ligne commence par `>`), sans titre ni étiquette.
- Puis chaque sous-section, dans l'ordre, sous un titre `###` qui reprend seulement son numéro et son titre.
- Dernière ligne, sans rien après :

`--- Fin de la section $numero — Dis « continue » pour la suivante ---`
