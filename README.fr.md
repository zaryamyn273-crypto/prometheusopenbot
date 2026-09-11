# Prometheus — un bot Telegram ordinaire qui essaie d'être utile
> Un bot Telegram relié à un modèle de langage, avec quelques outils utiles (prix devises, or et crypto, météo, recherche web, musique, fichiers, calculs). Au lieu de deviner il va aux outils ; si un truc est cassé il le dit. Pas de miracles ici.

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Sommaire
- [Aperçu](#aperçu)
- [Structure du projet](#structure-du-projet)
- [Fonctionnement](#fonctionnement)
- [Obtention des clés API](#obtention-des-clés-api)
  - [1. Token du bot Telegram (TELEGRAM_BOT_TOKEN)](#1-token-du-bot-telegram-telegram_bot_token)
  - [2. ID numérique admin (ADMIN_ID)](#2-id-numérique-admin-admin_id)
  - [3. Clé et endpoint IA (ROUTER_API_KEY et ROUTER_BASE_URL)](#3-clé-et-endpoint-ia-router_api_key-et-router_base_url)
  - [4. Compte Cloudflare, D1 et KV](#4-compte-cloudflare-d1-et-kv)
  - [5. Clé de recherche Tavily (TAVILY_API_KEY)](#5-clé-de-recherche-tavily-tavily_api_key)
  - [6. Clé AllRatesToday (ALLRATESTODAY_API_KEY)](#6-clé-allratestoday-allratestoday_api_key)
  - [7. Token GitHub (GITHUB_TOKEN)](#7-token-github-github_token)
  - [8. Clés Spotify (SPOTIFY_CLIENT_ID et SPOTIFY_CLIENT_SECRET)](#8-clés-spotify-spotify_client_id-et-spotify_client_secret)
  - [9. Sandbox cloud E2B (E2B_API_KEY)](#9-sandbox-cloud-e2b-e2b_api_key)
- [Fichier .env](#fichier-env)
- [Installation pas à pas](#installation-pas-à-pas)
- [Déploiement cloud](#déploiement-cloud)
- [Matrice des outils](#matrice-des-outils)
- [Modèle de sécurité](#modèle-de-sécurité)
- [Tests](#tests)
- [Licence et contributions](#licence-et-contributions)

---

## Aperçu

**Prometheus** est un bot Telegram open-source qui branche un modèle de langage sur des outils réels. L'idée est simple, et c'est tout ce qu'il fait :

- **Ne devine pas, va vérifier :** tout ce qui demande des données en direct (prix, météo, actus, état des sites) vient directement d'un outil, pas de la mémoire du modèle. Si un outil est en panne, le bot dit qu'il ne sait pas. Point.
- **Pas besoin de clé pour tout :** seuls le token Telegram, l'ID admin et une clé de modèle compatible OpenAI sont requis. Le reste (Tavily, Cloudflare, GitHub, Spotify, E2B) est optionnel — sans ça, ça marche quand même, avec des replis gratuits.
- **Dans les groupes, il ne s'en mêle pas :** il ne répond que si on s'adresse à lui (réponse, mention ou le mot « Prometheus »). Le reste est archivé en silence.
- **Pas d'exécution locale :** Python part d'abord dans le sandbox cloud E2B (si clé), sinon dans un sandbox local isolé. Le shell destructif ne s'exécute jamais, même sur ordre de l'admin.
- **Pas que le persan :** détecte la langue Telegram de chaque utilisateur et répond dedans (anglais, russe, espagnol, français...) ; les sorties d'outils sont traduites au besoin.

---

## Structure du projet

Le repo est organisé de façon séparée, modulaire et standard :

```text
prometheusopenbot/
├── bot.py                     # Point d'entrée : serveur Telegram + boot du bot
├── requirements.txt           # Dépendances Python
├── .env.example               # Modèle de variables d'environnement
├── nixpacks.toml / railway.json # Config déploiement cloud (Railway / Nixpacks)
│
├── src/                       # Paquet principal
│   ├── core/                  # Base de données, IA, client HTTP et config
│   │   ├── ai_service.py      # Service LLM unifié, prompts, vision, outils
│   │   ├── config.py          # Chargement env, politique sécu, prompt système
│   │   ├── database.py        # Stockage cloud multi-niveaux (Cloudflare D1 et KV)
│   │   ├── http.py            # Gestion des sessions HTTP async
│   │   └── security.py        # Validation commandes, rate limits, anti-intrusion
│   ├── tools/                 # ~90 outils ciblés (extras supprimés)
│   │   ├── admin/             # Gouvernance des groupes et modération
│   │   ├── database/          # Requêtes et interaction cloud
│   │   ├── dev/               # Dev : GitHub, Reddit, StackOverflow
│   │   ├── files/             # Générer/extraire docs (PDF, Word, Excel, CSV)
│   │   ├── financial/         # Cours live : crypto, or, fiat et forex
│   │   ├── github/            # Repos/issues/commits GitHub
│   │   ├── internal/          # Optimiseurs mémoire, compression prompt, cache
│   │   ├── media/             # Téléchargement musique, métadonnées, paroles, voix
│   │   ├── scientific/        # Maths, stats, convertisseur d'unités
│   │   ├── system/            # Télémétrie, sandbox E2B, shell admin sûr
│   │   ├── web_network/       # Moteurs live (Tavily, Bing, Brave, Digikala)
│   │   └── registry.py        # Auto-enregistrement des schémas + dispatcher
│   ├── ui/                    # Panneau admin in-app (boutons inline)
│   └── utils/                 # Formatage Telegram, nettoyage sorties, typo
│
├── tests/                     # Suites de tests
│   ├── test_master.py         # Validation intégrale du système
│   ├── run_test_battery.py    # Simu bot, BD et stress
│   ├── test_stress.py         # Stabilité sous forte charge
│   ├── run_rigorous_tests.py  # Éval outils web/réseau live
│   ├── test_financial_scientific_suite.py # Tests finance et maths
│   ├── test_media_files_runner.py        # Tests docs/média/image
│   └── test_rigorous_battery.py          # Cas limites et entrées bizarres
│
└── assets/                    # Statiques et polices persanes
```

---

## Fonctionnement

Le bot tourne sur un pipeline moderne multi-couches :

```text
┌─────────────────────────────────────────────────────────────┐
│                   Utilisateur sur Telegram                  │
└──────────────────────────────┬──────────────────────────────┘
                                │ (texte, voix, réponse, fichier)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Dispatcher Engine                  │
│        (auth, rate limiting, analyse d'accès)                │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   3-Tier Memory Architecture                │
│  • L1 Cache : RAM locale ultrarapide pour cours/réponses    │
│  • Cloudflare KV : mémoire cloud distribuée clé/valeur      │
│  • Cloudflare D1 : SQL avec recherche texte FTS5            │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             Autonomous LLM Multi-Step Reasoner              │
│     (raisonnement multi-étapes + appels en parallèle)       │
└──────────────────────────────┬──────────────────────────────┘
                                │ (Parallel Tool Execution)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Tool Matrix (~90 outils)                    │
│  • Finance (Binance, Nobitex, or, pièces, Tether, forex)    │
│  • Web et actus (Tavily AI, scrapers, Digikala, météo)      │
│  • Média et audio (musique 320, Whisper STT, QR, Telegraph) │
│  • Ops et système (sandbox Python, logs, ban global)        │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram HTML & Shield Formatter              │
│     (masquage auto [SECRET] + formatage standard)           │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    Réponse vers Telegram                    │
└─────────────────────────────────────────────────────────────┘
```

### 1. Appels parallèles aux outils
Le message est d'abord analysé et découpé en intentions indépendantes. S'il y a plusieurs demandes dans un message (p. ex. prix du Bitcoin, météo de Téhéran et heure officielle d'un coup), le bot identifie les outils et les appelle en parallèle.

### 2. Stockage à 3 niveaux
- **Niveau 1 (L1 In-Memory Cache) :** cache RAM très rapide avec TTL pour les données live (changes, crypto).
- **Niveau 2 (Cloudflare Workers KV) :** mémoire cloud distribuée clé/valeur pour sessions, cache long et réglages dynamiques.
- **Niveau 3 (Cloudflare D1 SQL) :** BD relationnelle serverless avec FTS5 pour l'historique complet, les logs et les membres.

### 3. Isolation des commandes admin
Les outils sensibles (exécuter Python, terminal, gestion des groupes, ban global) exigent l'ID numérique admin (`ADMIN_ID`). Personne n'y accède par prompt injection ni usurpation.

---

## Obtention des clés API

Pour toutes les fonctions il faut quelques clés. Certaines sont **obligatoires** (premier boot), d'autres **optionnelles** (outils annexes).

### 1. Token du bot Telegram (TELEGRAM_BOT_TOKEN) — [obligatoire 🔴]
- **Usage :** identité du bot pour se connecter à Telegram et envoyer/recevoir des messages.
- **Comment l'avoir :**
  1. Ouvrez [@BotFather](https://t.me/BotFather) sur Telegram.
  2. Envoyez `/newbot`.
  3. Choisissez un nom affiché puis un username (doit finir par `bot`).
  4. BotFather donne un token du type `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
  5. Pour les groupes : lancez `/setprivacy` chez BotFather, choisissez le bot, mettez `Disable` pour qu'il lise les messages de groupe.

### 2. ID numérique admin (ADMIN_ID) — [obligatoire 🔴]
- **Usage :** identité du proprio/super-admin pour le panneau, l'exécution Python, les bans et les groupes.
- **Comment l'avoir :**
  1. Ouvrez [@userinfobot](https://t.me/userinfobot) ou [@JsonDumpBot](https://t.me/JsonDumpBot).
  2. Start pour recevoir l'ID numérique (p. ex. `123456789`).
  3. Mettez-le dans `ADMIN_ID`.

### 3. Clé et endpoint IA (ROUTER_API_KEY et ROUTER_BASE_URL) — [obligatoire 🔴]
- **Usage :** le cerveau : raisonnement, intentions et appels d'outils. Tout fournisseur compatible **OpenAI API** convient :
- **Options :**
  - **OpenAI officiel :**
    - [platform.openai.com](https://platform.openai.com/api-keys) → nouvelle clé (`sk-...`)
    - `ROUTER_BASE_URL=https://api.openai.com/v1`, `ROUTER_MODEL=gpt-4o-mini`
  - **OpenRouter (plein de modèles au même endroit) :**
    - [openrouter.ai](https://openrouter.ai/keys) → clé API
    - `ROUTER_BASE_URL=https://openrouter.ai/api/v1`, n'importe quel modèle (`google/gemini-flash-1.5`, `openai/gpt-4o-mini`)
  - **DeepSeek :**
    - [platform.deepseek.com](https://platform.deepseek.com/api_keys) → clé, `ROUTER_BASE_URL=https://api.deepseek.com/v1`, `ROUTER_MODEL=deepseek-chat`
  - **Groq (très rapide) :**
    - [console.groq.com](https://console.groq.com/keys) → clé gratuite, `ROUTER_BASE_URL=https://api.groq.com/openai/v1`, `ROUTER_MODEL=llama-3.3-70b-versatile`

### 4. Compte Cloudflare, D1 et KV — [optionnel 🟡]
- **Usage :** historique permanent, recherche plein-texte des vieux messages, bannis, cache cloud. Sans ça, RAM (L1).
- **Comment l'avoir gratis :**
  1. Compte sur [cloudflare.com](https://cloudflare.com).
  2. **Account ID :** ouvrez Workers & D1 dans le panel ; l'ID 32 caractères est à droite.
  3. **API Token :** *My Profile > API Tokens > Create Token*, modèle *Edit Cloudflare Workers*.
  4. **Base D1 :** *Workers & Pages > D1 SQL Database*, créez-en une (p. ex. `prometheus-db`), UUID dans `CLOUDFLARE_D1_ID`.
  5. **KV :** *Workers & Pages > KV*, créez un namespace (p. ex. `prometheus-kv`), ID dans `CLOUDFLARE_KV_ID`.

### 5. Clé de recherche Tavily (TAVILY_API_KEY) — [optionnel ⚪]
- **Usage :** moteur IA rapide pour actus live, comparaisons de versions, événements du jour.
- **Comment l'avoir gratis :**
  1. [tavily.com](https://tavily.com), inscription (gratis : 1000 recherches/mois, sans carte).
  2. Copiez la clé (commence par `tvly-`) dans `TAVILY_API_KEY`.

### 6. Clé AllRatesToday (ALLRATESTODAY_API_KEY) — [optionnel ⚪]
- **Usage :** taux fiat directs (USD, EUR, AED...) et or/pièces d'Iran.
- **Comment l'avoir :**
  1. [allratestoday.com](https://allratestoday.com), inscription, clé `art_live_...`.
  2. *(Sans elle le bot bascule sur les scrapers web tout seul.)*

### 7. Token GitHub (GITHUB_TOKEN) — [optionnel ⚪]
- **Usage :** limites hautes pour les 12 outils GitHub (code/commits/issues/releases).
- **Comment l'avoir gratis :**
  1. [github.com/settings/tokens](https://github.com/settings/tokens).
  2. *Generate new token (classic)*, cochez `public_repo`, token `ghp_...` dans `GITHUB_TOKEN`.

### 8. Clés Spotify (SPOTIFY_CLIENT_ID et SPOTIFY_CLIENT_SECRET) — [optionnel ⚪]
- **Usage :** pochettes officielles et métadonnées exactes des morceaux étrangers.
- **Comment les avoir gratis :**
  1. [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
  2. Créez une app, copiez `Client ID` et `Client Secret`.
  3. *(Sans elles : iTunes API + métadonnées par défaut.)*

### 9. Sandbox cloud E2B (E2B_API_KEY) — [optionnel ⚪]
- **Usage :** exécuter Python/JavaScript/shell isolé dans le cloud, zéro charge serveur. Sans elle : sandbox local.
- **Comment l'avoir gratis :**
  1. Inscription sur [e2b.dev](https://e2b.dev).
  2. Clé du [panel E2B](https://e2b.dev/dashboard?tab=keys) (commence par `e2b_`).
  3. Mettez-la dans `E2B_API_KEY`. (Optionnel : `E2B_TEMPLATE` pour un template perso, `E2B_TIMEOUT_SEC` pour le plafond.)

---

## Fichier .env

Créez un `.env` à la racine et remplissez selon le guide :

| Variable | Type | Défaut | Usage |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | obligatoire 🔴 | - | Token du bot, via BotFather |
| `ADMIN_ID` | obligatoire 🔴 | `0` | ID numérique du super-admin Telegram |
| `ROUTER_BASE_URL` | obligatoire 🔴 | `https://api.openai.com/v1` | Endpoint V1 compatible OpenAI |
| `ROUTER_API_KEY` | obligatoire 🔴 | - | Clé du modèle IA |
| `ROUTER_MODEL` | optionnel ⚪ | `gpt-4o-mini` | Modèle (`gpt-4o-mini`, `deepseek-chat`...) |
| `CLOUDFLARE_ACCOUNT_ID` | optionnel ⚪ | `""` | Account ID 32 caractères |
| `CLOUDFLARE_API_TOKEN` | optionnel ⚪ | `""` | Token Cloudflare avec droit D1 + KV |
| `CLOUDFLARE_D1_ID` | optionnel ⚪ | `""` | UUID de la base D1 |
| `CLOUDFLARE_KV_ID` | optionnel ⚪ | `""` | ID du namespace KV |
| `TAVILY_API_KEY` | optionnel ⚪ | `""` | Clé de recherche Tavily AI |
| `ALLRATESTODAY_API_KEY` | optionnel ⚪ | `""` | Clé or/fiat live |
| `GITHUB_TOKEN` | optionnel ⚪ | `""` | Token perso GitHub (limites) |
| `SPOTIFY_CLIENT_ID` | optionnel ⚪ | `""` | Spotify Client ID |
| `SPOTIFY_CLIENT_SECRET` | optionnel ⚪ | `""` | Spotify Client Secret |
| `E2B_API_KEY` | optionnel ⚪ | `""` | Sandbox cloud E2B (sinon : local) |
| `E2B_TIMEOUT_SEC` | optionnel ⚪ | `30` | Plafond E2B en secondes (5–120) |
| `ENABLE_FINANCIAL_SYNC` | optionnel ⚪ | `1` | Sync cours en fond (`0` = off, économise le quota KV) |

---

## Installation pas à pas

### 1. Cloner le code
```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
```

### 2. Environnement virtuel Python
```bash
python3 -m venv venv
# Linux / macOS :
source venv/bin/activate
# Windows :
venv\Scripts\activate
```

### 3. Installer les dépendances
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Config
```bash
cp .env.example .env
nano .env   # collez les clés du guide
```

### 5. Lancer le bot
```bash
python bot.py
```
Après connexion à Telegram le bot fixe ses commandes et affiche le prêt en console.

---

## Déploiement cloud

### Railway :
1. Fork ou push du repo vers votre GitHub.
2. Ouvrez le panel [Railway.app](https://railway.app), **New Project > Deploy from GitHub repo**.
3. Choisissez le repo.
4. Dans **Variables** ajoutez celles du `.env`.
5. Grâce à `nixpacks.toml` + `railway.json`, Railway configure Python 3.12 et `ffmpeg` tout seul et démarre.

### Linux avec Systemd :
Créez `/etc/systemd/system/prometheus.service` :
```ini
[Unit]
Description=Prometheus Telegram Super Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/path/to/prometheusopenbot
ExecStart=/path/to/prometheusopenbot/venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Activez et démarrez :
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
```

---

## Matrice des outils

~**90 outils enregistrés**, chacun avec un boulot clair. Supprimés (morts/doublons/théâtre) : `darkweb_search`, `internal_resilient_fallback_search`, `autonomous_system_health_check`, `bot_rate_guard`, `bot_output_compactor`, `bot_prompt_token_saver`, `bot_alias_resolver`, `bot_d1_remember`, `bot_d1_recall`.

1. **📊 Finance (`src/tools/financial/`) :**
   - Crypto live de Binance et Nobitex (`get_price`, `get_crypto_overview`).
   - Or/pièces live et prime (`get_gold_and_coin_price`).
   - Tether, USD, EUR, AED et crosses forex (`get_dollar_price`, `get_fiat_overview`, `get_global_forex_rates`).

2. **🌐 Web et réseau (`src/tools/web_network/`) :**
   - Recherche maligne : Tavily AI + moteurs (`tavily_search`, `web_search`, `deep_search_and_read`).
   - Actus live (`live_news`).
   - Produits/prix Digikala (`digikala_search`).
   - Réseau : `check_website_status`, `resolve_dns`, `check_ssl_certificate`, `get_ip_info`.
   - Météo avec humidité et vent (`get_weather`).

3. **🎵 Média et audio (`src/tools/media/`) :**
   - Musique en 320kbps original avec tags et pochette (`download_music_track`).
   - Paroles et `.lrc` synchros (`get_song_lyrics`).
   - Voix/audio en texte avec Whisper (`transcribe_audio_tool`).
   - QR (`generate_qr_code_tool`).
   - Longs articles via Telegraph Instant View (`publish_telegraph_article`).

4. **🔬 Science et général (`src/tools/scientific/`) :**
   - Calculatrice avancée (`calculate_math_expression`).
   - Stats (`statistics_summary`).
   - Heure/calendrier officiel (`get_current_datetime_info`).
   - Convertisseur d'unités et hashs (`convert_units`, `generate_hash_digest`, ...).

5. **🛡️ Système et admin (`src/tools/admin/` et `src/tools/system/`) :**
   - Python en sandbox pour le super-admin (`execute_python_code`).
   - Exécution cloud isolée avec E2B (`e2b_run_code`, `e2b_run_command`) ; sans clé : local.
   - Télémétrie (`admin_system_diagnostics`).
   - Ban/mute global en D1 (`ban_user_tool`, `mute_user_tool`).
   - Groupes et sortie d'urgence (`list_joined_groups_tool`, `leave_group_by_admin_tool`).

6. **🐙 GitHub (`src/tools/github/`) :**
   - Chercher repos/issues/commits/releases et analyse.

---

## Modèle de sécurité

- **Masquage auto des secrets :** sorties et logs passent les filtres de clés + regex ; le sensible devient `[SECRET]`, les tokens n'atteignent jamais les chats.
- **PV vs groupes :** les commandes de gestion en privé sont pour la seule identité `ADMIN_ID`.
- **Anti prompt-injection :** logique en Python + prompt système contre changement de rôle et jailbreaks.

---

## Tests

Avant de déployer, contrôle des modules et outils :

```bash
# audit registre + outils offline
python tests/test_master.py

# éval multi + stress
python tests/run_test_battery.py

# sandbox E2B (sans clé/paquet saute le live)
python tests/test_e2b.py
```

---

## Licence et contributions

Projet open-source : architecture d'agents propre et scalable pour la communauté. Rapports et pull requests bienvenus.
