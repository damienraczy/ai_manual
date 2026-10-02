# Tâche : améliorer une section du manuel

Une première version du chapitre suivant a déjà été rédigée. Utilise-la comme **amorce** pour produire une nouvelle version complète, améliorée et enrichie : respecte exactement son titre et ses sous-sections tels que fixés dans la table des matières validée.

- Numéro : $numero
- Titre : $titre
- Description : $description
- Sous-sections attendues (numéro, titre, puis ce que chacune doit couvrir) :
$sous_sections

## Consigne d'amélioration

$consigne

Règles :
- Conserve ce qui est juste et bien formulé dans la version actuelle ; ne la recopie pas telle quelle, enrichis-la.
- Applique la consigne ci-dessus partout où elle s'applique.
- Le résultat doit être un chapitre complet et autonome, pas une liste de modifications ni un commentaire sur la version actuelle.

## Plan complet de l'ouvrage

Voici le plan de tout l'ouvrage. Situe ce chapitre dans l'ensemble : ne développe pas ce qui relève d'un autre chapitre (renvoie-y brièvement si utile) et appuie-toi sur ce que les chapitres précédents ont posé.

$plan

## Mémoire du manuel (ce qui a déjà été écrit)

Utilise ce résumé pour rester cohérent (terminologie, niveau déjà atteint) et pour ne pas te répéter : ne reprends ni les idées déjà développées, ni les métaphores et images déjà utilisées, ni les exemples déjà donnés — choisis-en de nouveaux ; renvoie plutôt au chapitre concerné avec les autres chapitres. Il peut déjà mentionner la version actuelle de ce chapitre. Ne le recopie pas dans ta réponse.

$digest

$sources

## Version actuelle du chapitre (amorce)

<version_actuelle>
$contenu_existant
</version_actuelle>

## Contraintes de sortie — STRICT

$role_note

- Commence directement par `## $intitule` (pas de titre de niveau supérieur, pas de préambule).
- Traite chaque sous-section annoncée, dans l'ordre, avec un titre `###` par sous-section, en couvrant ce que sa description annonce (le titre `###` ne reprend que le numéro et le titre, sans la description).
- Termine ta réponse par exactement cette ligne, sans rien après :

`--- Fin de la section $numero — Dis « continue » pour la suivante ---`

- Ne rédige aucune autre section, n'ajoute pas de résumé général du manuel, n'ajoute pas de texte après la ligne de fin.
