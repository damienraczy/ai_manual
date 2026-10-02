# MANUAL.md — Documentation complète de `ai_manual`

Ce document est la référence exhaustive de `ai_manual` (commande `manual`). Le [`README.md`](README.md) en donne la présentation et le démarrage rapide ; [`CLAUDE.md`](CLAUDE.md) et [`PRINCIPES.md`](PRINCIPES.md) décrivent les règles de développement.

## Table des matières

1. [Présentation](#1-présentation)
2. [Concepts et vocabulaire](#2-concepts-et-vocabulaire)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Les sujets](#5-les-sujets)
6. [Le plan : `toc.yml`, introduction et conclusion](#6-le-plan--tocyml-introduction-et-conclusion)
7. [Le pipeline de rédaction](#7-le-pipeline-de-rédaction)
8. [La mémoire et la vue d'ensemble de l'ouvrage](#8-la-mémoire-et-la-vue-densemble-de-louvrage)
9. [Référence des commandes](#9-référence-des-commandes)
10. [Flux de travail](#10-flux-de-travail)
11. [Améliorer le contenu et le plan](#11-améliorer-le-contenu-et-le-plan)
12. [Le glossaire](#12-le-glossaire)
12.bis. [Documents de référence](#12-bis-documents-de-référence)
13. [Publication LinkedIn](#13-publication-linkedin)
14. [Fichiers produits](#14-fichiers-produits)
15. [Traçabilité et diagnostic](#15-traçabilité-et-diagnostic)
16. [Garanties et gestion des erreurs](#16-garanties-et-gestion-des-erreurs)
17. [Personnaliser les prompts](#17-personnaliser-les-prompts)
18. [Architecture du code](#18-architecture-du-code)
19. [Développement et tests](#19-développement-et-tests)
20. [Dépannage](#20-dépannage)
21. [Limites connues](#21-limites-connues)
22. [Licence](#22-licence)

---

## 1. Présentation

`ai_manual` rédige un **manuel de référence complet, sur le sujet de votre choix**, en orchestrant plusieurs appels à des modèles de langage (LLM) :

1. un modèle propose une **table des matières** (le *plan*) ;
2. chaque **section** est rédigée en suivant strictement ce plan ;
3. un second modèle (le *juge*) relit chaque section selon des **critères** ; en cas de défaut bloquant, un *réécrivain* corrige, dans la limite d'un nombre de cycles ;
4. après chaque section acceptée, un **résumé cumulé** (la *mémoire*) est mis à jour, pour la cohérence d'ensemble et pour éviter les répétitions.

Un exemple guidé pas à pas (manuel de Prompt Engineering) est fourni dans [`examples/prompt-engineering/`](examples/prompt-engineering/README.md). Le dépôt ne fournit aucun sujet prêt dans `subjects/` : le dossier `subjects/` n'est pas versionné (il est ignoré par `.gitignore`) et chaque installation crée les siens. Un sujet se crée en une commande à partir d'un descriptif.

Une partie séparée et optionnelle (`manual publish`) prépare, sans rien publier, des paquets de publication LinkedIn à partir de sections terminées.

```
sujet ─► plan ─► rédaction ─► relecture (juge) ─► accepté ? ─oui─► mémoire ─► section suivante
(cadrage) (TOC)      ▲                                │
                     └──── réécriture ◄──── non ──────┘   (au plus --max-rewrite fois)
```

---

## 2. Concepts et vocabulaire

| Terme | Sens |
|---|---|
| **Sujet** | Le cadrage d'un manuel (thème, public, niveau, ton, progression, exclusions, critères). Un dossier `subjects/<slug>/`. |
| **Plan / TOC** | Introduction, parties, chapitres, sous-sections et conclusion. Source de vérité : `toc.yml`. |
| **Partie** | Regroupement de chapitres (numérotée en chiffres romains). Son titre sert de clé aux critères propres à une partie. |
| **Chapitre** | Unité de rédaction du corps du manuel, numéroté de 1 à N sur tout le manuel. |
| **Section** | Terme générique pour tout ce qui est rédigé dans un fichier : un chapitre, l'introduction (numéro 0) ou la conclusion (numéro N+1). |
| **Statut** | `pending` (à écrire), `done` (accepté par le juge **et** marqueur de fin présent), `failed` (refusé ou marqueur absent). |
| **Rôles LLM** | `model_write` (rédacteur), `model_judge` (juge), `model_rewriter` (réécrivain), `model_think` (mémoire), `model_image` (couverture, optionnel). |
| **Critère** | Exigence de qualité appliquée par le juge. Sévérité `bloquant` (force une réécriture) ou `recommande` (signalé, non bloquant). |
| **Mémoire / digest** | Résumé structuré de ce qui a déjà été écrit (`memory.md`). |
| **Plan de l'ouvrage** | Vue d'ensemble du plan complet, transmise au rédacteur avec le chapitre en cours signalé. |
| **Marqueur de fin** | Ligne finale obligatoire d'une section : `--- Fin de la section N — Dis « continue » pour la suivante ---`. |
| **Manifeste** | `manifest.json` : le suivi d'avancement (statut, tentatives, verdict). |

---

## 3. Installation

### Prérequis

- Python **3.10 ou plus récent**.
- Un accès à **Ollama Cloud** (URL et clé API) pour tous les rôles texte.
- *Optionnel* : une clé **OpenAI** pour l'image de couverture (`manual publish`).

### Procédure

```bash
git clone https://github.com/damienraczy/ai_manual.git ai_manual
cd ai_manual
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"          # programme + interface web des traces
# pip install -e ".[test,web]"   # avec les outils de test
```

L'installation **éditable** (`-e`) est nécessaire : le programme lit à l'exécution les dossiers `prompts/`, `requirements/` et `subjects/` du dépôt. Elle crée la commande `manual`. Sans activer le venv : `.venv/bin/python -m manual_cli.cli <commande>`.

Dépendances : `pyyaml`, `python-dotenv`, `requests`, `pydantic`, `markdown`, `mcp` ; extra `web` : `flask` ; extra `test` : `pytest`, `pytest-cov`.

---

## 4. Configuration

Deux fichiers, **relus à chaque appel LLM** : une modification (timeout, modèle) prend effet immédiatement, sans redémarrage.

### 4.1 Secrets : `~/.env`

Dans le répertoire personnel de l'utilisateur (pas dans le dépôt) :

```dotenv
OLLAMA_CLOUD_URL=https://...
OLLAMA_API_KEY=...
# Optionnel, uniquement pour `manual publish` :
OPENAI_URL=https://api.openai.com/v1
OPENAI_API_KEY=...
```

- `OLLAMA_CLOUD_URL` peut finir par `/api` ou non : il n'est pas doublé.
- `OPENAI_URL` peut pointer sur `/v1` ou plus loin (`/v1/responses`) : il est tronqué après `/v1`.
- `chmod 600 ~/.env` ; ne jamais le versionner.
- Une variable manquante lève `Variables d'environnement manquantes dans ~/.env : …` ; aucun repli silencieux.

### 4.2 Modèles : `params.yml`

```bash
cp params.example.yml params.yml     # fichier propre à chaque installation, exclu du dépôt
```

Deux sections :

**`models:`** — catalogue. Pour chaque modèle (clé libre) :

| Clé | Rôle |
|---|---|
| `provider` | `ollama` (rôles texte) ou `openai` (`model_image`) |
| `name` | Nom du modèle chez le fournisseur |
| `url` | **Nom** de la variable de `~/.env` contenant l'URL |
| `api_key` | **Nom** de la variable de `~/.env` contenant la clé |
| `timeout` | Délai en secondes (prioritaire sur `llm_config.timeout`) |
| `think` | Facultatif, modèles Ollama : `true`, `false` ou un niveau propre au modèle (ex. GLM 5.3 : `low`/`high`/`max`), transmis tel quel au champ `think` de l'API |

Toute autre clé dans un modèle est **refusée au démarrage** (jamais ignorée).

**`llm_config:`** — affectation des rôles :

```yaml
llm_config:
  timeout: 120              # repli si le modèle n'en définit pas
  llm:
    model_write: glm-5.3-flash
    model_judge: glm-5.3-flash
    model_think: glm-5.3-flash
    model_rewriter: glm-5.3-flash
    model_image: gpt-image-1   # optionnel
```

| Rôle | Fonction | Fournisseur |
|---|---|---|
| `model_write` | sujets, plan (et son amélioration), chapitres, glossaire, brouillon de post | `ollama` |
| `model_judge` | relecture de chaque section | `ollama` |
| `model_think` | mise à jour de la mémoire, analyse et affectation des documents de référence | `ollama` |
| `model_rewriter` | réécriture après rejet | `ollama` |
| `model_image` | image de couverture | `openai` |

**`sources:`** — réglages des documents de référence (voir 12 bis), requis dès qu'un sujet a des sources :

```yaml
sources:
  max_chunk_chars: 12000   # taille maximale d'un bloc de document envoyé au modèle (découpe sans perte)
  assign_batch: 40         # unités affectées aux chapitres par appel
  max_prompt_chars: 8000   # taille maximale du bloc de matière injecté dans le prompt d'un chapitre
```

Une clé manquante provoque une erreur explicite (`Réglage manquant dans params.yml : sources.…`), jamais une valeur par défaut silencieuse.

Les fournisseurs autorisés sont imposés par le code. **Seul le bloc nommé exactement `llm_config` est lu** ; les autres (`FASTllm_config`, `xllm_config`) sont des préréglages inertes : pour en activer un, renommer les blocs. Une clé `generation:` vide en tête de fichier est ignorée.

---

## 5. Les sujets

Un **sujet** est un dossier `subjects/<slug>/`. Le slug ne contient que minuscules, chiffres et tirets. Le dossier `subjects/` n'est pas versionné : il est créé au premier `manual subject new`, et les sujets sont à sauvegarder séparément (un clone du dépôt n'en contient aucun).

### 5.1 Contenu d'un dossier de sujet

| Fichier | Statut | Rôle |
|---|---|---|
| `subject.yml` | obligatoire | Cadrage (voir 5.2) |
| `requirements.yml` | facultatif | Critères propres au sujet |
| `system_prompt.md` | facultatif | Remplace **entièrement** le prompt système générique |
| `toc_instruction.md` | facultatif | Remplace **entièrement** l'instruction de génération du plan |

Les fichiers de remplacement sont envoyés tels quels : c'est à l'auteur de conserver le format de sortie attendu (schéma JSON du plan, etc.).

### 5.2 `subject.yml`

| Champ | Rôle | Obligatoire |
|---|---|---|
| `titre` | Titre du sujet | oui |
| `langue` | Langue de rédaction | oui |
| `role` | Personnage de l'auteur (expertise, références) | oui |
| `objectif` | Ce que le manuel doit apporter | oui |
| `public` | Lecteurs visés | oui |
| `niveau` | Niveau atteint | oui |
| `ton` | Ton de rédaction | oui |
| `plan_directeur` | Progression des grandes parties, séparées par des flèches | oui |
| `exclusions` | Liste de thèmes à ne pas traiter | non |
| `instructions` | Consignes libres (sources, exemples, style) | non |

Un champ inconnu, manquant ou vide est refusé avec un message explicite. Le gabarit « À COMPLÉTER » du squelette est rejeté au chargement. Ces champs alimentent `prompts/system_prompt.md` et `prompts/toc_instruction.md`.

### 5.3 Critères de relecture

Trois niveaux s'additionnent, pour chaque section :

1. **Communs** : `requirements/requirements.yml`, neutres vis-à-vis du sujet — définitions claires, cohérence avec le plan, exemples concrets, style et absence de métadiscours, Markdown propre, marqueur de fin (bloquants) ; typographie et lexique, densité, limites des méthodes, tableaux comparatifs, honnêteté des exemples, absence de redites (recommandés). Aucun critère n'impose de rubrique fixe (liste de contrôle, anti-patterns…) : ces rubriques plaquées dans chaque chapitre produisaient du remplissage. Les exigences propres à une discipline (par exemple « un exemple de prompt complet » pour le prompt engineering) vont dans le `requirements.yml` du sujet.
2. **Du sujet** (`generic`) : `subjects/<slug>/requirements.yml`.
3. **D'une partie** (`parties`) : clé = **titre exact** de la partie dans le plan. Une introduction ou une conclusion n'appartient à aucune partie : elle n'est jugée que sur les critères communs et ceux du sujet.

Format d'un critère : `id` unique (`^[a-z][a-z0-9_]*$`), `description`, `severity` (`bloquant` | `recommande`).

```yaml
version: 1
generic:
  - id: exemple_concret
    description: "Chaque notion est illustrée par un exemple."
    severity: bloquant
parties:
  "Titre exact de la partie":
    - id: ...
```

### 5.4 Commandes de gestion

| Commande | Effet |
|---|---|
| `manual subject list` | Liste les sujets (un sujet incomplet est signalé `INVALIDE`). |
| `manual subject new SLUG ["descriptif" \| -f FICHIER]` | Crée un sujet. Avec descriptif (en ligne, fichier, ou `-` = stdin) : le modèle rédige tous les champs et quelques critères. Sans : squelette « À COMPLÉTER ». |
| `manual subject refine SLUG ["consigne" \| -f FICHIER]` | Le modèle applique la consigne ; ancienne version dans `subject.yml.bak`. |
| `manual subject edit [SLUG]` | Ouvre `subject.yml` dans `$VISUAL`/`$EDITOR`, puis le valide. |
| `manual subject criteria [SLUG] [--force]` | Propose 1 à 3 critères par partie pertinente du plan **déjà généré** ; les parties déjà pourvues sont laissées sauf `--force` ; ancienne version dans `requirements.yml.bak`. |
| `manual subject check [SLUG] [--show]` | Valide ; `--show` affiche les prompts tels qu'ils seront envoyés. |
| `manual subject delete SLUG [-y] [--with-output]` | Supprime le dossier du sujet après confirmation `[o/N]` ; `--with-output` supprime aussi `output/<slug>/` (incompatible avec `--output`). |

Garanties : rien n'est écrit tant que la réponse du modèle n'est pas valide ; une sauvegarde `.bak` est conservée à chaque réécriture ; les commentaires YAML ne sont pas conservés par `refine` et `criteria`.

Le mieux est de retoucher le sujet **avant** `init`.

---

## 6. Le plan : `toc.yml`, introduction et conclusion

### 6.1 Génération

`manual init` demande à `model_write` un plan en JSON strict, validé par `GeneratedTocSchema` (3 essais, l'erreur de validation étant renvoyée au modèle). Chaque chapitre **et** chaque sous-section doit avoir une `description` d'une phrase, transmise ensuite au rédacteur.

Règles de la consigne de plan : au moins 2 chapitres par partie, 2 à 5 sous-sections par chapitre (jamais une sous-section orpheline), titres en casse française, style nominal parallèle, sans point final.

### 6.2 Deux fichiers distincts, sans doublon

| Fichier | Rôle | Qui l'édite |
|---|---|---|
| **`toc.yml`** | Le plan : titres et descriptions, **sans aucun numéro** | vous (à la main) |
| **`manifest.json`** | Le suivi : sujet et, par section, `numero`, `titre`, `status`, `attempts`, `last_verdict` | le programme |
| `00_toc.md` | Vue Markdown lisible du plan | régénérée (par `init`, `improve-toc` et au début de `write`) |

Les numéros ne sont jamais une donnée à maintenir : ils sont **déduits de la position** à chaque lecture — parties en chiffres romains (I, II…), chapitres de 1 à N sur tout le manuel, sous-sections `chapitre.rang` (`3.2`).

### 6.3 Format de `toc.yml`

```yaml
titre_manuel: Mon manuel
introduction:                       # facultatif
  titre: Introduction
  description: Présente le sujet, le public et le plan.
  sous_sections: []
parties:
  - titre: Les fondamentaux
    chapitres:
      - titre: Qu'est-ce qu'un prompt
        description: Définit le prompt et ses composantes.
        sous_sections:
          - titre: Définition
            description: Pose le vocabulaire de base.
          - titre: Anatomie d'un prompt
            description: Décrit rôle, contexte, tâche, format.
  - titre: Les techniques
    chapitres:
      - titre: ...
conclusion:                         # facultatif
  titre: Conclusion
  description: Synthèse et ouverture.
  sous_sections: []
```

### 6.4 Introduction et conclusion

Elles sont **hors des parties**, optionnelles et indépendantes :

- l'introduction est la **section 0** (fichier `00_introduction.md`) ;
- la conclusion est la **section N+1** (fichier `NN_conclusion.md`), son numéro se décale tout seul quand on ajoute un chapitre ;
- le titre dans le texte est `## Introduction` / `## Conclusion` (sans numéro), contre `## 3. Titre` pour un chapitre ;
- leurs sous-sections sont facultatives (`[]` accepté) ; celles de l'introduction se numérotent `0.1`, `0.2`… ;
- elles reçoivent une consigne propre (`prompts/role_introduction.md`, `prompts/role_conclusion.md`) : l'introduction présente sujet, public, mode d'emploi et annonce le plan sans développer le fond ; la conclusion synthétise et ouvre, sans notion nouvelle ;
- **elles sont rédigées après les chapitres** (voir 7.4), pour s'appuyer sur la mémoire du manuel écrit ;
- elles se ciblent comme les autres sections : `manual write -s 0`, `manual redo 0`, `manual improve 0`, `manual publish 0`.

Un manuel sans introduction ni conclusion reste valide (ancien manuel, ou sujet qui n'en veut pas) : le schéma ne les exige pas, la consigne de plan les demande.

### 6.5 Modifier le plan à la main

Éditer `toc.yml` (renommer, réordonner, ajouter, supprimer ; aucun numéro à corriger). À la lecture suivante :

| Modification | Effet |
|---|---|
| Chapitre **ajouté** | Statut `pending` |
| Chapitre dont le **titre change** | Repart en `pending` (son fichier `NN_titre.md` n'est plus celui du plan) |
| Chapitre **déplacé** (numéro différent) | Repart en `pending` (le suivi est apparié sur le couple numéro + titre) |
| **Description** modifiée | Statut inchangé ; relancer `redo` ou `improve` pour en tenir compte |
| Chapitre inchangé | Statut, tentatives et verdict conservés |

Les fichiers de chapitres déjà écrits ne sont jamais supprimés ni renommés : un fichier devenu inutile reste en place. Pendant que `write` tourne, ne modifiez pas `toc.yml` : le plan est lu au lancement. Un `toc.yml` invalide (YAML cassé, `parties` vide, partie sans `chapitres`, description manquante…) provoque une erreur explicite `toc.yml invalide : …` (code de sortie 1). Un `manifest.json` récent sans `toc.yml` est refusé (`toc.yml introuvable … le plan du manuel est perdu`).

Pour faire relire le plan par un modèle : `manual improve-toc` (section 11.2).

### 6.6 Compatibilité

Un ancien `manifest.json`, qui contenait le plan complet (`toc` et sections recopiées), est relu tel quel puis **migré** à la première sauvegarde : création de `toc.yml` et simplification du manifeste.

---

## 7. Le pipeline de rédaction

### 7.1 Boucle d'une section (`write_section`)

1. **Brouillon** — `model_write` reçoit le prompt système du sujet et l'instruction de section : numéro, titre, description, sous-sections attendues avec leur description, **plan complet de l'ouvrage** (chapitre en cours signalé) et **mémoire**.
2. **Jugement** — `model_judge` évalue le texte contre les critères applicables ; il reçoit aussi le titre et les sous-sections attendus et les règles de rédaction du prompt système (pour juger la cohérence avec le plan, le style et la typographie). Il répond en JSON (`accept` ou `revise`, avec la liste des problèmes : id du critère, sévérité, détail).
3. **Garde-fou local** — si le juge répond `accept` mais liste un problème **bloquant** (d'après les critères), le verdict est forcé à `revise`.
4. **Réécriture** — si `revise`, `model_rewriter` corrige à partir des problèmes relevés (les `bloquant` obligatoirement, les `recommande` s'ils améliorent le texte), avec le même prompt système que le rédacteur, puis le juge relit. Au plus `--max-rewrite` cycles (défaut 2).
5. **Acceptation** — la section est `done` seulement si le juge accepte **et** que le marqueur de fin exact est présent. Sinon : `failed`.
6. **Écriture et suivi** — le fichier est écrit (même en cas d'échec), le manifeste est mis à jour.
7. **Mémoire** — `model_think` intègre la section au digest (voir 8).

### 7.2 Format imposé d'une section

- commence par `## N. Titre` (chapitre) ou `## Titre` (introduction / conclusion), sans titre de niveau supérieur ni préambule ;
- synthèse d'environ 7 à 10 % du volume, en citation Markdown (`>`), sans titre ni étiquette — pour les chapitres ;
- chaque sous-section annoncée, dans l'ordre, sous un titre `###` (numéro et titre seulement) ;
- se termine par `--- Fin de la section N — Dis « continue » pour la suivante ---`, rien après. Le marqueur est retiré du fichier final.

### 7.3 Parallélisme

`manual write` traite les sections cibles avec un pool de workers (`-w`, défaut 4). Deux verrous protègent les écritures partagées de `manifest.json` et `memory.md`. Chaque rédaction relit le digest le plus récent au moment de son lancement.

### 7.4 Ordre : chapitres d'abord, introduction et conclusion ensuite

`write` exécute deux phases : d'abord tous les **chapitres** ciblés, puis l'**introduction** et la **conclusion** ciblées. Les résultats sont renvoyés dans l'ordre demandé.

### 7.5 Reprise

`manual write` sans option traite toutes les sections **non `done`** (`pending` et `failed`) : relancer la commande reprend après une interruption ou un échec.

---

## 8. La mémoire et la vue d'ensemble de l'ouvrage

Deux mécanismes complémentaires donnent au rédacteur une vue du manuel entier (réponse aux deux défauts : sections qui s'ignorent, et répétitions).

### 8.1 Le plan de l'ouvrage

Chaque rédaction (`write`, `redo`, `improve`) reçoit le plan **complet** : introduction, parties, chapitres avec leur description, sous-sections, conclusion ; la section en cours est marquée `← CHAPITRE EN COURS`. Le prompt demande de ne pas développer ce qui relève d'un autre chapitre (y renvoyer brièvement) et de s'appuyer sur ce que les chapitres précédents ont posé. Le plan est construit à partir de l'état courant (`render_plan`) : il reflète les éditions de `toc.yml`.

### 8.2 La mémoire (digest) structurée

`memory.md` est mis à jour par `model_think` après chaque section acceptée (800 mots maximum) selon des rubriques fixes, chaque entrée portant le numéro du chapitre :

- **Idées déjà développées**
- **Métaphores et images déjà utilisées**
- **Termes définis**
- **Exemples déjà utilisés**
- **Décisions de terminologie et de style**
- **Continuité**

Le rédacteur a pour consigne de ne reprendre ni idées, ni métaphores, ni exemples déjà utilisés, et de renvoyer au chapitre concerné. Au-delà de **12 000 caractères**, le digest est recompressé par le modèle en conservant ses rubriques ; si le modèle répond vide, le digest est tronqué à ce seuil.

`manual init` (avec ou sans `--force`) réinitialise la mémoire à « (Aucune section rédigée pour l'instant.) ».

> Le digest n'est alimenté que par les sections acceptées. Un digest issu d'une ancienne version du programme n'a pas ces rubriques : elles apparaissent au fil des prochaines sections acceptées. Pour assainir des sections déjà écrites : `manual improve N -i "supprime les redondances avec les autres chapitres"`.

---

## 9. Référence des commandes

### 9.1 Options globales (avant la sous-commande)

| Option | Effet |
|---|---|
| `--subject SLUG` | Sujet (dossier de `subjects/`). Facultatif s'il n'en existe qu'un ; **obligatoire dès qu'il y en a plusieurs**, sauf pour `status`, `publish`, `traces`, `glossary` quand `--output` est donné. |
| `--output DIR` | Répertoire de sortie (défaut : `output/<slug>/`). |

### 9.2 `manual init [--force]`

Génère le plan : écrit `toc.yml`, `manifest.json`, `00_toc.md`, initialise `memory.md`. Si un plan existe déjà : refuse (code 1) sans `--force` ; avec `--force`, avancement **et mémoire** sont réinitialisés (les fichiers de chapitres restent sur le disque).

### 9.3 `manual write [-s N…] [--max-rewrite K] [-w W]`

| Option | Effet |
|---|---|
| `-s, --section N [N…]` | Sections à rédiger : numéros isolés et intervalles inclusifs (`-s 0 1 3 5-8`). Défaut : toutes les sections non `done`. |
| `--max-rewrite K` | Cycles de réécriture maximum après rejet (défaut 2). |
| `-w, --worker W` | Workers en parallèle (défaut 4). |

Affiche `[OK]` ou `[A REVOIR]` par section ; **code de sortie 0 même si des sections échouent** (utiliser `manual status` dans un script). Régénère `00_toc.md` au démarrage.

### 9.4 `manual status`

Affiche `N. [statut] titre` pour chaque section (l'introduction est `0`) et `x/y sections terminées`. Pour un chapitre qui a reçu de la matière de documents de référence : `— sources : x/y traitées, z écartée(s)`. Code 1 si aucun plan n'existe.

### 9.5 `manual redo N [--max-rewrite K]`

Régénère la section N **depuis zéro**, sans relire l'existant.

### 9.6 `manual improve N… [-i TEXTE | -f FICHIER] [--max-rewrite K] [-w W]`

Améliore des sections déjà écrites (section 11.1). Consigne : `-i` en ligne, `-f` depuis un fichier (`-` = stdin) ; **les deux ensemble sont refusés**.

### 9.7 `manual improve-toc [-i TEXTE | -f FICHIER]`

Améliore le plan sans rien perdre (section 11.2).

### 9.8 `manual glossary`

Génère `glossaire.md` (section 12).

### 9.8 bis `manual sources …`

Documents de référence (section 12 bis).

| Commande | Effet |
|---|---|
| `sources add FICHIER… [--force]` | Copie des `.md`/`.txt` dans `subjects/<slug>/sources/` (refuse d'écraser sans `--force`) |
| `sources list` | Fichiers et état de l'analyse (unités, dont utiles) |
| `sources extract` | Analyse les fichiers nouveaux ou modifiés (cache par empreinte) et consolide |
| `sources assign [--force]` | Affecte les unités aux chapitres (nouvelles seulement ; `--force` recalcule, ancienne carte en `.bak`) |
| `sources show N` | Affiche la matière que recevra la section N à la rédaction |
| `sources orphans` | Unités utiles qu'aucun chapitre ne développe |
| `sources conflicts` | Contradictions repérées entre sources |

### 9.9 `manual publish N [--no-image]`

Prépare le paquet LinkedIn de la section N, qui doit être `done` (section 13).

### 9.10 `manual traces [--host H] [--port P]`

Interface web locale sur le journal des appels (défaut `127.0.0.1:8787`). Nécessite l'extra `web`.

### 9.11 `manual subject …`

Voir section 5.4.

### 9.12 Codes de sortie

| Code | Signification |
|---|---|
| `0` | Succès (y compris sections individuelles en échec : lire `status`) |
| `1` | Erreur connue (`Erreur : …` sur stderr), ou `init` sans `--force` sur un plan existant, ou `status` sans plan |

Erreurs connues capturées centralement : `ConfigError`, `GeneratorError`, `ParsingError`, `PatternError`, `ProviderError`, `PublishError`, `RequirementsError`, `SourcesError`, `StateError`, `SubjectError`.

---

## 10. Flux de travail

```bash
# 1. Cadrer
manual subject new mon-sujet -f descriptif.txt
manual subject check mon-sujet --show

# 2. Planifier
manual --subject mon-sujet init
#    relire output/mon-sujet/00_toc.md ; éditer toc.yml à la main si besoin
manual --subject mon-sujet improve-toc -i "ajoute un chapitre sur l'évaluation"
manual --subject mon-sujet subject criteria        # critères par partie (facultatif)

# 3. Tester la qualité sur un chapitre
manual --subject mon-sujet write -s 1

# 4. Écrire le reste (chapitres, puis introduction et conclusion)
manual --subject mon-sujet write

# 5. Contrôler et corriger
manual --subject mon-sujet status
manual --subject mon-sujet redo 7
manual --subject mon-sujet improve 3 5-8 -i "moins de redites, plus d'exemples"

# 6. Compléter
manual --subject mon-sujet glossary
manual --subject mon-sujet publish 1
```

Conseils : rédiger d'abord un chapitre seul pour juger la qualité avant de lancer le manuel entier ; ajuster sujet, critères ou modèles avant de relancer ; compter plusieurs heures pour un manuel complet avec un modèle à longue réflexion.

### Que faire quand le résultat ne convient pas ?

| Situation | Commande |
|---|---|
| Section ratée ou hors sujet | `redo N` (depuis zéro) |
| Section correcte mais à enrichir ou à dédoublonner | `improve N -i "…"` |
| Plan à corriger, des chapitres déjà écrits | `improve-toc`, ou édition de `toc.yml` |
| Plan à refaire, rien d'écrit | `init --force` |
| Toutes les sections trop faibles | `subject criteria` / `subject refine`, un meilleur `model_judge` / `model_rewriter`, puis `redo` / `improve` |
| Des répétitions entre chapitres | `improve N -i "supprime les redites avec les autres chapitres"` |

---

## 11. Améliorer le contenu et le plan

### 11.1 `manual improve`

Le texte existant sert d'**amorce** à une nouvelle génération complète, avec la même boucle que `write` (juge, réécriture, mémoire), le plan de l'ouvrage et le digest.

- Sans consigne : « relis et améliore » (`prompts/improve_default_instruction.md`).
- Le titre et les sous-sections du plan sont conservés.
- **Rien n'est perdu** : la nouvelle version ne remplace l'ancienne que si elle est **acceptée** (juge + marqueur). L'ancienne est alors conservée en `NN_titre.md.bak`. Sinon l'original, le statut, le manifeste et la mémoire restent intacts, et la version refusée est écrite en `NN_titre.candidate.md`.
- Une section `failed` qui a du contenu peut être améliorée ; une section sans fichier doit d'abord passer par `write` (erreur explicite sinon).
- Options : `--max-rewrite`, `-w`.

### 11.2 `manual improve-toc`

Relit et améliore le plan **en partant de l'actuel** (le modèle reçoit le plan en JSON, la consigne et la liste des chapitres figés).

- **Chapitres `done` figés** : même numéro, même titre, mêmes sous-sections (numéros et titres) ; leur description peut être précisée. Sinon la réponse est refusée avec la liste des violations renvoyée au modèle (3 essais, puis arrêt **sans rien modifier**).
- Le reste est librement modifiable : réordonner, fusionner, scinder, ajouter, supprimer, renommer des parties.
- Les numéros sont recalculés (chapitres de 1 à N consécutifs).
- **Avancement préservé** : un chapitre inchangé (même numéro, titre, sous-sections) garde statut, tentatives et verdict ; un chapitre nouveau ou modifié repasse en `pending`.
- **Introduction et conclusion** : conservées ou ajoutées par le modèle ; contrairement aux chapitres, elles ne sont **pas figées** — modifiées, elles repartent en `pending`. Le numéro de la conclusion change si le nombre de chapitres change : elle est alors à (ré)écrire.
- **Rien n'est supprimé** : fichiers de chapitres et mémoire ne sont jamais touchés ; les fichiers devenus inutilisés sont listés. La version précédente est archivée dans `toc_history/<AAAAMMJJ-HHMMSS>/` (`manifest.json`, `toc.yml`, `00_toc.md`).
- Si le modèle ne change rien : « Aucun changement » et rien n'est écrit.
- **Critères par partie** : les parties renommées laissent des clés orphelines dans `requirements.yml` ; la commande les signale (relancer `subject criteria --force`).

---

## 12. Le glossaire

`manual glossary` construit `glossaire.md` à partir des chapitres **terminés** (`done`), en deux temps :

1. **Extraction** : un appel `model_write` par chapitre (`prompts/glossary_extract_instruction.md`) ; le modèle repère les termes, concepts et sigles que le chapitre définit ou emploie de façon importante, avec une définition d'une à deux phrases fidèle au texte.
2. **Consolidation** : un dernier appel (`prompts/glossary_merge_instruction.md`) reçoit toutes les entrées avec leur numéro de chapitre, fusionne les doublons et variantes (casse, pluriel, sigle et forme développée), harmonise les définitions, conserve la liste des chapitres de chaque terme et écarte les entrées triviales.

Rendu : `# Glossaire — <titre du manuel>`, puis une ligne par terme, **triée alphabétiquement sans tenir compte de la casse ni des accents** :

```
- **Prompt** — consigne envoyée au modèle (chap. 1, 3)
```

Particularités :

- le glossaire est **régénéré en entier** à chaque appel et ne reflète que les chapitres terminés ;
- il s'appuie sur le manifeste et le dossier de sortie (pas sur le sujet) ;
- erreurs explicites : pas de manifeste (`manual init`), aucun chapitre terminé, fichier d'un chapitre `done` introuvable, JSON invalide après 3 essais.

---

## 12 bis. Documents de référence

Pour donner de la matière à la rédaction, un sujet peut fournir des documents : bibliographie commentée, thèmes préparés, notes plus ou moins structurées, passages déjà rédigés… et même des textes inutiles (ils sont écartés). Ils vont dans `subjects/<slug>/sources/` (`.md` ou `.txt`, sous-dossiers admis, fichiers cachés ignorés ; non versionné comme le reste du sujet).

```bash
manual sources add notes/biblio.md notes/themes.md   # copie dans subjects/<slug>/sources/
manual sources extract                               # analyse + consolidation (cache par empreinte)
manual sources list
manual sources assign                                # unités -> chapitres (après `manual init`)
manual sources show 3                                # ce que recevra le chapitre 3
```

En pratique `init`, `improve-toc`, `write` et `improve` font l'analyse et l'affectation **eux-mêmes** dès que `sources/` contient des fichiers ; les sous-commandes servent à les lancer à la main et à contrôler.

### 12 bis.1 Principe : des unités de matière

Chaque fichier est découpé par `model_think` en **unités** :

| Champ | Sens |
|---|---|
| `id` | `<fichier>#<n>`, stable |
| `type` | `idee`, `fait`, `reference`, `exemple`, `passage` (texte déjà rédigé), `theme` |
| `enonce` | l'unité reformulée en une ou deux phrases |
| `extrait` | passage **copié mot pour mot** : il est vérifié dans le fichier (espaces ignorés), et le modèle est relancé s'il en invente |
| `utilite` | `haute` (à couvrir), `moyenne` (si pertinent), `nulle` (écartée : reste dans l'index, n'est jamais injectée) |
| `themes` | un à trois mots-clés |

L'utilité est jugée par rapport au manuel visé (titre, objectif, public du sujet). Un fichier long est découpé en blocs (titres Markdown, paragraphes, lignes, tranches : rien n'est perdu). Les résultats sont mis en cache dans `sources_index.json` selon l'empreinte du contenu **et** du contexte du sujet : seuls les fichiers nouveaux ou modifiés sont ré-analysés ; un fichier supprimé quitte l'index.

Une passe de **consolidation** fusionne les doublons entre fichiers (provenances conservées dans `autres_sources`) et signale les **contradictions** (`manual sources conflicts`) ; elle n'est refaite que si les unités changent.

### 12 bis.2 Affectation exclusive : `sources_map.yml`

Chaque unité utile reçoit **un seul chapitre principal** (qui la développe : pas de redite entre chapitres) et, facultativement, un chapitre **secondaire** qui y renvoie en une phrase. L'introduction et la conclusion peuvent en recevoir. La carte est un YAML éditable :

```yaml
Raisonnement et exemples:     # titre du chapitre dans toc.yml
  principal: [biblio.md#1, biblio.md#2]
  secondaire: []
orphelines: [themes.md#4]     # unités laissées de côté
```

- Seules les unités **nouvelles ou sans chapitre** sont affectées : vos retouches (et commentaires) restent. `sources assign --force` recalcule tout (ancienne carte en `sources_map.yml.bak`).
- Un chapitre renommé ou supprimé dans `toc.yml`, ou une unité disparue, sont retirés de la carte ; les unités concernées sont réaffectées.
- Une unité principale dans deux chapitres, ou une carte mal formée, est refusée avec une erreur explicite.
- `manual sources orphans` liste la matière utile qu'aucun chapitre ne développe : un signal pour revoir le plan.

### 12 bis.3 Dans la rédaction

Le prompt d'un chapitre (`write`, `redo`, `improve`) reçoit un bloc **Matière fournie par l'auteur**, groupé par type avec une consigne adaptée : citer exactement les références (sans en inventer), reprendre et étoffer les passages, développer thèmes et idées, reformuler faits et exemples. Les unités `haute` sont marquées **À COUVRIR** ; les renvois indiquent le chapitre qui développe l'unité. Une contradiction (⚠) doit être présentée comme un débat. Statut des sources : **de la matière, pas une vérité**.

Le bloc est limité par `sources.max_prompt_chars` : si nécessaire les unités de moindre priorité perdent d'abord leur extrait, puis sont omises, et le bloc le **dit** (`Omis faute de place : …`). Une unité omise n'est jamais exigée du rédacteur.

### 12 bis.4 Relecture : la couverture

Quand un chapitre a des unités À COUVRIR, le juge reçoit un critère **bloquant** `couverture_sources` : chaque unité doit être traitée, ou explicitement écartée par le rédacteur avec une ligne `<!-- écarté [id] : motif -->` (motif recevable : hors sujet, douteux). Une unité ni traitée ni écartée provoque une réécriture. Les commentaires d'écart sont retirés du fichier du chapitre et gardés dans `manifest.json` ; `manual status` affiche `sources : x/y traitées, z écartée(s)`.

### 12 bis.5 Dans le plan

`init` et `improve-toc` reçoivent un résumé de la matière **par thème** (nombre d'unités, types, quelques énoncés) : les thèmes utiles doivent trouver leur place dans la structure. Ensuite l'affectation est (re)calculée. Les sources n'ont aucun effet sur un sujet qui n'en a pas : prompts et coûts sont inchangés.

### 12 bis.6 Coût et limites

- Un appel d'analyse par fichier (ou par bloc), un appel d'affectation par lot, une consolidation : mis en cache, relancés seulement quand les sources, le contexte du sujet ou le plan changent.
- L'affectation par LLM reste approximative : la carte est faite pour être corrigée à la main.
- Pas de recherche vectorielle : l'affectation passe par le LLM (aucun fournisseur d'embeddings n'est configuré).
- La qualité de l'extraction et de l'affectation dépend du modèle `model_think` ; la vérification mot pour mot ne garantit que la fidélité des extraits, pas l'exactitude des sources.

---

## 13. Publication LinkedIn

`manual publish N [--no-image]` prépare, pour une section **terminée**, un paquet dans `output/<slug>/publish/<section>/` :

| Fichier | Contenu |
|---|---|
| `article.html` | La section en HTML autonome, à ouvrir dans un navigateur puis à copier-coller dans l'éditeur d'article LinkedIn (qui ne comprend pas le Markdown brut mais conserve la mise en forme du HTML collé ; les tableaux passent mal) |
| `post.txt` | Brouillon de post (`model_write`), terminé par le jeton `{ARTICLE_URL}` à remplacer par le lien de l'article |
| `cover.png` | Image de couverture (`model_image`, OpenAI) ; omise avec `--no-image` |

**Rien n'est publié automatiquement** : l'API LinkedIn ne permet pas de créer des articles ; la création de l'article et la publication du post restent manuelles. Une section non `done` est refusée (`PublishError`).

---

## 14. Fichiers produits

Dans `output/<slug>/` (ou `--output`) :

| Fichier | Contenu |
|---|---|
| `toc.yml` | **Le plan, à éditer à la main** (sans numéros) |
| `manifest.json` | Le suivi seul (sujet ; par section : `numero`, `titre`, `status`, `attempts`, `last_verdict`) |
| `00_toc.md` | Vue lisible du plan (descriptions en italique) |
| `00_introduction.md` | Introduction (section 0), si le plan en a une |
| `NN_titre-du-chapitre.md` | Un fichier par chapitre ; `NN_conclusion.md` pour la conclusion |
| `NN_….md.bak` | Version précédente, après `improve` |
| `NN_….candidate.md` | Version d'`improve` refusée par la relecture |
| `memory.md` | Digest structuré transmis aux rédactions |
| `glossaire.md` | Glossaire généré |
| `sources_index.json` | Unités de matière extraites des documents de référence (cache) |
| `sources_map.yml` | Affectation des unités aux chapitres (éditable) |
| `toc_history/<date-heure>/` | Anciens plans archivés par `improve-toc` |
| `traces/calls.jsonl` | Journal de tous les appels LLM |
| `publish/<section>/` | Paquets de publication LinkedIn |

Dans `subjects/<slug>/` : `subject.yml`, `requirements.yml`, `sources/` (documents de référence), éventuellement `system_prompt.md`, `toc_instruction.md`, et les `*.bak` créés par `subject refine` et `subject criteria`.

Le nom de fichier d'une section est `<numéro sur 2 chiffres>_<slug du titre>.md` (le slug est dérivé du titre : ASCII, minuscules, tirets).

---

## 15. Traçabilité et diagnostic

### 15.1 Journal des appels

Chaque tentative d'appel (réussie ou non) est ajoutée à `traces/calls.jsonl` (JSON Lines, thread-safe) avec : `role`, `model_key`, `model_name`, `attempt`, `started_at`, `ended_at`, `duration_seconds`, `success`, `input`, `output`, `error`. La traçabilité est activée une fois par commande ; elle est inactive tant qu'elle n'est pas configurée. Les commandes sans dossier de sortie (`subject new`, `subject refine`) ne sont pas journalisées.

### 15.2 `manual traces`

Serveur Flask local (page unique + API JSON) pour parcourir le journal : utile pour diagnostiquer des timeouts, des dérives de latence ou des réponses inattendues d'un modèle.

### 15.3 Reprises automatiques

Chaque appel est tenté jusqu'à **3 fois** (`MAX_RETRIES`) en cas d'erreur réseau, de réponse mal formée ou de statut HTTP d'erreur : backoff exponentiel à plein jitter (base 2 s, plafond 60 s), `Retry-After` respecté sur un HTTP 429. Après la dernière tentative : `ProviderError`.

---

## 16. Garanties et gestion des erreurs

- **Échec explicite** : configuration manquante, variable d'environnement absente, erreur fournisseur, JSON invalide, plan invalide → erreur claire, jamais de repli silencieux.
- **Configuration stricte** : clé inconnue ou `think` mal typé dans `params.yml` → refus au démarrage.
- **Rien n'est écrit avant validation** des réponses structurées (sujet, critères, plan, glossaire).
- **Sauvegardes** : `.bak` (sujet, critères, sections améliorées), `.candidate.md` (version refusée), `toc_history/` (anciens plans).
- **Le travail écrit est protégé** : `improve-toc` fige les chapitres rédigés et ne touche ni aux fichiers ni à la mémoire ; `improve` ne remplace une section que si la nouvelle version est acceptée.
- **Cohérence sujet/manuel** : le manifeste mémorise le sujet ; `write`, `improve`, `improve-toc` refusent un manuel généré pour un autre sujet (un manifeste sans sujet est accepté).
- **Double contrôle** d'une section : accord du juge **et** marqueur de fin ; un critère bloquant listé force la réécriture même si le juge a répondu « accept ».
- **Aucune publication automatique.**
- **Secrets hors du dépôt** : `params.yml` ne contient que des noms de variables.

---

## 17. Personnaliser les prompts

Tout le texte envoyé aux modèles est dans `prompts/` (prompts propres à un sujet : `subjects/<slug>/`). Les gabarits utilisent `string.Template` : **`$variable`, pas `{variable}`**. Ne pas renommer ni supprimer un placeholder ; `tests/test_prompts_integrity.py` détecte une dérive.

| Fichier | Rôle | Placeholders |
|---|---|---|
| `system_prompt.md` | Prompt système (rempli par `subject.yml`) | champs du sujet |
| `toc_instruction.md` | Génération du plan | `plan_directeur`, … |
| `section_instruction.md` | Rédaction d'une section | `numero`, `titre`, `intitule`, `description`, `sous_sections`, `plan`, `digest`, `role_note`, `sources` |
| `improve_instruction.md` | Amélioration d'une section | idem + `consigne`, `contenu_existant` |
| `improve_default_instruction.md` | Consigne d'amélioration par défaut | — |
| `role_introduction.md`, `role_conclusion.md` | Consigne propre à l'introduction / la conclusion (injectée comme `$role_note`) | — |
| `judge_instruction.md` | Relecture | `requirements`, `section_text`, `intitule`, `sous_sections`, `regles` |
| `rewrite_instruction.md` | Réécriture après rejet (avec le prompt système du sujet) | `section_text`, `issues`, `numero`, `sources` |
| `toc_improve_instruction.md`, `toc_improve_default_instruction.md` | Amélioration du plan | `toc_actuelle`, `consigne`, `chapitres_figes` |
| `glossary_extract_instruction.md` | Extraction des termes d'un chapitre | `numero`, `titre`, `texte` |
| `glossary_merge_instruction.md` | Consolidation du glossaire | `entrees` |
| `sources_extract_instruction.md` | Découpe d'un document en unités de matière | `contexte`, `fichier`, `texte` |
| `sources_consolidate_instruction.md` | Doublons et contradictions entre unités | `unites` |
| `sources_assign_instruction.md` | Affectation des unités aux chapitres | `plan`, `chapitres`, `unites` |
| `author_system_prompt.md`, `subject_generate_instruction.md`, `subject_refine_instruction.md`, `partie_criteria_instruction.md` | Rédaction assistée des sujets et critères | variables selon le fichier |
| `subject_template.yml` | Squelette d'un nouveau sujet | — |
| `linkedin_post_instruction.md` | Brouillon du post | — |

Les prompts de la **mémoire** (rubriques, limites de mots) sont des constantes de `manual_cli/memory.py` (`UPDATE_PROMPT`, `COMPRESS_PROMPT`, `MAX_DIGEST_CHARS`) et utilisent `str.format` (`{digest}`, `{section_text}`).

---

## 18. Architecture du code

```
manual_cli/
  cli.py               commandes et arguments ; gestion centrale des erreurs
  config.py            params.yml et ~/.env, relus à chaque appel (AppConfig.role)
  subjects.py          sujets : chargement, validation, prompts, critères
  subject_author.py    création, retouche et critères de sujet assistés par LLM
  generator.py         plan, rédaction, relecture, amélioration, phases d'écriture
  state.py             ManualState/SectionState, toc.yml, manifest.json, renumérotation, plan de l'ouvrage
  schemas.py           TocSchema, GeneratedTocSchema, Cadre, Chapitre, Partie, JudgeVerdict
  memory.py            digest structuré (mise à jour, compression)
  glossary.py          extraction par chapitre et consolidation
  sources.py           documents de référence : découpe, unités de matière, cache, consolidation
  sources_assign.py    affectation aux chapitres (sources_map.yml), bloc injecté, résumé pour le plan
  parsing.py           extraction/validation du JSON des modèles (call_structured, nouvelles tentatives)
  patterns.py          sélection de sections (-s 1 3 5-8)
  requirements_loader.py   lecture et assemblage des critères
  providers.py         clients Ollama Cloud / OpenAI, reprises, traces
  publish.py           paquet LinkedIn
  tracing.py, web/     journal des appels et interface de consultation
  mcp_affinity/        script annexe indépendant, non utilisé par `manual`
prompts/  requirements/  tests/  assets/   (versionnés)
subjects/  output/                         (locaux, non versionnés)
```

Points d'architecture notables :

- **Modèle d'état en mémoire vs sur disque** : `ManualState` (plan + sections) est reconstruit à chaque `load_state` à partir de `toc.yml` et du suivi de `manifest.json` ; `save_state` écrit les deux fichiers. Tout le reste du code manipule `ManualState` sans connaître le format disque.
- **Configuration juste-à-temps** : `load_config()` renvoie un `AppConfig` qui relit `params.yml`/`~/.env` à chaque `.role(name)`. Ne pas réintroduire de cache.
- **Indirections de clients** (`_client`, etc.) : points d'injection des tests.
- **Deux pièges d'URL couverts par des tests de régression** : `/api` non doublé pour Ollama, troncature après `/v1` pour OpenAI.

---

## 19. Développement et tests

```bash
.venv/bin/pip install -e ".[test,web]"
.venv/bin/python -m pytest                         # suite + couverture (seuil 90 %, actuellement 100 %)
.venv/bin/python -m pytest tests/test_state.py -q --no-cov
.venv/bin/python -m pytest -k nom_du_test -q --no-cov
```

Règles (voir `PRINCIPES.md`) : TDD strict (RED → GREEN → REFACTOR, y compris pour les corrections de bugs) ; couverture ≥ 90 % ; échec explicite plutôt que repli silencieux ; aucun paramètre en dur (modèles, délais, fournisseurs dans `params.yml`) ; chargement de configuration juste-à-temps ; docstrings Google et annotations de type partout ; commentaires seulement pour un *pourquoi* non évident. Pas de linter ni de typeur configurés.

Motifs de test :

- les tests de fournisseurs simulent `requests.post`/`requests.get` ;
- les tests d'orchestration remplacent les fonctions `_client` par des faux exposant `.chat()` / `.generate_image()` (voir `FakeClients`, `RoutingFakeClients`, et `Router` dans `tests/test_framing.py`, qui route d'après le texte du prompt plutôt que l'ordre des appels) ;
- les tests CLI remplacent les fonctions importées par `cli.py`, jamais argparse ;
- `tests/test_multi_subject_flow.py` joue un parcours complet sur un sujet autre que Prompt Engineering ;
- `tests/test_prompts_integrity.py` garde les placeholders de prompts et les clés de parties ;
- `tests/test_glossary.py`, `tests/test_framing.py`, `tests/test_state.py` couvrent le glossaire, l'introduction/conclusion et la persistance du plan.

Git : branche de travail `v0.1`, branche principale `main`, dépôt public `origin` (github.com/damienraczy/ai_manual). Ne commiter et ne pousser que sur demande.

---

## 20. Dépannage

| Symptôme | Cause probable et remède |
|---|---|
| `Variables d'environnement manquantes dans ~/.env` | Renseigner les variables nommées par `url` / `api_key` du modèle utilisé |
| `Erreur : … clé inconnue …` au démarrage | Clé non autorisée dans un modèle de `params.yml` (autorisées : `provider`, `name`, `url`, `api_key`, `timeout`, `think`) |
| Timeouts fréquents | Augmenter `timeout` du modèle (effet immédiat) ; consulter `manual traces` pour les durées |
| `Une table des matières existe déjà` | Utiliser `init --force` (réinitialise avancement et mémoire) |
| `toc.yml invalide : …` | Corriger le YAML : `parties` non vide, chaque partie avec `chapitres`, chaque chapitre avec `titre` et `description` |
| `toc.yml introuvable … le plan du manuel est perdu` | Restaurer `toc.yml` depuis `toc_history/` ou un ancien manifeste complet |
| Un chapitre repasse `pending` après édition du plan | Titre ou position modifié (voir 6.5) ; ses fichiers restent sur le disque |
| Section `failed` | Lire le dernier verdict (`manifest.json`), puis `redo N` ou `improve N`, ou renforcer `model_judge` / `model_rewriter` |
| Section `failed` « marqueur de fin manquant » | Le modèle n'a pas terminé par la ligne exacte ; relancer, ou allonger le `timeout` |
| `La section N n'a pas encore de contenu à améliorer` | Utiliser `write -s N` d'abord |
| `improve` : fichier `.candidate.md` | La nouvelle version a été refusée par la relecture ; l'original est intact, lire le candidat |
| Plan refusé par `improve-toc` après 3 essais | Le modèle ne respecte pas les chapitres figés ; préciser la consigne ; rien n'a été modifié |
| `Le manuel … a été généré pour le sujet X` | Utiliser `--subject X` ou un autre `--output` |
| `manual traces` : erreur d'import Flask | `pip install -e ".[web]"` |
| `ModuleNotFoundError` avec Python système | Utiliser `.venv/bin/python` |

---

## 21. Limites connues

- **Modèles texte** : uniquement Ollama Cloud ; OpenAI ne sert que pour l'image de couverture.
- **Numérotation des chapitres figés** : avec `improve-toc`, les chapitres déjà rédigés gardent leur numéro ; on ne peut pas en insérer un nouveau *entre* deux chapitres écrits. En éditant `toc.yml` à la main, insérer un chapitre décale les suivants, qui repartent en `pending` (titre/numéro appariés) et dont les fichiers `NN_…` ne correspondent plus.
- **Introduction et conclusion** : non figées par `improve-toc` ; la conclusion change de numéro quand le nombre de chapitres change.
- **Critères par partie fragiles** : indexés sur le titre exact des parties.
- **Mémoire et `improve`** : le digest mentionne déjà la version actuelle d'un chapitre avant son amélioration ; des redites sont possibles sur ce chapitre.
- **Redites entre sections** : réduites par le plan de l'ouvrage et la mémoire structurée, non éliminées ; l'efficacité dépend du modèle. Le contrôle reste humain (`improve` avec consigne).
- **Documents de référence** : affectation et extraction approximatives (voir 12 bis.6) ; seuls `.md`/`.txt` sont lus ; une unité écartée à tort par le rédacteur est signalée, pas empêchée.
- **Glossaire** : régénéré en entier, limité aux chapitres terminés ; la qualité de la fusion dépend du modèle.
- **Commentaires YAML** perdus par `subject refine` et `subject criteria` (l'ancienne version reste en `.bak`) ; `toc.yml` n'est réécrit que lorsque le plan change réellement (`init`, `improve-toc`, migration d'un ancien manifeste) : vos commentaires y survivent à `write`, mais pas à ces réécritures.
- **Publication LinkedIn** manuelle (limite de l'API).
- **Durée** : plusieurs heures pour un manuel complet avec un modèle à longue réflexion.

---

## 22. Licence

© 2026 Damien Raczy — tous droits réservés sauf autorisations ci-dessous. Utilisation, copie et adaptation permises sous deux conditions : **attribution** de l'auteur, et **aucun usage commercial**. Correspond à la licence CC BY-NC 4.0 (texte complet dans [`LICENSE`](LICENSE)). Logiciel fourni « tel quel », sans garantie ; les textes générés doivent être relus et vérifiés avant toute diffusion.
