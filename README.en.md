# Prometheus — Multi-Modal, Agentic & Hardened Telegram Assistant
> An agentic assistant connected to modern language models, equipped with a real-time matrix of ~90 tools (finance, web search, media, high-res vision, voice STT, damaged barcode reconstruction, secure file inspection, and sandbox execution). Prometheus never hallucinates; it reasons independently, calls the verified tool, and delivers referenced facts.

[![CI](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/zaryamyn273-crypto/prometheusopenbot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Security Hardened](https://img.shields.io/badge/security-hardened-green.svg)](#security-and-hardening)

<p align="center">
  <a href="README.md">🇮🇷 فارسی</a> ·
  <a href="README.en.md">🇬🇧 English</a> ·
  <a href="README.ru.md">🇷🇺 Русский</a> ·
  <a href="README.es.md">🇪🇸 Español</a> ·
  <a href="README.fr.md">🇫🇷 Français</a>
</p>

---

## 📖 Table of Contents
- [Key Features & Recent Advancements](#key-features--recent-advancements)
- [Quickstart & Configuration](#quickstart--configuration)
- [Pipeline Architecture](#pipeline-architecture)
- [Tools Matrix](#tools-matrix)
- [Security and Hardening](#security-and-hardening)
- [Adversarial Testing & Penetration Suite](#adversarial-testing--penetration-suite)
- [Documentation & Guides](#documentation--guides)

---

## Key Features & Recent Advancements

* 🧠 **Isolated 30-Message RAM Buffer per Group & On-Demand Context:**
  - Dedicated, isolated rolling window of **up to 30 last messages per group in RAM** with zero cross-group context leaks or pollution.
  - Context is injected into the LLM prompt **strictly on demand** (only when explicitly requested by the user or when replying to a message). Direct standalone queries execute in zero-history mode for maximum speed and token efficiency.
* 🇮🇷 **100% Persian Language Accuracy & Zero Arabic False Positives:**
  - Overhauled language detection (`detect_lang`) providing absolute Persian priority for shared-alphabet messages.
  - Completely eliminates erroneous Arabic language switching on short Persian sentences (such as "who are you" or "write a story").
* 🎯 **Strict Direct-Question Scoping & Sharp Persona (Sarcastic & Witty):**
  - Strict system mandate to answer exclusively what is asked in the user's immediate prompt without unsolicited preachiness, rambling, or lectures.
  - Crisp, professional, concise, and technical tone with a touch of intelligent, dry wit and subtle sarcasm.
* ⚡ **Real-Time RAM & Cloudflare D1 Sync for Bans & Directives:**
  - Instant synchronization between sub-microsecond in-memory hashed sets and Cloudflare D1 for banned users and admin directives (`manage_admin_memory`).
* 🔍 **Sub-Second Speculative Web Search (<1.2s):**
  - Concurrent speculative race across Tavily AI, Bing, Wikipedia, and DuckDuckGo Instant.
  - Automatic circuit breaker for Tavily rate-limits to eliminate 429 delays and timeouts.
* 🏷️ **Advanced Barcode & Damaged Barcode Reconstruction Engine:**
  - 1D linear barcodes (Code-128, EAN-13, Code-39) and QR codes with **Level H 30% error correction**.
  - **Algebraic Damaged Barcode Reconstruction:** Resolves scratched or missing digits via Luhn Mod-10 parity recovery, regenerating clean scannable barcodes.
* 🎙️ **Multimodal Audio & High-Definition Vision:**
  - Fast Speech-to-Text (STT) powered by multimodal LLMs, transcribing voice notes and audio without third-party local overhead.
  - 2048px high-resolution vision engine handling both standard compressed Telegram photos and uncompressed photo documents.
* 🛡️ **Live Group Telemetry & Airtight Governance:**
  - Real-time parallel group status monitoring (`list_joined_groups_tool`) tracking live member count, bot permission status (Admin vs Member), and valid invite links.
  - **100% Silent Security Gate:** Silently blocks unauthorized groups until the Master Admin explicitly approves them via interactive buttons in private chat.
* ⚡ **Instant Numeric User ID & Identity Extraction (`whois` / `getid`):**
  - Sub-10ms user identity lookup via replies ("id", "whois", "آیدی") or forwarded channel messages.
* 🔒 **Enterprise-Grade Defense-in-Depth:**
  - Three-layer anti-jailbreak shield with NFKC character normalization and zero-width character stripping.
  - Full hop-by-hop redirect SSRF guard blocking private IP ranges and cloud metadata endpoints (`169.254.169.254`).
  - AST Python code analyzer and automated secret scrubber masking API keys and bot tokens with `[SECRET]`.

---

## Quickstart & Configuration

Only **3 environment variables** are required to boot (all other services have automatic fallbacks):

```bash
# 1. Clone repository
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot

# 2. Configure environment
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN, ADMIN_ID, and ROUTER_API_KEY in .env

# 3. Install dependencies and start
pip install -r requirements.txt
python bot.py

# Or launch with Docker:
docker compose up -d --build
```

> **Zero Secrets Policy:** Zero tokens, API keys, or credentials are committed to Git. All credentials are supplied strictly via environment variables at runtime.

---

## Pipeline Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                      User on Telegram                       │
│        (Text, Voice Note, Image, Reply, Forward)            │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 Telegram Dispatcher Engine                  │
│   • Admin numeric ID verification                           │
│   • Pre-LLM anti-jailbreak & NFKC sanitization              │
│   • Sub-millisecond fast-turn triage (Time, Market, Ping)   │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             On-Demand Isolated Memory Tier                  │
│  • Strict 30-message isolated RAM buffer per group          │
│  • On-demand context injection (reply or explicit request)  │
│  • Cloudflare D1: Serverless SQL database with FTS5 search  │
│  • Live synchronization for bans & admin directives         │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│             Autonomous LLM Multi-Step Reasoner              │
│     (Parallel multi-tool calling, reasoning, formatting)    │
│     • Strict Persian language fidelity, concise persona     │
│     • Absolute direct-question scoping without bloat        │
└──────────────────────────────┬──────────────────────────────┘
                                │ (Parallel Async Tool Exec)
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Tool Matrix (~90 Verified Tools)              │
│  • Finance (Binance, Nobitex, Gold, Forex, Tether)          │
│  • Web & Network (Speculative Search, DNS, Web Scraper)     │
│  • Media (Damaged Barcode Recovery, QR Level-H, MP3 320k)   │
│  • System & Docs (E2B Sandbox, Telegram ID, PDF/Doc Reader) │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram HTML & Shield Formatter              │
│  • Automatic secret masking with [SECRET] pattern           │
│  • Telegram 4096-character chunking & HTML fallback         │
└──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                   Delivery to User Message                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Tools Matrix

| Category | Highlighted Tools | Capabilities |
| :--- | :--- | :--- |
| **Media & Barcode** | `generate_barcode_tool`<br>`reconstruct_damaged_barcode_tool`<br>`download_music_track`<br>`transcribe_audio_tool` | 1D barcode & Level-H QR generation, mathematical repair of scratched barcodes, 320kbps MP3 retrieval, high-accuracy speech-to-text. |
| **Web & Network** | `web_search`<br>`fetch_webpage_content`<br>`check_website_status`<br>`resolve_dns` | Sub-1.2s concurrent search, ad-stripped page extraction, SSRF-guarded ping/status diagnostics, DNS-over-HTTPS. |
| **Financial Markets** | `get_price`<br>`get_crypto_overview`<br>`get_gold_and_coin_price`<br>`get_fiat_overview` | Sub-50ms crypto, gold, coin, and foreign exchange rates with distributed fallback architecture. |
| **System & Admin** | `extract_user_id_tool`<br>`list_joined_groups_tool`<br>`ban_user_tool`<br>`manage_admin_memory` | Instant numeric ID extraction, live group auditing, user ban management, admin memory sync across D1 and RAM. |
| **Documents & Math** | `read_document_file`<br>`calculate_math_expression`<br>`convert_units` | Sandboxed extraction of PDF, DOCX, and XLSX files, arbitrary precision arithmetic, and scientific unit conversion. |

---

## Security and Hardening

1. **Hop-by-Hop Redirect SSRF Defense (`src/utils/net_guard.py`):**
   - Validates resolved DNS IP addresses at every individual redirect hop (HTTP 301/302/307/308).
   - Firmly blocks private IP subnets, loopbacks, link-local ranges, and cloud metadata endpoints (`169.254.169.254`).
2. **Three-Layer Anti-Jailbreak Guard (`src/core/guard.py`):**
   - Unicode NFKC normalization and zero-width character stripping before pattern matching.
   - Comprehensive detection of override prompts, safety boundary bypasses, and roleplay hijacking.
   - Fixed `IMMUNITY_BLOCK` enforcing that all user inputs and tool responses are treated strictly as untrusted data.
3. **Automated Secret Scrubbing (`src/core/security.py`):**
   - Regex-based masking for Telegram bot tokens, OpenAI/DeepSeek `sk-` keys, GitHub PATs, and authorization headers.
4. **AST Code Sandbox:**
   - Static abstract syntax tree verification blocking dangerous reflection attributes (`__mro__`, `__subclasses__`, `__globals__`) and system calls.

---

## Adversarial Testing & Penetration Suite

Run the automated test suite locally:

```bash
# Run the complete adversarial anti-jailbreak, SSRF, and sandbox test suite:
python tests/test_adversarial.py

# Run offline language detection and Persian/Arabic boundary verification:
python tests/test_detect_lang.py

# Run multi-dimensional stress testing:
python tests/run_test_battery.py

# Test language detection and internationalization:
python tests/test_i18n.py

# Test daily quota and rate limiter enforcement:
python tests/test_daily_limit.py
```

---

## Documentation & Guides

* 🔑 [Complete Key Configuration Guide (Persian)](docs/setup/keys.fa.md)
* 🌐 [Complete Key Configuration Guide (English)](docs/setup/keys.md)
* 🏗️ [Architecture & Memory Tiers](docs/architecture/overview.md)
* 🛠️ [Tool Matrix Catalog](docs/architecture/tooling.md)
* 🛡️ [Security Policy & Vulnerability Reporting](SECURITY.md)

---

## License and Contributing

Prometheus is open-source software under standard licensing. Contributions, issues, and pull requests are welcomed!
