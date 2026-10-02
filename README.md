# ai_manual

<img src="assets/social-preview.jpg" alt="ai_manual : un robot présente « The Basics of Prompt Engineering » sur un tableau" width="800">

`ai_manual` est un outil en ligne de commande (`manual`) qui **rédige de bout en bout un manuel de référence complet, sur n'importe quel sujet** (une discipline technique, un métier, un domaine juridique, une méthode, un cours…), en orchestrant plusieurs appels à des modèles de langage (LLM) : il propose un plan, écrit chaque chapitre, le fait relire et corriger automatiquement par un second modèle, puis garde en mémoire ce qui a été dit pour rester cohérent d'un chapitre à l'autre.

Il fonctionne **sujet par sujet**. Le dépôt ne fournit aucun sujet : le dossier `subjects/` n'est pas versionné et chacun crée les siens. Un sujet se crée en une commande à partir d'un descriptif (court ou long, en fichier), puis se retouche à volonté. **Pour voir toute la démarche sur un cas concret, suivez l'[exemple guidé pas à pas](examples/prompt-engineering/README.md)** : créer un manuel de Prompt Engineering, du sujet au glossaire et à la publication.

**En bref**

- **Un manuel structuré, cohérent et contrôlé** : plan validé avant la rédaction, critères de qualité vérifiés chapitre par chapitre, réécriture automatique en cas de défaut.
- **Vous gardez la main** : refaire un chapitre, l'*améliorer* à partir de son texte, *améliorer le plan* sans perdre ce qui est déjà écrit, cibler certaines sections, reprendre après une interruption.
- **Tout est réglable** : sujet, critères, prompts, modèles (un par rôle), parallélisme.
- **Rien n'est détruit en silence** : chaque modification importante laisse une sauvegarde ou une archive (voir [Garanties](#garanties-et-sécurités)).
- **Rien n'est publié automatiquement** : la préparation d'une publication LinkedIn est fournie, la publication reste manuelle.

> La documentation complète et exhaustive est dans [`MANUAL.md`](MANUAL.md).

## Sommaire

