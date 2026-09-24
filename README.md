# ai_manual

`ai_manual` est un outil en ligne de commande (`manual`) qui **rédige de bout en bout un manuel de référence complet** en orchestrant plusieurs appels à des modèles de langage (LLM). La version fournie produit un manuel de *Prompt Engineering* en français, du niveau débutant au niveau expert. Changer le sujet consiste à modifier les prompts.

## Sommaire

- [Ce que fait le programme](#ce-que-fait-le-programme)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Fichiers produits](#fichiers-produits)
- [Adapter le manuel à un autre sujet](#adapter-le-manuel-à-un-autre-sujet)
- [Publication LinkedIn (optionnelle)](#publication-linkedin-optionnelle)
- [Tests](#tests)
- [Structure du dépôt](#structure-du-dépôt)
- [Licence et propriété](#licence-et-propriété)

## Ce que fait le programme

1. **Plan.** Un premier LLM propose une table des matières complète (parties, chapitres, sous-sections), enregistrée dans `00_toc.md` et dans un fichier d'état `manifest.json`.
2. **Rédaction.** Chaque chapitre est écrit un par un, en suivant strictement le plan. Plusieurs chapitres peuvent être rédigés en parallèle.
3. **Relecture automatique.** Un second LLM (le « juge ») évalue chaque chapitre selon des critères de qualité définis dans `requirements/requirements.yml` (définitions claires, exemples concrets, avantages et limites, cohérence avec le plan, etc.). Si un critère bloquant n'est pas rempli, un troisième rôle (le « réécrivain ») corrige le chapitre, qui est rejugé, dans la limite de `--max-rewrite` cycles.
4. **Mémoire.** Après chaque chapitre accepté, un résumé cumulé de ce qui a déjà été couvert (`memory.md`) est transmis aux rédactions suivantes, pour éviter les contradictions et les redites.
5. **Reprise.** L'avancement est sauvegardé chapitre par chapitre : on peut interrompre, relancer, cibler certains chapitres ou en refaire un seul sans tout recommencer.

Un chapitre n'est marqué `done` que si le juge l'accepte **et** que son marqueur de fin est présent dans le texte.

> Compter plusieurs heures pour un manuel complet avec un modèle qui raisonne longuement.

## Prérequis

- Python **3.10 ou plus récent**
- Un accès à un service **Ollama Cloud** (URL et clé API) pour tous les rôles texte
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

L'installation en mode éditable (`-e`) est nécessaire : le programme lit les dossiers `prompts/` et `requirements/` du dépôt à l'exécution. Elle crée la commande `manual` dans le venv ; sans activer le venv, on peut aussi lancer `.venv/bin/python -m manual_cli.cli <commande>`.

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
| `model_write` | rédige la table des matières et les chapitres | `ollama` |
| `model_judge` | relit et valide chaque chapitre | `ollama` |
| `model_think` | met à jour la mémoire inter-chapitres | `ollama` |
| `model_rewriter` | réécrit un chapitre rejeté | `ollama` |
| `model_image` | image de couverture (optionnel) | `openai` |

Seul le bloc nommé exactement `llm_config` est lu. Les autres blocs (`FASTllm_config`, `xllm_config`) sont des préréglages : pour en activer un, renommer les blocs (l'ancien `llm_config` en `autrellm_config`, le préréglage en `llm_config`).

`params.yml` ne contient aucun secret mais reste propre à chaque installation ; il est exclu du dépôt (voir `.gitignore`).

## Utilisation

Toutes les commandes acceptent `--output DIR` avant la sous-commande pour choisir le répertoire de sortie (défaut : `output/manual/` dans le dépôt).

```bash
manual init                      # 1. génère la table des matières
manual write                     # 2. rédige toutes les sections en attente
manual status                    # 3. affiche l'avancement
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

Flux de travail habituel :

1. `manual init`, puis relire `output/manual/00_toc.md` ; relancer `manual init --force` tant que le plan ne convient pas.
2. `manual write` ; en cas d'interruption, relancer la même commande : les sections terminées sont conservées.
3. `manual status` pour repérer les sections « à revoir », puis `manual redo N` pour celles qui ne conviennent pas.

### Suivi des appels LLM

Chaque appel (réussi ou non) est journalisé dans `output/manual/traces/calls.jsonl`. `manual traces` propose une interface web locale pour les parcourir, ce qui aide à diagnostiquer les délais d'attente (timeouts) ou les lenteurs d'un modèle. Elle nécessite l'extra `web` (Flask).

## Fichiers produits

Dans le répertoire de sortie (`output/manual/` par défaut) :

| Fichier | Contenu |
|---|---|
| `00_toc.md` | La table des matières générée |
| `NN_titre-du-chapitre.md` | Un fichier Markdown par chapitre |
| `manifest.json` | L'état de chaque section (statut, nombre de tentatives) |
| `memory.md` | Le résumé cumulé transmis aux rédactions suivantes |
| `traces/calls.jsonl` | Le journal de tous les appels LLM |
| `publish/<chapitre>/` | Les paquets de publication LinkedIn |

## Adapter le manuel à un autre sujet

Tout le texte envoyé aux modèles est dans `prompts/` ; le sujet, le niveau, le public et le ton sont définis dans `prompts/system_prompt.md`.

| Fichier | Rôle |
|---|---|
| `system_prompt.md` | Identité de l'auteur, sujet, public, exigences de contenu |
| `toc_instruction.md` | Consigne de génération de la table des matières (format JSON strict) |
| `section_instruction.md` | Consigne de rédaction d'un chapitre |
| `judge_instruction.md` | Consigne de relecture |
| `rewrite_instruction.md` | Consigne de réécriture |
| `linkedin_post_instruction.md` | Consigne du brouillon de post LinkedIn |

Les prompts utilisent la syntaxe `string.Template` (`$variable`, et non `{variable}`) : ne pas renommer ni supprimer un placeholder. Le test `tests/test_prompts_integrity.py` détecte ce genre d'erreur.

Les critères de qualité (génériques et par partie) se règlent dans `requirements/requirements.yml` : chaque critère est `bloquant` (force une réécriture) ou `recommande` (signalé sans bloquer).

## Publication LinkedIn (optionnelle)

`manual publish N` prépare, pour un chapitre terminé, un paquet dans `output/manual/publish/<chapitre>/` :

- `article.html` : le chapitre en HTML autonome, à ouvrir dans un navigateur puis à copier-coller dans l'éditeur d'article LinkedIn (qui ne comprend pas le Markdown brut mais conserve la mise en forme du HTML copié) ;
- `post.txt` : un brouillon de post, terminé par le jeton `{ARTICLE_URL}` à remplacer par le lien de l'article ;
- `cover.png` : une image de couverture (rôle `model_image`, désactivable avec `--no-image`).

**Rien n'est publié automatiquement** : la création de l'article et la publication du post restent manuelles.

## Tests

```bash
pip install -e ".[test,web]"
python -m pytest                 # suite complète, seuil de couverture : 90 %
python -m pytest -k nom_du_test -q --no-cov
```

Le projet suit un développement piloté par les tests (RED → GREEN → REFACTOR) et une gestion d'erreurs explicite : toute configuration manquante ou erreur de fournisseur lève une erreur claire, sans repli silencieux.

## Structure du dépôt

```
manual_cli/            code source (CLI, génération, fournisseurs, traces, interface web)
prompts/               prompts envoyés aux modèles
requirements/          critères de qualité utilisés par le juge
tests/                 suite de tests
params.example.yml     modèle de configuration à copier en params.yml
pyproject.toml         packaging et configuration des tests
```

## Licence et propriété

© 2026 Damien Raczy | (+687) 78 20 52 | damien@iod.nc — tous droits réservés, sauf les autorisations ci-dessous.

Ce logiciel est la propriété de son auteur. Vous pouvez l'utiliser, le copier et l'adapter, **à deux conditions** :

1. **Attribution.** L'auteur, Damien Raczy, doit toujours être cité, dans le code adapté comme dans toute œuvre qui en dérive ou qui l'utilise de façon significative.
2. **Pas d'usage commercial.** Aucun usage lié à un gain financier n'est autorisé : pas de vente, pas de service payant, pas d'intégration à une offre commerciale, ni directement, ni indirectement.

Toute autre utilisation nécessite l'accord écrit préalable de l'auteur.

Ces conditions correspondent à celles de la licence [Creative Commons Attribution – Pas d'Utilisation Commerciale 4.0 (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/deed.fr), dont le texte complet figure dans le fichier [`LICENCE`](LICENCE).

Le logiciel est fourni « tel quel », sans garantie d'aucune sorte. Les textes générés par les modèles de langage doivent être relus et vérifiés avant toute diffusion ; l'utilisateur reste responsable de ce qu'il publie et des coûts d'utilisation des API tierces.
