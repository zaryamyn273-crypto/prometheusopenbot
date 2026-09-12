# Prometheus — a plain Telegram bot that tries to be useful
> A Telegram bot wired to a language model, with a handful of useful tools (fiat/gold/crypto prices, weather, web search, music, files, calculations). Instead of guessing it goes to the tools; if something is broken it says so. No miracles here.

[![CI](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

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
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Tools](#tools)
- [Security](#security)
- [Testing](#testing)
- [License and Contributing](#license-and-contributing)
- [📚 Full docs](docs/setup/keys.md)

---

## Overview

**Prometheus** is an open-source Telegram bot that plugs a language model into real tools. The idea is simple, and it does just that:

- **Don't guess, go look:** anything that needs live data (prices, weather, news, site status) comes straight from a tool, not from model memory. If a tool is down, the bot says it doesn't know. That's it.
- **You don't need a key for everything:** only a Telegram token, an admin ID, and one OpenAI-compatible model key are required. Everything else (Tavily, Cloudflare, GitHub, Spotify, E2B) is optional — without them it still works, just with free fallbacks.
- **It minds its own business in groups:** it only replies when addressed (reply, mention, or the word "Prometheus"). Everything else is silently archived.
- **No on-server code execution:** AI-written code runs only in the E2B cloud sandbox; without a key the tool is DISABLED (no local fallback by design). Destructive shell never runs, not even on admin order.
- **Not Persian-only:** it detects each user's Telegram language and answers in it (English, Russian, Spanish, French, ...); tool outputs are translated when needed.

---

## Quickstart

Only **3 variables** to boot — everything else is optional:

```bash
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot
cp .env.example .env   # set TELEGRAM_BOT_TOKEN, ADMIN_ID, ROUTER_API_KEY
pip install -r requirements.txt && python bot.py
# or with Docker: docker compose up -d --build
```

Full key guides: [docs/setup/keys.md](docs/setup/keys.md) — deploy: [Railway](docs/setup/railway.md) • [Docker](docs/setup/docker.md)

---

## Architecture

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

- **Tier 0/1 triage:** clock, chatter and market boards answer with zero LLM rounds.
- **Lazy loading:** tool modules load only when needed (~93 fewer modules, ~29% less RSS at import).
- **3-tier memory:** local RAM → cloud KV → D1, with automatic fallback to RAM.
- Details: [docs/architecture/overview.md](docs/architecture/overview.md)

---

## Tools

~**90 tools** in 6 families (finance, web/network, media, science, system/admin, GitHub) + cloud memory. Full matrix: [docs/architecture/tooling.md](docs/architecture/tooling.md)

---

## Security

- AI-written code runs only in the E2B cloud sandbox (no key: DISABLED, no local fallback).
- Secrets masked as `[SECRET]`; admin auth by numeric ID only.
- Full threat model + responsible disclosure: [SECURITY.md](SECURITY.md)

---

## Testing

```bash
python tests/test_master.py       # full audit
python tests/test_i18n.py         # bilingualism (offline)
python tests/test_e2b.py          # sandbox (offline without key)
python tests/run_test_battery.py  # multi-dimensional stress
```
Build + Docker are checked on every push by GitHub Actions (badge above).

---

## License and Contributing

Open-source project: a clean, scalable agent architecture for the community. Bug reports and pull requests are welcome.