- [Vocabulaire](#vocabulaire)
- [Ce que fait le programme](#ce-que-fait-le-programme)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Démarrage rapide](#démarrage-rapide)
- [Exemple guidé : un manuel de Prompt Engineering](#exemple-guidé--un-manuel-de-prompt-engineering)
- [Référence des commandes](#référence-des-commandes)
- [Guide : les sujets](#guide--les-sujets)
- [Guide : écrire et suivre le manuel](#guide--écrire-et-suivre-le-manuel)
- [Guide : améliorer le contenu et le plan](#guide--améliorer-le-contenu-et-le-plan)
- [Publication LinkedIn (optionnelle)](#publication-linkedin-optionnelle)
- [Fichiers produits](#fichiers-produits)
- [Garanties et sécurités](#garanties-et-sécurités)
- [Personnaliser les prompts](#personnaliser-les-prompts)
- [Architecture et structure du dépôt](#architecture-et-structure-du-dépôt)
- [Tests](#tests)
- [Limites connues](#limites-connues)
- [Remerciements](#remerciements)
- [Licence et propriété](#licence-et-propriété)

## Vocabulaire

| Terme | Sens |
|---|---|
| **Sujet** | Le cadrage d'un manuel : de quoi il parle, pour qui, à quel niveau, sur quel ton, avec quelle progression et quels critères de qualité. Un dossier `subjects/<identifiant>/`. |
| **Plan** (ou table des matières, TOC) | Les parties, chapitres et sous-sections du manuel, générés par le modèle et enregistrés dans `toc.yml` (le plan, modifiable à la main) et `manifest.json` (le suivi) ; `00_toc.md` n'en est qu'une vue lisible. Chaque chapitre et chaque sous-section porte une `description` d'une phrase, transmise au rédacteur. |
| **Section** (ou chapitre) | L'unité de rédaction : un chapitre du plan, écrit dans son propre fichier Markdown. L'**introduction** (section 0) et la **conclusion** (section N+1) sont des sections hors des parties, facultatives. Statuts : `pending` (à écrire), `done` (accepté), `failed` (refusé par la relecture, ou marqueur de fin absent). |
| **Rôles LLM** | `model_write` (rédacteur), `model_judge` (juge), `model_rewriter` (réécrivain), `model_think` (mémoire), `model_image` (couverture, optionnel). Chacun peut utiliser un modèle différent. |
| **Critères** | Les exigences de qualité appliquées par le juge : communes à tous les sujets, propres au sujet, ou propres à une partie. Sévérité `bloquant` (force une réécriture) ou `recommande` (signalé sans bloquer). |
| **Mémoire** | Le résumé structuré de ce qui a déjà été écrit (`memory.md`) : idées développées, métaphores et images, termes définis, exemples, décisions de style, chacun avec son chapitre. Transmis à chaque rédaction pour éviter contradictions et redites. |
| **Plan de l'ouvrage** | Le plan complet, transmis à chaque rédaction avec le chapitre en cours signalé, pour que chaque section sache ce que contiennent les autres. |
| **Glossaire** | `glossaire.md`, généré par `manual glossary` à partir des chapitres terminés. |

## Ce que fait le programme

```
sujet ──► plan ──► rédaction ──► relecture (juge) ──► accepté ? ──oui──► mémoire ──► chapitre suivant
(cadrage) (TOC)        ▲                                  │
                       └──── réécriture ◄───── non ───────┘   (au plus --max-rewrite fois)
```

1. **Cadrage du sujet.** Rôle de l'auteur, public, niveau, ton, progression, exclusions, critères propres. Peut être rédigé par le LLM à partir d'un descriptif (court ou long, en fichier), puis retouché par consigne ou à la main.
2. **Plan.** Un LLM propose une table des matières complète (introduction, parties, chapitres, conclusion), à relire et à améliorer avant de commencer à écrire. Sa réponse est un JSON validé (trois essais au plus, avec renvoi de l'erreur au modèle) : chaque chapitre et chaque sous-section doit avoir sa description. Le plan est enregistré dans `toc.yml`, sans numéros, et se modifie à la main.
3. **Rédaction.** Chaque chapitre est écrit en suivant strictement le plan (titre, sous-sections et ce que chacune doit couvrir), en connaissant le plan complet de l'ouvrage et la mémoire ; plusieurs chapitres peuvent l'être en parallèle. L'introduction et la conclusion sont écrites après les chapitres.
4. **Relecture automatique.** Le juge évalue chaque chapitre selon les critères. Si un critère bloquant n'est pas rempli, le réécrivain corrige et le juge relit, dans la limite de `--max-rewrite` cycles.
5. **Mémoire.** Après chaque chapitre accepté, le résumé structuré est mis à jour (idées, métaphores, termes et exemples déjà utilisés), pour limiter les répétitions.
6. **Reprise et amélioration.** L'avancement est sauvegardé chapitre par chapitre : on peut interrompre, reprendre, refaire un chapitre, l'améliorer à partir de son texte ou améliorer le plan sans repartir de zéro.

Un chapitre n'est marqué `done` que si le juge l'accepte **et** que son marqueur de fin est présent dans le texte.

> Compter plusieurs heures pour un manuel complet avec un modèle qui raisonne longuement.

## Prérequis

- Python **3.10 ou plus récent**
- Un accès à un service **Ollama Cloud** (URL et clé API) pour tous les rôles texte (rédaction des chapitres, relecture, rédaction des sujets et du plan)
- *Optionnel* : une clé **OpenAI** pour générer des images de couverture (`manual publish`)

## Installation

```bash
git clone https://github.com/damienraczy/ai_manual.git ai_manual
cd ai_manual

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[web]"          # programme + interface web des traces
# pip install -e ".[test,web]"   # idem, avec les outils de test
```

L'installation en mode éditable (`-e`) est nécessaire : le programme lit les dossiers `prompts/`, `requirements/` et `subjects/` du dépôt à l'exécution. Elle crée la commande `manual` dans le venv ; sans activer le venv, on peut aussi lancer `.venv/bin/python -m manual_cli.cli <commande>`.

## Configuration

La configuration repose sur deux fichiers : `params.yml` (choix des modèles, dans le dépôt) et `~/.env` (secrets, dans le répertoire personnel de l'utilisateur). Les deux sont relus à chaque appel LLM : une modification prend effet immédiatement, sans relancer le programme.

### 1. Les secrets : `~/.env`

Créer le fichier `.env` **dans le répertoire personnel de l'utilisateur** (`~/.env`, par exemple `/Users/prenom/.env` sous macOS ou `/home/prenom/.env` sous Linux), et non dans le dépôt :

```dotenv
# Rôles texte (obligatoire) : Ollama Cloud
OLLAMA_CLOUD_URL=https://...
OLLAMA_API_KEY=...

# Image de couverture (optionnel, uniquement pour `manual publish`)
OPENAI_URL=https://api.openai.com/v1
OPENAI_API_KEY=...
```

Points d'attention :

- `OLLAMA_CLOUD_URL` peut se terminer par `/api` ou non : le programme évite de le doubler.
- `OPENAI_URL` peut pointer sur la racine `/v1` ou sur un chemin plus long (`/v1/responses`) : il est tronqué après `/v1`.
- Restreindre les droits du fichier : `chmod 600 ~/.env`.
- Ce fichier ne doit jamais être versionné ni partagé.
- Une variable manquante provoque une erreur explicite (`Variables d'environnement manquantes dans ~/.env : ...`) ; le programme ne bascule jamais silencieusement sur autre chose.

### 2. Le choix des modèles : `params.yml`

```bash
cp params.example.yml params.yml
```

`params.yml` contient deux parties :

- **`models:`** : le catalogue des modèles disponibles. Pour chacun : `provider`, `name`, `url` et `api_key` (les *noms* des variables de `~/.env`, pas leurs valeurs) et `timeout` en secondes. Facultatif : `think` (modèles Ollama), transmis tel quel au champ `think` de l'API : `true`, `false` ou un niveau propre au modèle. Sans lui, le modèle garde son défaut. Les niveaux acceptés se lisent dans `thinking.values` de `POST /api/show` (par exemple GLM 5.3 : `low`, `high`, `max`, avec `max` par défaut ; sa réflexion ne peut pas être désactivée, `false` est sans effet). Pour réduire la réflexion d'un modèle, déclarer une seconde entrée du même modèle avec `think: low`. Toute autre clé dans un modèle (ex. `effort`) est refusée au démarrage plutôt qu'ignorée.
- **`llm_config:`** : l'affectation d'un modèle à chaque rôle (`llm:`), et `timeout`, le délai en secondes appliqué aux modèles qui n'en définissent pas.

| Rôle | Fonction | Fournisseur autorisé |
|---|---|---|
| `model_write` | rédige les sujets, la table des matières (et son amélioration), les chapitres et le glossaire | `ollama` |
| `model_judge` | relit et valide chaque chapitre | `ollama` |
| `model_think` | met à jour la mémoire inter-chapitres | `ollama` |
| `model_rewriter` | réécrit un chapitre rejeté | `ollama` |
| `model_image` | image de couverture (optionnel) | `openai` |

Seul le bloc nommé exactement `llm_config` est lu. Les autres blocs (`FASTllm_config`, `xllm_config`) sont des préréglages : pour en activer un, renommer les blocs (l'ancien `llm_config` en `autrellm_config`, le préréglage en `llm_config`).

`params.yml` ne contient aucun secret mais reste propre à chaque installation ; il est exclu du dépôt (voir `.gitignore`).

## Démarrage rapide

Une fois la [configuration](#configuration) faite, du sujet au premier chapitre :

```bash
manual subject new mon-sujet "Manuel de … pour …"        # 1. le modèle rédige le cadrage du sujet
manual subject check mon-sujet --show                    # 2. relire le cadrage et les prompts obtenus
manual --subject mon-sujet init                          # 3. générer le plan → output/mon-sujet/00_toc.md
manual --subject mon-sujet improve-toc                   # 4. (facultatif) améliorer le plan
manual --subject mon-sujet write -s 1                    # 5. rédiger le chapitre 1 pour juger la qualité
manual --subject mon-sujet write                         # 6. rédiger tout le reste
```

Le dossier `subjects/` est créé au premier `manual subject new` : un clone du dépôt n'a aucun sujet au départ. Tant qu'il n'existe qu'un seul sujet, `--subject` peut être omis.

## Exemple guidé : un manuel de Prompt Engineering

Le dossier [`examples/prompt-engineering/`](examples/prompt-engineering/README.md) déroule, étape par étape et commande par commande, la création d'un manuel complet : création du sujet (par le modèle à partir d'un descriptif, ou depuis un sujet tout prêt), relecture, plan (génération, édition à la main, amélioration), critères par partie, premier chapitre, rédaction du manuel entier, corrections, glossaire, publication. Il contient le descriptif, le sujet prêt à l'emploi et des exemples de consignes. La démarche est la même pour tout autre sujet.

## Référence des commandes

Deux options se placent **avant** la sous-commande :

- `--subject SUJET` choisit le sujet (un dossier de `subjects/`). Facultatif tant qu'il n'existe qu'un seul sujet ; **dès qu'il y en a plusieurs, il devient obligatoire** pour `init`, `write`, `redo`, `improve`, `improve-toc`, `status`, `glossary`, `publish` et `traces` (sauf `status`, `glossary`, `publish` et `traces` si `--output` est donné). `subject criteria` et `subject edit` acceptent aussi `--subject` à la place de l'identifiant.
- `--output DIR` choisit le répertoire de sortie (défaut : `output/<sujet>/` dans le dépôt).

### Génération

| Commande | Effet |
|---|---|
| `manual init [--force]` | Génère le plan. Refuse d'écraser un plan existant sans `--force` ; avec `--force`, l'avancement **et la mémoire sont réinitialisés** (les fichiers de chapitres restent sur le disque). |
| `manual write` | Rédige toutes les sections qui ne sont pas `done`, c'est-à-dire en attente **et** en échec (`failed`), 4 workers en parallèle par défaut : d'abord les chapitres, puis l'introduction et la conclusion. Relancer la commande reprend donc après une interruption ou un échec. |
| `manual write -s 1 3 5-8` | Rédige seulement les sections 1, 3 et 5 à 8 (`-s 0` : l'introduction). |
| `manual write -w 8` | Utilise 8 workers en parallèle. |
| `manual write --max-rewrite 3` | Autorise jusqu'à 3 cycles de réécriture après un rejet du juge (défaut : 2). |
| `manual status` | Affiche l'état de chaque section (`pending`, `done`, `failed`) et le total. Code de sortie `1` si aucun plan n'existe encore. |
| `manual redo N [--max-rewrite K]` | Régénère la section N **depuis zéro** (sans relire l'existant). |
| `manual glossary` | Génère `glossaire.md` à partir des chapitres terminés : extraction des termes chapitre par chapitre, puis consolidation (doublons fusionnés, tri alphabétique, chapitres cités). |

### Amélioration

| Commande | Effet |
|---|---|
| `manual improve N… [-i "consigne" \| -f FICHIER] [--max-rewrite K] [-w W]` | Améliore des sections déjà écrites : leur texte sert d'amorce à une nouvelle génération enrichie. Sans consigne : « relis et améliore ». |
| `manual improve-toc [-i "consigne" \| -f FICHIER]` | Améliore le plan en partant de l'actuel : chapitres rédigés figés, avancement conservé, version précédente archivée. |

### Sujets

| Commande | Effet |
|---|---|
| `manual subject list` | Liste les sujets (un sujet incomplet est signalé `INVALIDE`). |
| `manual subject new SLUG ["descriptif" \| -f FICHIER]` | Crée un sujet : rédigé par le modèle si un descriptif est donné (en ligne ou dans un fichier, `-` = entrée standard), sinon squelette à remplir. |
| `manual subject refine SLUG ["consigne" \| -f FICHIER]` | Retouche un sujet selon une consigne en langage naturel. |
| `manual subject edit [SLUG]` | Ouvre `subject.yml` dans `$VISUAL` / `$EDITOR`, puis le valide. |
| `manual subject criteria [SLUG] [--force]` | Propose des critères de relecture par partie du plan généré. |
| `manual subject check [SLUG] [--show]` | Valide un sujet ; `--show` affiche les prompts tels qu'ils seront envoyés. |
| `manual subject delete SLUG [-y] [--with-output]` | Supprime définitivement un sujet, après confirmation. |

### Publication et diagnostic

| Commande | Effet |
|---|---|
| `manual publish N [--no-image]` | Prépare le paquet de publication LinkedIn de la section N (voir [plus bas](#publication-linkedin-optionnelle)). |
| `manual traces [--host H] [--port P]` | Lance l'interface web (défaut : `127.0.0.1:8787`) sur le journal des appels LLM. |

## Guide : les sujets

Un **sujet** est un dossier `subjects/<identifiant>/` qui décrit de quoi parle le manuel. Le dossier `subjects/` est **ignoré par git** (voir `.gitignore`) : les sujets restent locaux à chaque installation, à sauvegarder séparément si besoin. Les règles de forme communes à tous les sujets (format JSON du plan, marqueur de fin de section, consignes de relecture) restent dans `prompts/` et ne se touchent pas.

### Créer un sujet

**Rédigé par le modèle** (le plus rapide) : donner l'identifiant et un descriptif.

```bash
manual subject new cybersecurite-dirigeants "Manuel de cybersécurité pour dirigeants non techniques, du débutant à l'opérationnel"
manual subject check cybersecurite-dirigeants --show   # relire le cadrage et les prompts obtenus
```

Pour un descriptif plus long, le mettre dans un fichier texte (UTF-8) et le passer avec `-f` / `--brief-file` (`-` lit l'entrée standard) :

```bash
manual subject new cybersecurite-dirigeants -f descriptif.txt
```

Plus le descriptif est précis, meilleur est le cadrage. Exemple de contenu de `descriptif.txt` :

```text
Manuel de cybersécurité destiné aux dirigeants non techniques de PME.
Public : dirigeants et directeurs généraux, sans formation informatique.
Objectif : leur permettre de décider, arbitrer et piloter, pas de configurer.
À couvrir : panorama des menaces, gouvernance et responsabilités, budget,
assurance cyber, gestion de crise et communication.
À exclure : configuration technique, cryptographie détaillée.
Ton : direct, sans jargon ; chaque chapitre s'appuie sur un incident réel.
```

Le modèle (`model_write`) propose tous les champs de `subject.yml` et quelques critères de relecture propres au sujet. Rien n'est écrit tant que sa réponse n'est pas valide.

**À la main** : sans descriptif, `manual subject new <identifiant>` crée un squelette dont les champs valent « À COMPLÉTER » (refusés tant qu'ils restent tels quels), à remplir avec `manual subject edit <identifiant>`. Un identifiant ne contient que des minuscules, des chiffres et des tirets.

### Retoucher ou supprimer un sujet

| Commande | Effet |
|---|---|
| `manual subject refine SLUG "consigne"` ou `refine SLUG -f consigne.txt` | Le modèle applique la consigne (ex. « ton plus décontracté, sans juridique »), donnée en ligne ou dans un fichier, et affiche les champs modifiés. L'ancienne version est conservée dans `subject.yml.bak`. |
| `manual subject edit [SLUG]` | Ouvre `subject.yml` dans l'éditeur, puis le valide à la fermeture. |
| `manual subject check [SLUG] [--show]` | Valide le sujet ; `--show` affiche les prompts tels qu'ils seront envoyés. |
| `manual subject delete SLUG [-y] [--with-output]` | Supprime le dossier `subjects/SLUG/` (sujet incomplet compris) après confirmation `[o/N]` ; `-y` supprime sans demander. L'identifiant est obligatoire, même s'il n'y a qu'un sujet. Le manuel déjà généré dans `output/SLUG/` est **conservé** sauf avec `--with-output` (incompatible avec l'option globale `--output`). |

Le mieux est de retoucher le sujet **avant** `init` : le plan est généré à partir du sujet. Après coup, `manual improve-toc` adapte le plan sans rien perdre.

### Le fichier `subject.yml`

| Champ | Rôle | Obligatoire |
|---|---|---|
| `titre` | Titre du sujet | oui |
| `langue` | Langue de rédaction | oui |
| `role` | Personnage de l'auteur (expertise, références) | oui |
| `objectif` | Ce que le manuel doit apporter | oui |
| `public` | Lecteurs visés | oui |
| `niveau` | Niveau atteint (ex. « débutant → expert ») | oui |
| `ton` | Ton de la rédaction | oui |
| `plan_directeur` | Progression attendue des grandes parties, séparées par des flèches | oui |
| `exclusions` | Liste des sujets à ne pas traiter | non |
| `instructions` | Consignes libres supplémentaires (sources, exemples attendus, style) | non |

Ces champs sont injectés dans le prompt système (`prompts/system_prompt.md`) et dans l'instruction de plan (`prompts/toc_instruction.md`). Un champ inconnu, manquant ou vide est refusé avec un message explicite.

### Critères de relecture

Trois niveaux s'additionnent :

1. **Communs à tous les sujets** : `requirements/requirements.yml` (définitions claires, exemples concrets, avantages et limites, cohérence avec le plan, marqueur de fin…).
2. **Propres au sujet** (`generic`) : `subjects/<sujet>/requirements.yml`, proposés par le modèle à la création du sujet ou ajoutés à la main.
3. **Propres à une partie** (`parties`) : la clé est le **titre exact** de la partie dans le plan généré. Comme les parties ne sont connues qu'après `init`, on les fait proposer une fois le plan validé :

```bash
manual --subject cybersecurite-dirigeants subject criteria   # 1 à 3 critères par partie pertinente
manual --subject cybersecurite-dirigeants write
```

Chaque critère a un `id` unique, une `description` et une `severity` (`bloquant` ou `recommande`). Les critères sont enregistrés dans `requirements.yml` du sujet ; l'ancienne version va dans `requirements.yml.bak`, et les commentaires du fichier ne sont pas conservés. Les parties déjà pourvues sont laissées telles quelles, sauf avec `--force`. Si le plan change de titres de parties, relancer la commande.

### Contrôle total (facultatif)

Dans le dossier du sujet, deux fichiers **remplacent entièrement** le gabarit générique correspondant :

- `system_prompt.md` : le prompt système ;
- `toc_instruction.md` : l'instruction de génération du plan.

Ils sont alors envoyés tels quels : c'est à vous de conserver le format de sortie (schéma JSON du plan, etc.).

## Guide : écrire et suivre le manuel

Flux de travail habituel :

1. Choisir ou créer le sujet : `manual subject list`, ou `manual subject new SLUG "descriptif"` puis `manual subject check SLUG --show`.
2. `manual init`, puis relire `output/<sujet>/00_toc.md`. Modifier le plan à la main (`toc.yml`), l'améliorer avec `manual improve-toc`, ou repartir de zéro avec `manual init --force` (tant qu'aucun chapitre n'est écrit).
3. Facultatif : `manual subject criteria` pour ajouter des critères de relecture par partie.
4. `manual write` ; en cas d'interruption ou d'échec, relancer la même commande : les sections terminées (`done`) sont conservées, les autres sont reprises.
5. `manual status` pour repérer les sections `failed`, puis `manual redo N` (refaire de zéro) ou `manual improve N` (améliorer l'existant) pour celles qui ne conviennent pas. `write`, `redo` et `improve` retournent `0` même si des sections échouent : dans un script, lire `manual status`.
6. Facultatif : `manual glossary` pour générer le glossaire, puis `manual publish N` pour préparer une publication LinkedIn.

Conseil : rédiger d'abord un chapitre seul (`manual write -s 1`) pour juger la qualité et ajuster sujet, critères ou modèles avant de lancer le manuel entier.

### Modifier le plan à la main

`output/<sujet>/toc.yml` est la source de vérité du plan : titres et descriptions uniquement, **aucun numéro à maintenir** (parties en chiffres romains, chapitres de 1 à N, sous-sections `chapitre.rang` sont déduits de la position). Un chapitre ajouté, retitré ou déplacé repart en attente ; modifier une description ne change pas le statut (utiliser `redo` ou `improve`). L'introduction et la conclusion s'y déclarent par les clés facultatives `introduction:` et `conclusion:`. Voir [`MANUAL.md`](MANUAL.md#6-le-plan--tocyml-introduction-et-conclusion).

### Suivi des appels LLM

Chaque appel (réussi ou non) est journalisé dans `output/<sujet>/traces/calls.jsonl`. `manual traces` propose une interface web locale pour les parcourir, ce qui aide à diagnostiquer les délais d'attente (timeouts) ou les lenteurs d'un modèle. Elle nécessite l'extra `web` (Flask). Les commandes `subject new` et `subject refine`, qui n'ont pas de répertoire de sortie, ne sont pas journalisées.

## Guide : améliorer le contenu et le plan

### Que faire quand le résultat ne convient pas ?

| Situation | Commande | Ce qui se passe |
|---|---|---|
| Un chapitre est raté ou hors sujet | `manual redo N` | Régénéré **depuis zéro**, l'existant est ignoré. |
| Un chapitre est correct mais à enrichir | `manual improve N [-i "consigne"]` | Le texte existant sert d'**amorce** ; l'ancienne version est conservée. |
| Le plan est à corriger, des chapitres sont déjà écrits | `manual improve-toc [-i "consigne"]` | Plan amélioré **en préservant** les chapitres rédigés ; version précédente archivée. |
| Le plan est à refaire, rien n'est écrit | `manual init --force` | Nouveau plan, avancement et mémoire réinitialisés. |
| Tous les chapitres sont trop faibles | `manual subject criteria` / `subject refine`, puis `redo` ou `improve` | Critères plus exigeants ou consignes changées. Un modèle plus fort pour `model_judge` et `model_rewriter` dans `params.yml` aide aussi. |

### Améliorer des sections déjà écrites

`manual improve` reprend le texte d'une section et l'utilise comme **amorce** d'une nouvelle génération, sur le même principe que l'écriture normale (rédaction, relecture par le juge, réécriture si besoin, mise à jour de la mémoire), mais avec un contenu enrichi.

```bash
manual improve 7                                    # consigne par défaut : « relis et améliore »
manual improve 7 -i "plus d'exemples chiffrés, intro plus courte"
manual improve 3 5-8 -f consigne.txt                # plusieurs sections, consigne dans un fichier
```

- **Sans consigne**, le modèle relit et améliore : corrections, manques comblés, exemples enrichis, plan du chapitre inchangé. La consigne par défaut se règle dans `prompts/improve_default_instruction.md`.
- **Le titre et les sous-sections du plan sont conservés** ; la mémoire du manuel est fournie au modèle pour rester cohérent avec les autres chapitres.
- **Rien n'est perdu** : la nouvelle version ne remplace l'ancienne que si elle passe la relecture. L'ancienne est alors gardée en `NN_titre.md.bak`. Sinon, l'original, son statut et la mémoire restent intacts, et la version refusée est écrite à côté dans `NN_titre.candidate.md` pour que vous puissiez la lire.
- Une section `failed` qui a du contenu peut aussi être améliorée ; une section sans contenu doit d'abord passer par `manual write`.
- Options : `--max-rewrite N` et `-w N`, comme pour `write`.

### Améliorer la table des matières

`manual improve-toc` fait relire et améliorer le plan **en partant de l'actuel**, sans repartir de zéro ni rien perdre :

```bash
manual improve-toc                                          # consigne par défaut : « relis et améliore »
manual improve-toc -i "ajoute un chapitre sur l'évaluation, fusionne les chapitres 4 et 5"
manual improve-toc -f consigne.txt
```

- **Les chapitres déjà rédigés (`done`) sont figés** : le modèle doit les conserver avec le même numéro, le même titre et les mêmes sous-sections (numéros et titres ; leur `description` peut être précisée ou ajoutée, sans renvoyer le chapitre en attente) ; sinon sa réponse est refusée et il est prié de corriger (trois essais, puis la commande s'arrête sans rien modifier). Le reste (chapitres non rédigés, parties) peut être réordonné, fusionné, scindé, ajouté ou supprimé, avec une numérotation consécutive de 1 à N.
- **L'avancement est préservé** : les chapitres inchangés gardent leur statut ; les chapitres nouveaux ou modifiés repassent en attente, à rédiger avec `manual write`.
- **Rien n'est supprimé** : les fichiers de chapitres et la mémoire ne sont jamais touchés (les fichiers que le nouveau plan n'utilise plus sont listés, laissés en place). La version précédente du plan est archivée dans `output/<sujet>/toc_history/<date-heure>/` (`manifest.json`, `toc.yml` et `00_toc.md`), à chaque exécution.
- **Critères par partie** : si une partie est renommée, les critères propres à l'ancien titre n'ont plus de correspondance ; la commande le signale (voir `manual subject criteria`).
- **Manifestes anciens** : un manifeste créé avant l'ajout des descriptions de sous-sections se relit sans migration (descriptions vides). `improve-toc` exige ensuite une description pour toutes les sous-sections, y compris celles des chapitres figés.
- Avant d'avoir rédigé quoi que ce soit, tout le plan est modifiable.

## Publication LinkedIn (optionnelle)

`manual publish N` prépare, pour un chapitre terminé, un paquet dans `output/<sujet>/publish/<chapitre>/` :

- `article.html` : le chapitre en HTML autonome, à ouvrir dans un navigateur puis à copier-coller dans l'éditeur d'article LinkedIn (qui ne comprend pas le Markdown brut mais conserve la mise en forme du HTML copié) ;
- `post.txt` : un brouillon de post, terminé par le jeton `{ARTICLE_URL}` à remplacer par le lien de l'article ;
- `cover.png` : une image de couverture (rôle `model_image`, désactivable avec `--no-image`).

**Rien n'est publié automatiquement** : la création de l'article et la publication du post restent manuelles.

## Fichiers produits

Dans le répertoire de sortie (`output/<sujet>/` par défaut) :

| Fichier | Contenu |
|---|---|
| `00_toc.md` | Vue lisible du plan (régénérée par `init`, `improve-toc` et `write`) : description du chapitre en italique sous son titre, description de chaque sous-section en italique sous son intitulé |
| `00_introduction.md`, `NN_conclusion.md` | Introduction et conclusion, si le plan en prévoit |
| `glossaire.md` | Le glossaire (`manual glossary`) |
| `NN_titre-du-chapitre.md` | Un fichier Markdown par chapitre |
| `NN_titre-du-chapitre.md.bak` | Version précédente d'un chapitre, après `improve` |
| `NN_titre-du-chapitre.candidate.md` | Version d'`improve` refusée par la relecture (l'original est intact) |
| `toc.yml` | Le plan, **source de vérité et fichier à éditer à la main** : parties, chapitres, sous-sections et descriptions, sans aucun numéro (parties en chiffres romains, chapitres 1..N et sous-sections `chapitre.rang` sont déduits de la position). Un chapitre ajouté ou dont le titre change repart en attente ; modifier une description ne change pas le statut (utilise `redo` ou `improve`) |
| `manifest.json` | Le suivi seul : le sujet et, par chapitre, `numero`, `titre`, `status`, `attempts`, `last_verdict`. Un ancien manifeste contenant le plan est relu tel quel puis migré à la prochaine sauvegarde |
| `memory.md` | Le résumé structuré transmis aux rédactions suivantes |
| `toc_history/<date-heure>/` | Anciennes versions du plan (`manifest.json`, `toc.yml`, `00_toc.md`), archivées par `improve-toc` |
| `traces/calls.jsonl` | Le journal de tous les appels LLM |
| `publish/<chapitre>/` | Les paquets de publication LinkedIn |

Dans `subjects/<sujet>/` : `subject.yml`, `requirements.yml`, éventuellement `system_prompt.md` et `toc_instruction.md`, et les sauvegardes `*.bak` créées par `subject refine` et `subject criteria`.

## Garanties et sécurités

- **Échec explicite, jamais de repli silencieux** : une configuration manquante, une variable d'environnement absente ou une erreur d'un fournisseur lève une erreur claire.
- **Configuration stricte** : une clé inconnue dans un modèle de `params.yml` (ex. `effort`) ou un `think` d'un mauvais type est refusé au démarrage, jamais ignoré.
- **Rien n'est écrit avant validation** : la réponse d'un modèle qui doit être structurée (sujet, critères, plan) est validée d'abord ; en cas d'échec, les fichiers existants restent intacts.
- **Sauvegardes systématiques** : `.bak` (sujet, critères, chapitres améliorés), `.candidate.md` (version refusée), `toc_history/` (anciens plans).
- **Le travail écrit est protégé** : `improve-toc` fige les chapitres déjà rédigés et ne touche jamais aux fichiers de chapitres ni à la mémoire ; `improve` ne remplace un chapitre que si la nouvelle version est acceptée.
- **Cohérence sujet / manuel** : le manifeste mémorise le sujet ; `write`, `improve` et `improve-toc` refusent de travailler sur un manuel généré pour un autre sujet.
- **Double contrôle d'un chapitre** : `done` exige l'accord du juge *et* le marqueur de fin ; de plus, un critère bloquant listé par le juge force la réécriture même s'il a répondu « accepter ».
- **Aucune publication automatique** : `manual publish` ne prépare que des fichiers à copier soi-même.
- **Erreurs lisibles** : toute erreur connue (configuration, fournisseur, validation, sujet) s'affiche `Erreur : …` sur la sortie d'erreur avec le code de sortie `1`, sans trace d'appels.
- **Secrets hors du dépôt** : les clés vivent dans `~/.env`, `params.yml` ne contient que des noms de variables.

## Personnaliser les prompts

Tout le texte envoyé aux modèles est dans `prompts/` (les prompts spécifiques à un sujet sont dans `subjects/`). Les gabarits utilisent la syntaxe `string.Template` (`$variable`, et non `{variable}`) : ne pas renommer ni supprimer un placeholder. Le test `tests/test_prompts_integrity.py` détecte ce genre d'erreur.

| Fichier | Rôle |
|---|---|
| `system_prompt.md`, `toc_instruction.md` | Gabarits remplis par `subject.yml` (prompt système, génération du plan) |
| `section_instruction.md` | Rédaction d'une section |
| `role_introduction.md`, `role_conclusion.md` | Consigne propre à l'introduction et à la conclusion |
| `glossary_extract_instruction.md`, `glossary_merge_instruction.md` | Extraction des termes d'un chapitre et consolidation du glossaire |
| `judge_instruction.md` | Relecture d'un chapitre |
| `rewrite_instruction.md` | Réécriture après un rejet |
| `improve_instruction.md`, `improve_default_instruction.md` | Amélioration d'un chapitre et consigne par défaut |
| `toc_improve_instruction.md`, `toc_improve_default_instruction.md` | Amélioration du plan et consigne par défaut |
| `author_system_prompt.md`, `subject_generate_instruction.md`, `subject_refine_instruction.md`, `partie_criteria_instruction.md` | Rédaction assistée des sujets et des critères |
| `subject_template.yml` | Squelette d'un nouveau sujet |
| `linkedin_post_instruction.md` | Brouillon du post LinkedIn |

## Architecture et structure du dépôt

```
manual_cli/            code source
  cli.py               commandes et arguments
  subjects.py          sujets : chargement, validation, rendu des prompts, critères
  subject_author.py    rédaction assistée : création, retouche, critères par partie
  generator.py         plan, rédaction, relecture, amélioration, mémoire
  providers.py         clients Ollama Cloud / OpenAI (reprises, traces)
  config.py            params.yml et ~/.env, relus à chaque appel
  state.py, memory.py  plan (`toc.yml`), suivi (`manifest.json`) et résumé structuré
  glossary.py          glossaire : extraction par chapitre et consolidation
  schemas.py           schémas du plan (introduction, parties, chapitres, sous-sections, conclusion) et du verdict du juge
  parsing.py           extraction et validation du JSON des modèles (nouvelles tentatives)
  patterns.py          lecture des sélections de sections (`-s 1 3 5-8`)
  requirements_loader.py  lecture et rendu des critères de relecture
  publish.py           paquet de publication LinkedIn
  tracing.py, web/     journal des appels et interface de consultation
  mcp_affinity/        script annexe indépendant (liste les outils d'un serveur MCP local), non utilisé par `manual`
prompts/               gabarits de prompts communs à tous les sujets
examples/              exemple guidé pas à pas (manuel de Prompt Engineering)
subjects/              un dossier par sujet de manuel (subject.yml, critères propres) ; non versionné, créé par `manual subject new`
requirements/          critères de qualité communs utilisés par le juge
assets/                image de prévisualisation sociale (1280x640)
tests/                 suite de tests
params.example.yml     modèle de configuration à copier en params.yml
pyproject.toml         packaging et configuration des tests
```

## Tests

```bash
pip install -e ".[test,web]"
python -m pytest                 # suite complète, seuil de couverture : 90 %, LLM simulés (aucun appel réseau)
python -m pytest -k nom_du_test -q --no-cov
```

Le projet suit un développement piloté par les tests (RED → GREEN → REFACTOR). La suite comprend un parcours complet sur un sujet autre que Prompt Engineering avec un modèle simulé (`tests/test_multi_subject_flow.py`).

## Limites connues

- **Modèles texte** : uniquement Ollama Cloud ; OpenAI n'est utilisé que pour l'image de couverture.
- **Numérotation figée** : avec `improve-toc`, les chapitres déjà rédigés gardent leur numéro ; on ne peut pas en insérer un nouveau *entre* deux chapitres écrits (les nouveaux chapitres se placent parmi les numéros non figés).
- **Critères par partie fragiles** : ils sont indexés sur le titre exact des parties générées ; si le plan est régénéré avec d'autres titres, relancer `manual subject criteria`.
- **Mémoire et `improve`** : le résumé cumulé mentionne déjà la version actuelle d'un chapitre avant son amélioration ; des redites sur ce chapitre y sont possibles.
- **Redites** : réduites par le plan de l'ouvrage et la mémoire structurée, pas éliminées ; un digest ancien n'a pas les nouvelles rubriques, qui se remplissent au fil des sections acceptées.
- **Introduction et conclusion** : `improve-toc` ne les fige pas (modifiées, elles repartent en attente) ; la conclusion change de numéro quand le nombre de chapitres change.
- **Glossaire** : régénéré en entier, uniquement à partir des chapitres terminés.
- **Commentaires YAML** : `subject refine` et `subject criteria` réécrivent leur fichier, les commentaires y sont perdus (l'ancienne version reste dans le `.bak`). `toc.yml` n'est réécrit que si le plan change réellement.
- **Publication LinkedIn** : l'API de LinkedIn ne permet pas de créer des articles ; la publication reste manuelle.
- **Durée** : plusieurs heures pour un manuel complet avec un modèle à longues chaînes de raisonnement.

## Remerciements

- **[OpenCode](https://opencode.ai)** : a servi à prototyper l'outil.
- **[Ollama](https://ollama.com)** : fournit les modèles de langage utilisés pour tous les rôles texte.
- **[Gemini](https://gemini.google.com)** (Google) : a servi à restructurer le prompt d'origine, dont sont issus tous les autres prompts.

## Licence et propriété

© 2026 Damien Raczy | (+687) 78 20 52 | damien@iod.nc — tous droits réservés, sauf les autorisations ci-dessous.

Ce logiciel est la propriété de son auteur. Vous pouvez l'utiliser, le copier et l'adapter, **à deux conditions** :

1. **Attribution.** L'auteur, Damien Raczy, doit toujours être cité, dans le code adapté comme dans toute œuvre qui en dérive ou qui l'utilise de façon significative.
2. **Pas d'usage commercial.** Aucun usage lié à un gain financier n'est autorisé : pas de vente, pas de service payant, pas d'intégration à une offre commerciale, ni directement, ni indirectement.

Toute autre utilisation nécessite l'accord écrit préalable de l'auteur.

Ces conditions correspondent à celles de la licence [Creative Commons Attribution – Pas d'Utilisation Commerciale 4.0 (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/deed.fr), dont le texte complet figure dans le fichier [`LICENSE`](LICENSE).

Le logiciel est fourni « tel quel », sans garantie d'aucune sorte. Les textes générés par les modèles de langage doivent être relus et vérifiés avant toute diffusion ; l'utilisateur reste responsable de ce qu'il publie et des coûts d'utilisation des API tierces.
