# Exemple guidé : un manuel de Prompt Engineering, pas à pas

Ce dossier vous fait produire, de A à Z, un **manuel de Prompt Engineering** (en français, du débutant à l'expert) avec `ai_manual`. C'est un exemple : la même démarche vaut pour n'importe quel autre sujet (cuisine, droit, cybersécurité, histoire…), il suffit de changer le descriptif.

Durée : 15 minutes de manipulation, puis **plusieurs heures de calcul** pour le manuel complet avec un modèle qui raisonne longuement. On commence donc par un seul chapitre.

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `descriptif.txt` | Le descriptif libre à donner au modèle pour qu'il rédige le sujet (voie A) |
| `subjects/prompt-engineering/` | Le même sujet, **déjà rédigé** : `subject.yml` + `requirements.yml` (voie B) |
| `consigne-improve-toc.txt` | Exemple de consigne pour améliorer le plan (étape 5) |
| `consigne-improve.txt` | Exemple de consigne pour améliorer un chapitre (étape 8) |

Toutes les commandes se lancent **depuis la racine du dépôt** (`ai_manual/`), venv activé (`source .venv/bin/activate`) ; sinon remplacer `manual` par `.venv/bin/python -m manual_cli.cli`.

## Étape 0 — Prérequis

1. Installer le programme et configurer `~/.env` et `params.yml` (voir le [README](../../README.md#installation) et [`MANUAL.md`](../../MANUAL.md#4-configuration)).
2. Vérifier que `params.yml` affecte bien un modèle aux quatre rôles texte (`model_write`, `model_judge`, `model_think`, `model_rewriter`). Pour un premier essai, le même modèle partout convient ; pour la qualité, prendre un modèle plus fort pour `model_judge` et `model_rewriter`.

## Étape 1 — Créer le sujet

Le sujet est le cadrage du manuel : public, niveau, ton, progression, exclusions, critères de qualité. Deux voies, au choix.

### Voie A — Faire rédiger le sujet par le modèle (recommandé pour apprendre)

```bash
manual subject new prompt-engineering -f examples/prompt-engineering/descriptif.txt
```

Le modèle lit `descriptif.txt` et propose tous les champs de `subject.yml` ainsi que quelques critères de relecture. Rien n'est écrit tant que sa réponse n'est pas valide.

### Voie B — Partir du sujet tout prêt (rapide, sans appel au modèle)

```bash
mkdir -p subjects
cp -r examples/prompt-engineering/subjects/prompt-engineering subjects/
```

Le dossier `subjects/` n'est pas versionné : il est créé par `subject new` ou par cette copie.

## Étape 2 — Relire et ajuster le sujet

```bash
manual subject check prompt-engineering --show
```

La commande valide le sujet et affiche les prompts **tels qu'ils seront envoyés** au modèle. Relisez surtout le rôle, le public, les exclusions (ici : RAG, programmation, fine-tuning) et le plan directeur.

Pour retoucher :

```bash
manual subject refine prompt-engineering "ton plus pédagogique, plus d'exemples pour débutants"
manual subject edit prompt-engineering        # ou à la main, dans votre éditeur
```

`refine` garde l'ancienne version dans `subject.yml.bak`. Ajuster le sujet **avant** `init` donne un meilleur plan.

## Étape 3 — Générer le plan

```bash
manual --subject prompt-engineering init
```

Résultat dans `output/prompt-engineering/` :

- `toc.yml` : le plan, **modifiable à la main** (titres et descriptions, sans numéro) ;
- `00_toc.md` : la même chose, lisible ;
- `manifest.json` et `memory.md` : le suivi et la mémoire (à ne pas éditer).

Le plan contient une introduction, des parties, des chapitres avec leurs sous-sections, et une conclusion. Relisez `00_toc.md`.

> Tant qu'**aucun chapitre n'est écrit**, vous pouvez tout refaire : `manual --subject prompt-engineering init --force` (réinitialise avancement et mémoire).

## Étape 4 — Corriger le plan à la main (facultatif)

Ouvrez `output/prompt-engineering/toc.yml` : renommez, réordonnez, ajoutez ou supprimez des chapitres. **Aucun numéro à corriger** : ils sont recalculés. Un chapitre ajouté ou retitré passera `pending`. Pour vérifier :

```bash
manual --subject prompt-engineering status
```

## Étape 5 — Faire améliorer le plan par le modèle (facultatif)

```bash
manual --subject prompt-engineering improve-toc -f examples/prompt-engineering/consigne-improve-toc.txt
```

Le modèle améliore le plan en partant de l'existant. Les chapitres déjà écrits sont figés, et l'ancienne version est archivée dans `output/prompt-engineering/toc_history/`. Sans consigne (`improve-toc` seul), il « relit et améliore ».

## Étape 6 — Ajouter des critères par partie (facultatif)

Les critères propres à chaque partie dépendent des titres **exacts** du plan : ils se demandent donc *après* `init`.

```bash
manual --subject prompt-engineering subject criteria
```

Les critères proposés sont ajoutés à `subjects/prompt-engineering/requirements.yml` (ancienne version : `requirements.yml.bak`). Si vous renommez des parties ensuite, relancez avec `--force`.

## Étape 7 — Écrire un premier chapitre, juger la qualité

```bash
manual --subject prompt-engineering write -s 1
```

Pour chaque section, le programme enchaîne : **rédaction → relecture par le juge → réécriture si un critère bloquant manque → mise à jour de la mémoire**. Le chapitre est dans `output/prompt-engineering/01_….md`.

Relisez-le. Si le résultat ne convient pas : ajustez le sujet (étape 2), les critères (étape 6) ou les modèles (`params.yml`), puis `manual --subject prompt-engineering redo 1`.

Conseil : consultez aussi `manual --subject prompt-engineering traces` (interface web, extra `web`) pour voir les appels, leurs durées et d'éventuels timeouts.

## Étape 8 — Écrire tout le manuel

```bash
manual --subject prompt-engineering write            # tout ce qui n'est pas encore fait, 4 workers
manual --subject prompt-engineering write -w 8       # plus de parallélisme
manual --subject prompt-engineering status           # avancement
```

Les chapitres sont écrits d'abord, puis l'introduction (section 0) et la conclusion. Si l'exécution s'interrompt ou si des sections échouent (`failed`), **relancez la même commande** : les sections terminées sont conservées.

## Étape 9 — Corriger et enrichir

| Besoin | Commande |
|---|---|
| Un chapitre est raté | `manual --subject prompt-engineering redo 7` |
| Un chapitre est correct mais à enrichir ou à dédoublonner | `manual --subject prompt-engineering improve 7 -f examples/prompt-engineering/consigne-improve.txt` |
| Plusieurs chapitres | `manual --subject prompt-engineering improve 3 5-8 -i "plus d'exemples de prompts"` |

`improve` ne remplace un chapitre que si la nouvelle version passe la relecture (l'ancienne reste en `.md.bak` ; une version refusée est écrite en `.candidate.md`).

## Étape 10 — Le glossaire

```bash
manual --subject prompt-engineering glossary
```

Produit `output/prompt-engineering/glossaire.md` : les termes de tous les chapitres **terminés**, fusionnés, triés alphabétiquement, avec leurs chapitres. À relancer quand de nouveaux chapitres sont terminés.

## Étape 11 — Publier un chapitre sur LinkedIn (facultatif)

```bash
manual --subject prompt-engineering publish 1 --no-image
```

Prépare `output/prompt-engineering/publish/…/` : `article.html` (à copier dans l'éditeur d'article LinkedIn) et `post.txt` (brouillon de post avec le jeton `{ARTICLE_URL}`). Sans `--no-image`, une image de couverture est aussi générée (clé OpenAI requise). **Rien n'est publié automatiquement.**

## Résultat

```
output/prompt-engineering/
  toc.yml  00_toc.md  manifest.json  memory.md
  00_introduction.md  01_….md  …  NN_conclusion.md
  glossaire.md
  toc_history/  traces/  publish/
```

## Et pour un autre sujet ?

Rien à changer dans la démarche : écrivez un `descriptif.txt` pour votre sujet (public, objectif, ce qu'il faut couvrir et exclure, ton), puis `manual subject new mon-sujet -f descriptif.txt` et reprenez à l'étape 2. Pour aller plus loin : [`MANUAL.md`](../../MANUAL.md).
