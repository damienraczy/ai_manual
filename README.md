# ai_manual

<img src="assets/social-preview.jpg" alt="ai_manual : un robot présente « The Basics of Prompt Engineering » sur un tableau" width="800">

`ai_manual` est un outil en ligne de commande (`manual`) qui **rédige de bout en bout un manuel de référence complet** en orchestrant plusieurs appels à des modèles de langage (LLM). Il fonctionne **sujet par sujet** : le dépôt fournit un sujet complet (un manuel de *Prompt Engineering* en français, du niveau débutant au niveau expert), et un nouveau sujet se crée en une commande à partir d'un court descriptif, rédigé par le modèle puis retouchable à volonté.

## Sommaire

- [Ce que fait le programme](#ce-que-fait-le-programme)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Fichiers produits](#fichiers-produits)
- [Sujets : écrire sur un autre thème](#sujets--écrire-sur-un-autre-thème)
- [Publication LinkedIn (optionnelle)](#publication-linkedin-optionnelle)
- [Tests](#tests)
- [Structure du dépôt](#structure-du-dépôt)
- [Remerciements](#remerciements)
- [Licence et propriété](#licence-et-propriété)

## Ce que fait le programme

1. **Cadrage du sujet.** Un sujet décrit de quoi parle le manuel : rôle de l'auteur, public, niveau, ton, progression, exclusions, critères propres. Il peut être rédigé par le LLM à partir d'un descriptif, puis retouché (voir [Sujets](#sujets--écrire-sur-un-autre-thème)).
2. **Plan.** Un LLM propose une table des matières complète (parties, chapitres, sous-sections), enregistrée dans `00_toc.md` et dans un fichier d'état `manifest.json`.
3. **Rédaction.** Chaque chapitre est écrit un par un, en suivant strictement le plan. Plusieurs chapitres peuvent être rédigés en parallèle.
4. **Relecture automatique.** Un second LLM (le « juge ») évalue chaque chapitre selon des critères de qualité communs (`requirements/requirements.yml`) et propres au sujet (définitions claires, exemples concrets, avantages et limites, cohérence avec le plan, etc.). Si un critère bloquant n'est pas rempli, un troisième rôle (le « réécrivain ») corrige le chapitre, qui est rejugé, dans la limite de `--max-rewrite` cycles.
5. **Mémoire.** Après chaque chapitre accepté, un résumé cumulé de ce qui a déjà été couvert (`memory.md`) est transmis aux rédactions suivantes, pour éviter les contradictions et les redites.
6. **Reprise.** L'avancement est sauvegardé chapitre par chapitre : on peut interrompre, relancer, cibler certains chapitres ou en refaire un seul sans tout recommencer.

Un chapitre n'est marqué `done` que si le juge l'accepte **et** que son marqueur de fin est présent dans le texte.

> Compter plusieurs heures pour un manuel complet avec un modèle qui raisonne longuement.

## Prérequis

- Python **3.10 ou plus récent**
- Un accès à un service **Ollama Cloud** (URL et clé API) pour tous les rôles texte (rédaction des chapitres, relecture, rédaction des sujets)
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

- **`models:`** : le catalogue des modèles disponibles. Pour chacun : `provider`, `name`, `url` et `api_key` (les *noms* des variables de `~/.env`, pas leurs valeurs) et `timeout` en secondes.
- **`llm_config:`** : l'affectation d'un modèle à chaque rôle.

| Rôle | Fonction | Fournisseur autorisé |
|---|---|---|
| `model_write` | rédige les sujets, la table des matières et les chapitres | `ollama` |
| `model_judge` | relit et valide chaque chapitre | `ollama` |
| `model_think` | met à jour la mémoire inter-chapitres | `ollama` |
| `model_rewriter` | réécrit un chapitre rejeté | `ollama` |
| `model_image` | image de couverture (optionnel) | `openai` |

Seul le bloc nommé exactement `llm_config` est lu. Les autres blocs (`FASTllm_config`, `xllm_config`) sont des préréglages : pour en activer un, renommer les blocs (l'ancien `llm_config` en `autrellm_config`, le préréglage en `llm_config`).

`params.yml` ne contient aucun secret mais reste propre à chaque installation ; il est exclu du dépôt (voir `.gitignore`).

## Utilisation

Deux options se placent avant la sous-commande :

- `--subject SUJET` choisit le sujet du manuel (un dossier de `subjects/`, voir [Sujets](#sujets--écrire-sur-un-autre-thème)). Facultatif tant qu'il n'existe qu'un seul sujet ; **dès qu'il y en a plusieurs, il devient obligatoire** pour `init`, `write`, `redo`, `status`, `publish` et `traces` (sauf si `--output` est donné pour `status`, `publish` et `traces`).
- `--output DIR` choisit le répertoire de sortie (défaut : `output/<sujet>/` dans le dépôt).

```bash
manual --subject prompt-engineering init   # 1. génère la table des matières
manual --subject prompt-engineering write  # 2. rédige toutes les sections en attente
manual --subject prompt-engineering status # 3. affiche l'avancement
```

| Commande | Effet |
|---|---|
| `manual init [--force]` | Génère la table des matières. Refuse d'écraser une TOC existante sans `--force`. |
| `manual write` | Rédige toutes les sections en attente (4 workers en parallèle par défaut). |
| `manual write -s 1 3 5-8` | Rédige seulement les sections 1, 3 et 5 à 8. |
| `manual write -w 8` | Utilise 8 workers en parallèle. |
| `manual write --max-rewrite 3` | Autorise jusqu'à 3 cycles de réécriture après un rejet du juge (défaut : 2). |
| `manual status` | Affiche l'état de chaque section (`done`, en attente, à revoir) et le total. |
| `manual redo 7 [--max-rewrite N]` | Régénère la section 7 depuis zéro. |
| `manual publish 1 [--no-image]` | Prépare le paquet de publication LinkedIn de la section 1 (voir plus bas). |
| `manual traces [--host H] [--port P]` | Lance l'interface web (défaut : `127.0.0.1:8787`) sur le journal des appels LLM. |
| `manual subject list` | Liste les sujets disponibles (un sujet incomplet est signalé `INVALIDE`). |
| `manual subject new SLUG ["descriptif"]` | Crée un sujet : rédigé par le modèle si un descriptif est donné, sinon squelette à remplir. |
| `manual subject refine SLUG "consigne"` | Retouche un sujet selon une consigne en langage naturel. |
| `manual subject edit [SLUG]` | Ouvre `subject.yml` dans l'éditeur puis le valide. |
| `manual subject criteria [SLUG] [--force]` | Propose des critères de relecture par partie de la table des matières générée. |
| `manual subject check [SLUG] [--show]` | Valide un sujet ; `--show` affiche les prompts tels qu'ils seront envoyés. |

Flux de travail habituel :

1. Choisir ou créer le sujet : `manual subject list`, ou `manual subject new SLUG "descriptif"` puis `manual subject check SLUG --show`.
2. `manual init`, puis relire `output/<sujet>/00_toc.md` ; relancer `manual init --force` tant que le plan ne convient pas.
3. Facultatif : `manual subject criteria` pour ajouter des critères de relecture par partie.
4. `manual write` ; en cas d'interruption, relancer la même commande : les sections terminées sont conservées.
5. `manual status` pour repérer les sections « à revoir », puis `manual redo N` pour celles qui ne conviennent pas.
6. Facultatif : `manual publish N` pour préparer une publication LinkedIn.

### Suivi des appels LLM

Chaque appel (réussi ou non) est journalisé dans `output/<sujet>/traces/calls.jsonl`. `manual traces` propose une interface web locale pour les parcourir, ce qui aide à diagnostiquer les délais d'attente (timeouts) ou les lenteurs d'un modèle. Elle nécessite l'extra `web` (Flask).

## Fichiers produits

Dans le répertoire de sortie (`output/<sujet>/` par défaut) :

| Fichier | Contenu |
|---|---|
| `00_toc.md` | La table des matières générée |
| `NN_titre-du-chapitre.md` | Un fichier Markdown par chapitre |
| `manifest.json` | L'état de chaque section (statut, nombre de tentatives) et le sujet utilisé |
| `memory.md` | Le résumé cumulé transmis aux rédactions suivantes |
| `traces/calls.jsonl` | Le journal de tous les appels LLM |
| `publish/<chapitre>/` | Les paquets de publication LinkedIn |

## Sujets : écrire sur un autre thème

Un **sujet** est un dossier `subjects/<identifiant>/` qui décrit de quoi parle le manuel. Le dépôt fournit `subjects/prompt-engineering/`. Les règles de forme communes à tous les sujets (format JSON du plan, marqueur de fin de section, consignes de relecture) restent dans `prompts/` et ne se touchent pas.

### Créer un sujet

**Rédigé par le modèle** (le plus rapide) : donner l'identifiant et un court descriptif.

```bash
manual subject new cybersecurite-dirigeants "Manuel de cybersécurité pour dirigeants non techniques, du débutant à l'opérationnel"
manual subject check cybersecurite-dirigeants --show   # relire le cadrage et les prompts obtenus
manual --subject cybersecurite-dirigeants init         # générer la table des matières
manual --subject cybersecurite-dirigeants write
```

Le modèle (`model_write`) propose tous les champs de `subject.yml` et quelques critères de relecture propres au sujet. Rien n'est écrit tant que sa réponse n'est pas valide.

**À la main** : sans descriptif, `manual subject new <identifiant>` crée un squelette dont les champs valent « À COMPLÉTER » (refusés tant qu'ils restent tels quels), à remplir avec `manual subject edit <identifiant>`.

### Retoucher un sujet

| Commande | Effet |
|---|---|
| `manual subject refine SLUG "consigne"` | Le modèle applique la consigne (ex. « ton plus décontracté, sans juridique ») et affiche les champs modifiés. L'ancienne version est conservée dans `subject.yml.bak`. |
| `manual subject edit [SLUG]` | Ouvre `subject.yml` dans `$VISUAL` / `$EDITOR`, puis le valide à la fermeture. |
| `manual subject check [SLUG] [--show]` | Valide le sujet ; `--show` affiche les prompts tels qu'ils seront envoyés. |

Le mieux est de faire `refine` ou `edit` **avant** `init` : le plan est généré une fois pour toutes à partir du sujet. Pour un nouveau plan après modification : `manual init --force`.

### Critères de relecture par partie

Les parties d'un manuel ne sont connues qu'après `init`. Une fois le plan validé :

```bash
manual --subject cybersecurite-dirigeants subject criteria   # le modèle propose 1 à 3 critères par partie pertinente
manual --subject cybersecurite-dirigeants write
```

Les critères sont enregistrés dans `requirements.yml` du sujet (l'ancienne version va dans `requirements.yml.bak`, et les commentaires du fichier ne sont pas conservés). Les parties déjà pourvues sont laissées telles quelles, sauf avec `--force`. Si le plan est régénéré avec d'autres titres de parties, relancer la commande.

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

Ces champs sont injectés dans le prompt système (`prompts/system_prompt.md`) et dans l'instruction de plan (`prompts/toc_instruction.md`). Un champ inconnu ou manquant est refusé avec un message explicite.

### Aller plus loin (facultatif)

Dans le dossier du sujet :

- `system_prompt.md` et/ou `toc_instruction.md` : remplacent entièrement le gabarit générique correspondant, pour un contrôle total. Ils sont alors envoyés tels quels : c'est à vous de conserver le format de sortie (schéma JSON du plan, etc.).
- `requirements.yml` : ajoute des critères de relecture à ceux, communs, de `requirements/requirements.yml`. Deux blocs possibles : `generic` (toutes les sections) et `parties` (par grande partie, la clé étant le titre exact de la partie dans la table des matières générée). Chaque critère a un `id` unique, une `description` et une `severity` : `bloquant` (force une réécriture) ou `recommande` (signalé sans bloquer).

Les autres prompts (`section_instruction.md`, `judge_instruction.md`, `rewrite_instruction.md`, `linkedin_post_instruction.md`) sont communs à tous les sujets. Ils utilisent la syntaxe `string.Template` (`$variable`, et non `{variable}`) : ne pas renommer ni supprimer un placeholder. Le test `tests/test_prompts_integrity.py` détecte ce genre d'erreur.

## Publication LinkedIn (optionnelle)

`manual publish N` prépare, pour un chapitre terminé, un paquet dans `output/<sujet>/publish/<chapitre>/` :

- `article.html` : le chapitre en HTML autonome, à ouvrir dans un navigateur puis à copier-coller dans l'éditeur d'article LinkedIn (qui ne comprend pas le Markdown brut mais conserve la mise en forme du HTML copié) ;
- `post.txt` : un brouillon de post, terminé par le jeton `{ARTICLE_URL}` à remplacer par le lien de l'article ;
- `cover.png` : une image de couverture (rôle `model_image`, désactivable avec `--no-image`).

**Rien n'est publié automatiquement** : la création de l'article et la publication du post restent manuelles.

## Tests

```bash
pip install -e ".[test,web]"
python -m pytest                 # suite complète, seuil de couverture : 90 %, LLM simulés (aucun appel réseau)
python -m pytest -k nom_du_test -q --no-cov
```

Le projet suit un développement piloté par les tests (RED → GREEN → REFACTOR) et une gestion d'erreurs explicite : toute configuration manquante ou erreur de fournisseur lève une erreur claire, sans repli silencieux.

## Structure du dépôt

```
manual_cli/            code source (CLI, sujets, génération, fournisseurs, traces, interface web)
prompts/               gabarits de prompts communs à tous les sujets (dont ceux de la rédaction assistée)
subjects/              un dossier par sujet de manuel (subject.yml, critères propres)
assets/                image de prévisualisation sociale (1280x640)
requirements/          critères de qualité communs utilisés par le juge
tests/                 suite de tests
params.example.yml     modèle de configuration à copier en params.yml
pyproject.toml         packaging et configuration des tests
```

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
