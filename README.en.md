# Prometheus — a plain Telegram bot that tries to be useful
> A Telegram bot wired to a language model, with a handful of useful tools (fiat/gold/crypto prices, weather, web search, music, files, calculations). Instead of guessing it goes to the tools; if something is broken it says so. No miracles here.

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Table of Contents
- [Overview](#overview)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [API Keys Setup](#api-keys-setup)
  - [1. Telegram Bot Token (TELEGRAM_BOT_TOKEN)](#1-telegram-bot-token-telegram_bot_token)
  - [2. Admin Numeric ID (ADMIN_ID)](#2-admin-numeric-id-admin_id)
  - [3. AI Key and Endpoint (ROUTER_API_KEY and ROUTER_BASE_URL)](#3-ai-key-and-endpoint-router_api_key-and-router_base_url)
  - [4. Cloudflare Account, D1 and KV](#4-cloudflare-account-d1-and-kv)
  - [5. Tavily Web Search Key (TAVILY_API_KEY)](#5-tavily-web-search-key-tavily_api_key)
  - [6. AllRatesToday Rates Key (ALLRATESTODAY_API_KEY)](#6-allratestoday-rates-key-allratestoday_api_key)
  - [7. GitHub Token (GITHUB_TOKEN)](#7-github-token-github_token)
  - [8. Spotify Keys (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)](#8-spotify-keys-spotify_client_id-and-spotify_client_secret)
  - [9. E2B Cloud Sandbox (E2B_API_KEY)](#9-e2b-cloud-sandbox-e2b_api_key)
- [Environment Variables](#environment-variables)
- [Step-by-Step Installation](#step-by-step-installation)
- [Cloud Deployment](#cloud-deployment)
- [Tools Matrix](#tools-matrix)
- [Security Model](#security-model)
- [Testing](#testing)
- [License and Contributing](#license-and-contributing)

---

## Overview

**Prometheus** is an open-source Telegram bot that plugs a language model into real tools. The idea is simple, and it does just that:

- **Don't guess, go look:** anything that needs live data (prices, weather, news, site status) comes straight from a tool, not from model memory. If a tool is down, the bot says it doesn't know. That's it.
- **You don't need a key for everything:** only a Telegram token, an admin ID, and one OpenAI-compatible model key are required. Everything else (Tavily, Cloudflare, GitHub, Spotify, E2B) is optional — without them it still works, just with free fallbacks.
- **It minds its own business in groups:** it only replies when addressed (reply, mention, or the word "Prometheus"). Everything else is silently archived.
- **It doesn't run code locally:** Python runs in the E2B cloud sandbox first (if keyed), otherwise in an isolated local sandbox. Destructive shell never runs, not even on admin order.

---

## Project Structure

The repo is organized in a separated, modular, standard way:

```text
prometheusopenbot/
├── bot.py                     # Main entrypoint: Telegram server + bot bootstrap
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── nixpacks.toml / railway.json # Cloud deploy config (Railway / Nixpacks)
│
├── src/                       # Core package
│   ├── core/                  # Database, AI, HTTP client and config
│   │   ├── ai_service.py      # Unified LLM service, prompts, vision, tools
│   │   ├── config.py          # Env loading, security policy, system prompt
│   │   ├── database.py        # Multi-tier cloud storage (Cloudflare D1 & KV)
│   │   ├── http.py            # Async HTTP session management
│   │   └── security.py        # Command validation, rate limits, intrusion guard
│   ├── tools/                 # ~90 focused tools (each does one thing, extras removed)
│   │   ├── admin/             # Group governance and moderation tools
│   │   ├── database/          # Cloud query/interaction tools
│   │   ├── dev/               # Dev tools: GitHub, Reddit, StackOverflow
│   │   ├── files/             # Doc generation/extraction (PDF, Word, Excel, CSV)
│   │   ├── financial/         # Live crypto, gold, fiat and forex quotes
│   │   ├── github/            # Repo/issue/commit interaction
│   │   ├── internal/          # Memory optimizers, prompt compression, caching
│   │   ├── media/             # Studio music download, metadata, lyrics, voice
│   │   ├── scientific/        # Math, stats and unit conversion
│   │   ├── system/            # Server telemetry, E2B sandbox, safe admin shell
│   │   ├── web_network/       # Live search engines (Tavily, Bing, Brave, Digikala)
│   │   └── registry.py        # Auto tool-schema registration + dispatch
│   ├── ui/                    # In-app Telegram admin panel (inline keyboards)
│   └── utils/                 # Telegram formatting, output cleanup, typography
│
├── tests/                     # Test suites
│   ├── test_master.py         # Full system/tools validation
│   ├── run_test_battery.py    # Bot behavior, DB and stress simulation
│   ├── test_stress.py         # Tool stability under heavy load
│   ├── run_rigorous_tests.py  # Live web/network tool evaluation
│   ├── test_financial_scientific_suite.py # Financial + math tests
│   ├── test_media_files_runner.py        # Docs/media/image processing tests
│   └── test_rigorous_battery.py          # Edge cases and weird inputs
│
└── assets/                    # Static assets and Persian standard fonts
```

---

## How It Works

The bot runs on a modern multi-layer pipeline:

```text
┌─────────────────────────────────────────────────────────────┐
│                      User on Telegram                       │
└──────────────────────────────┬──────────────────────────────┘
                                │ (text, voice, reply, file)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Dispatcher Engine                  │
│        (auth, rate limiting, access analysis)                │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   3-Tier Memory Architecture                │
│  • L1 Cache: ultra-fast local RAM for rates and answers     │
│  • Cloudflare KV: distributed cloud key/value memory        │
│  • Cloudflare D1: SQL database with FTS5 text search        │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             Autonomous LLM Multi-Step Reasoner              │
│     (multi-step reasoning + parallel Function Calls)        │
└──────────────────────────────┬──────────────────────────────┘
                                │ (Parallel Tool Execution)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                  Tool Matrix (~90 tools)                    │
│  • Finance (Binance, Nobitex, gold, coins, Tether, forex)   │
│  • Web & news (Tavily AI, web scrapers, Digikala, weather)  │
│  • Media & audio (320kbps music, Whisper STT, QR, Telegraph)│
│  • Ops & system (Python sandbox, logs, global ban)          │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram HTML & Shield Formatter              │
│     (automatic [SECRET] masking + standard formatting)      │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                     Reply sent to Telegram                  │
└─────────────────────────────────────────────────────────────┘
```

### 1. Parallel Tool Calling
The user message is analyzed first and split into independent intents. If there are several asks in one message (e.g. Bitcoin price, Tehran weather and official time at once), the bot identifies the needed tools and calls them in parallel.

### 2. 3-Tier Storage System
- **Tier 1 (L1 In-Memory Cache):** very fast RAM cache with TTL expiry for live data (fiat/crypto rates).
- **Tier 2 (Cloudflare Workers KV):** distributed cloud key/value memory for sessions, longer-lived cache and dynamic settings.
- **Tier 3 (Cloudflare D1 SQL Database):** serverless relational DB with FTS5 full-text search for complete chat history, logs and member management.

### 3. Admin Command Isolation
Sensitive tools (Python execution, terminal commands, group membership management, global ban) sit behind numeric admin-ID auth (`ADMIN_ID`). No user can reach them via prompt injection or impersonation.

---

## API Keys Setup

To run with full features you need a few keys and IDs. Some are **required** (for first boot), some **optional** (for side tools).

### 1. Telegram Bot Token (TELEGRAM_BOT_TOKEN) — [required 🔴]
- **Use:** the bot's identity for connecting to Telegram servers and sending/receiving messages.
- **How to get it:**
  1. Open [@BotFather](https://t.me/BotFather) on Telegram.
  2. Send `/newbot`.
  3. Pick a display name, then a username (must end in `bot`).
  4. BotFather gives you a token like `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
  5. For groups: run `/setprivacy` in BotFather, pick your bot, set it to `Disable` so it can read group messages.

### 2. Admin Numeric ID (ADMIN_ID) — [required 🔴]
- **Use:** identity of the owner/super-admin for the admin panel, Python execution, user bans and group management.
- **How to get it:**
  1. Open [@userinfobot](https://t.me/userinfobot) or [@JsonDumpBot](https://t.me/JsonDumpBot).
  2. Press start to get your numeric ID (e.g. `123456789`).
  3. Put it in `ADMIN_ID`.

### 3. AI Key and Endpoint (ROUTER_API_KEY and ROUTER_BASE_URL) — [required 🔴]
- **Use:** the bot's brain for reasoning, intent detection and tool calls (Function Calling). Any **OpenAI API**-compatible provider works:
- **Options:**
  - **Official OpenAI:**
    - Go to [platform.openai.com](https://platform.openai.com/api-keys)
    - Create a key (`sk-...`)
    - Set `ROUTER_BASE_URL=https://api.openai.com/v1` and `ROUTER_MODEL=gpt-4o-mini`
  - **OpenRouter (many models in one place):**
    - Go to [openrouter.ai](https://openrouter.ai/keys)
    - Create an API key
    - Set `ROUTER_BASE_URL=https://openrouter.ai/api/v1` and any model (e.g. `google/gemini-flash-1.5`, `openai/gpt-4o-mini`)
  - **DeepSeek:**
    - Go to [platform.deepseek.com](https://platform.deepseek.com/api_keys)
    - Create a key, set `ROUTER_BASE_URL=https://api.deepseek.com/v1`, `ROUTER_MODEL=deepseek-chat`
  - **Groq (very fast):**
    - Go to [console.groq.com](https://console.groq.com/keys)
    - Create a free key, set `ROUTER_BASE_URL=https://api.groq.com/openai/v1`, `ROUTER_MODEL=llama-3.3-70b-versatile`

### 4. Cloudflare Account, D1 and KV — [optional 🟡]
- **Use:** permanent chat history, full-text search over old group messages, ban lists, distributed cloud cache. Without it the bot keeps working on RAM (L1).
- **How to get it free:**
  1. Create an account at [cloudflare.com](https://cloudflare.com).
  2. **Account ID:** open Workers & D1 in the dashboard; the 32-char account ID is on the right column.
  3. **API Token:** *My Profile > API Tokens > Create Token*, pick the *Edit Cloudflare Workers* template.
  4. **D1 database:** *Workers & Pages > D1 SQL Database*, create one (e.g. `prometheus-db`), copy the Database UUID into `CLOUDFLARE_D1_ID`.
  5. **KV namespace:** *Workers & Pages > KV*, create one (e.g. `prometheus-kv`), copy the Namespace ID into `CLOUDFLARE_KV_ID`.

### 5. Tavily Web Search Key (TAVILY_API_KEY) — [optional ⚪]
- **Use:** fast AI search engine for live news, version comparisons, same-day events.
- **How to get it free:**
  1. Go to [tavily.com](https://tavily.com) and sign up (free plan: 1000 searches/month, no card).
  2. Copy your key (starts with `tvly-`) into `TAVILY_API_KEY`.

### 6. AllRatesToday Rates Key (ALLRATESTODAY_API_KEY) — [optional ⚪]
- **Use:** direct live fiat rates (USD, EUR, AED...) and Iranian gold/coin prices.
- **How to get it:**
  1. Go to [allratestoday.com](https://allratestoday.com), sign up, get an `art_live_...` key.
  2. *(Without it the bot falls back to live web scrapers automatically.)*

### 7. GitHub Token (GITHUB_TOKEN) — [optional ⚪]
- **Use:** higher rate limits for the 12 GitHub tools (code/commit/issue/release search).
- **How to get it free:**
  1. Go to [github.com/settings/tokens](https://github.com/settings/tokens).
  2. *Generate new token (classic)*, tick `public_repo`, put the `ghp_...` token in `GITHUB_TOKEN`.

### 8. Spotify Keys (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET) — [optional ⚪]
- **Use:** official high-quality covers and exact metadata for foreign tracks.
- **How to get it free:**
  1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
  2. Create an app, copy `Client ID` and `Client Secret`.
  3. *(Without them the bot uses iTunes API + default metadata.)*

### 9. E2B Cloud Sandbox (E2B_API_KEY) — [optional ⚪]
- **Use:** isolated Python/JavaScript/shell execution in the cloud, zero load on your server. Without it the bot uses the local sandbox.
- **How to get it free:**
  1. Sign up at [e2b.dev](https://e2b.dev).
  2. Get a key from the [E2B dashboard](https://e2b.dev/dashboard?tab=keys) (starts with `e2b_`).
  3. Put it in `E2B_API_KEY`. (Optional: `E2B_TEMPLATE` for a custom template, `E2B_TIMEOUT_SEC` for the run cap.)

---

## Environment Variables

Create a `.env` file in the project root and fill it per the guide above:

| Variable | Type | Default | Use |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | required 🔴 | - | Telegram bot token from BotFather |
| `ADMIN_ID` | required 🔴 | `0` | Numeric Telegram user ID of the super-admin |
| `ROUTER_BASE_URL` | required 🔴 | `https://api.openai.com/v1` | OpenAI-compatible V1 endpoint |
| `ROUTER_API_KEY` | required 🔴 | - | AI model auth key |
| `ROUTER_MODEL` | optional ⚪ | `gpt-4o-mini` | Model name (e.g. `gpt-4o-mini`, `deepseek-chat`) |
| `CLOUDFLARE_ACCOUNT_ID` | optional ⚪ | `""` | 32-char Cloudflare account ID |
| `CLOUDFLARE_API_TOKEN` | optional ⚪ | `""` | Cloudflare token with D1 + KV permission |
| `CLOUDFLARE_D1_ID` | optional ⚪ | `""` | D1 database UUID |
| `CLOUDFLARE_KV_ID` | optional ⚪ | `""` | Workers KV namespace ID |
| `TAVILY_API_KEY` | optional ⚪ | `""` | Tavily AI search key |
| `ALLRATESTODAY_API_KEY` | optional ⚪ | `""` | Live gold/fiat rates key |
| `GITHUB_TOKEN` | optional ⚪ | `""` | GitHub personal token (rate limits) |
| `SPOTIFY_CLIENT_ID` | optional ⚪ | `""` | Spotify client ID |
| `SPOTIFY_CLIENT_SECRET` | optional ⚪ | `""` | Spotify client secret |
| `E2B_API_KEY` | optional ⚪ | `""` | E2B cloud sandbox for isolated code runs (else: local) |
| `E2B_TIMEOUT_SEC` | optional ⚪ | `30` | E2B run cap in seconds (5–120) |
| `ENABLE_FINANCIAL_SYNC` | optional ⚪ | `1` | Background price sync (`0` = off, saves KV quota) |

---

## Step-by-Step Installation

### 1. Clone the source
```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
```

### 2. Create and activate a Python venv
```bash
python3 -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Create and fill the config file
```bash
cp .env.example .env
nano .env   # paste the keys from the guide above
```

### 5. Run the bot
```bash
python bot.py
```
After a successful Telegram connection the bot sets its command list and prints a ready message to the console.

---

## Cloud Deployment

### Railway:
1. Fork or push this repo to your GitHub account.
2. Open the [Railway.app](https://railway.app) dashboard, **New Project > Deploy from GitHub repo**.
3. Pick your repo.
4. In the **Variables** tab, add the `.env` variables.
5. Thanks to `nixpacks.toml` + `railway.json`, Railway auto-configures Python 3.12 and `ffmpeg` and runs the project.

### Linux with Systemd:
Create a service at `/etc/systemd/system/prometheus.service`:
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
Then enable and start it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
```

---

## Tools Matrix

~**90 registered tools**, each with one clear job. Removed for being uncalled/duplicated/theater: `darkweb_search`, `internal_resilient_fallback_search`, `autonomous_system_health_check`, `bot_rate_guard`, `bot_output_compactor`, `bot_prompt_token_saver`, `bot_alias_resolver`, `bot_d1_remember`, `bot_d1_recall`.

1. **📊 Finance (`src/tools/financial/`):**
   - Live crypto prices from Binance and Nobitex (`get_price`, `get_crypto_overview`).
   - Live gold/coin prices (Emami, Bahar Azadi, half/quarter) and bubble (`get_gold_and_coin_price`).
   - Live Tether, USD, EUR, AED and forex crosses (`get_dollar_price`, `get_fiat_overview`, `get_global_forex_rates`).

2. **🌐 Web and network (`src/tools/web_network/`):**
   - Smart web search: Tavily AI + combined engines (`tavily_search`, `web_search`, `deep_search_and_read`).
   - Live news (politics, economy, tech, sports) (`live_news`).
   - Digikala product/price lookup (`digikala_search`).
   - Network tools: `check_website_status`, `resolve_dns`, `check_ssl_certificate`, `get_ip_info`.
   - Weather with humidity and wind (`get_weather`).

3. **🎵 Media and audio (`src/tools/media/`):**
   - Music search/download in original 320kbps quality with tags and cover (`download_music_track`).
   - Lyrics and timed `.lrc` files (`get_song_lyrics`).
   - Voice/audio to text via Whisper AI (`transcribe_audio_tool`).
   - High-quality QR codes (`generate_qr_code_tool`).
   - Long-form publishing via Telegraph Instant View (`publish_telegraph_article`).

4. **🔬 Scientific and general (`src/tools/scientific/`):**
   - Advanced math evaluator (`calculate_math_expression`).
   - Stats summaries (`statistics_summary`).
   - Official time/calendar (`get_current_datetime_info`).
   - Unit conversion and hashing (`convert_units`, `generate_hash_digest`, ...).

5. **🛡️ System and admin (`src/tools/admin/` & `src/tools/system/`):**
   - Sandboxed Python for the super-admin (`execute_python_code`).
   - Isolated cloud runs via E2B (`e2b_run_code`, `e2b_run_command`); local fallback without a key.
   - Server telemetry (`admin_system_diagnostics`).
   - Global ban/mute backed by D1 (`ban_user_tool`, `mute_user_tool`).
   - Group management and emergency leave (`list_joined_groups_tool`, `leave_group_by_admin_tool`).

6. **🐙 GitHub (`src/tools/github/`):**
   - Search repos/issues/commits/releases and repo analysis.

---

## Security Model

- **Automatic secret masking:** tool outputs and logs pass through known-key + regex filters; sensitive values are replaced with `[SECRET]` so tokens never leak into chats.
- **PV vs group separation:** management commands in private chat are only for the `ADMIN_ID` identity.
- **Prompt-injection guard:** bot logic plus system prompt resist role override and jailbreak tricks.

---

## Testing

Before deploying, sanity-check modules and tools:

```bash
# registry + offline tool audit
python tests/test_master.py

# multi-dimensional evaluation + stress
python tests/run_test_battery.py

# E2B sandbox (skips live run without key/package)
python tests/test_e2b.py
```

---

## License and Contributing

Open-source project: a clean, scalable agent architecture for the community. Bug reports and pull requests are welcome.
