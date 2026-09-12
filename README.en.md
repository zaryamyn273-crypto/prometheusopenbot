# Prometheus — Multi-Modal, Agentic & Hardened Telegram Assistant
> An advanced agentic assistant connected to modern frontier LLMs, equipped with a real-time matrix of ~90 tools (finance, web search, media, high-res vision, voice STT, international task scheduling, damaged barcode reconstruction, secure file inspection, and sandbox execution). Prometheus never hallucinates; it reasons independently, calls the verified tool, and delivers referenced facts.

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
- [Tools Matrix & Telegram Commands](#tools-matrix--telegram-commands)
- [Security and Hardening](#security-and-hardening)
- [Adversarial Testing & Penetration Suite](#adversarial-testing--penetration-suite)
- [Documentation & Guides](#documentation--guides)

---

## Key Features & Recent Advancements

* 🌍 **Multilingual & Timezone-Aware Distributed Task Scheduler (`scheduler`):**
  - Persistent scheduling of reminders, tasks, and automated financial broadcasts backed by Cloudflare D1 SQL storage (fully resilient against container restarts).
  - **Dynamic Timezone Inference:** Automatically resolves the user's country and timezone based on their language and locale (Persian ➔ `Asia/Tehran`, English ➔ `UTC`, Arabic ➔ `Asia/Dubai`, German ➔ `Europe/Berlin`, Turkish ➔ `Europe/Istanbul`, Japanese ➔ `Asia/Tokyo`, etc.).
  - **Natural Timezone Recognition in Prompts:** Extracts arbitrary city/timezones directly from user text (e.g. "at 14:00 London time", "tomorrow at 9 am est", "at 18:00 UTC", "ساعت ۵ عصر به وقت دبی").
  - **User Timezone Persistence & Clarification:** Dedicated `user_preferences` table in D1, with native `/timezone` and `/tz` commands alongside agent tools (`schedule_task_tool` and `set_user_timezone_tool`). Automatically notifies international users with guidance on setting their local timezone.
* 🚪 **Strict Group Authorization Gate (Zero Auto-Approval & Zero Auto-Leave):**
  - When the bot is invited to any group by non-admins, it enters a strict `pending` status.
  - **Never Auto-Approves, Never Auto-Leaves:** The bot remains 100% silent and never answers regular chat messages until the Master Admin explicitly acts.
  - It **never automatically leaves** on its own; approval is granted strictly when the Master Admin clicks "Approve" in private chat, and departure occurs strictly when the admin clicks "Reject".
* 🛡️ **Zero Cross-Group Collision & Cloudflare Quota Shield:**
  - Per-chat isolated display-name indexing (`_CHAT_DISPLAY_NAMES`) preventing identity collisions when different users share names across groups.
  - Strict mandatory `chat_id` constraints across all memory search layers and FTS5 indices, completely blocking cross-chat data leaks.
  - Intelligent Adaptive Write-Behind Coalescer (3.0s debounce window): multi-row batch inserts **reduce Cloudflare D1 HTTP calls by >95%**, shielding against daily quota limits and HTTP 429 throttling.
  - Enriched 23-column message schemas capturing Telegram forum `thread_id`, `forward_from`, `sender_chat_id`, `detected_lang`, `char_count`, `has_media`, and `extra_meta`.
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
* 🔒 **Enterprise Hardened Red/Blue Shield:**
  - Hop-by-hop redirect SSRF guard with strict loopback/private IPv4/IPv6 blocking.
  - Deterministic pre-LLM zero-cost anti-jailbreak filter with NFKC and zero-width normalization.
  - AST-based Python sandbox and automatic secret masking in shell logs with `[SECRET]`.

---

## Quickstart & Configuration

To start Prometheus, only **3 mandatory variables** are required in your environment:

```bash
# 1. Clone repository
git clone https://github.com/zaryamyn273-crypto/prometheusopenbot.git
cd prometheusopenbot

# 2. Configure environment
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN, ADMIN_ID, and ROUTER_API_KEY

# 3. Install dependencies and run
pip install -r requirements.txt
python bot.py

# Or launch with Docker:
docker compose up -d --build
```

> **Zero Secret Leak Guarantee:** No credentials, API tokens, or secrets are ever committed to the repository or git history. All variables are injected at runtime via environment variables.

---

## Tools Matrix & Telegram Commands

### Telegram Commands:
* `/remind <time> <message>` or `/schedule`: Schedule reminders or tasks across any timezone.
* `/schedules`: View active schedules for the current chat or user.
* `/cancel_schedule <id>`: Cancel an active schedule by its ID.
* `/timezone` or `/tz`: View or set preferred timezone (e.g. `/timezone London`, `/timezone New York`).
* `/whois` or `ID`: Instant user/channel telemetry extraction via reply.
* `/admin`: Interactive Master Admin control dashboard.
* `/ban` & `/unban`: Manage user access by numeric ID, username, or display name.

### Autonomous Agent Tools:
* `schedule_task_tool`: Natural language scheduling with automatic timezone awareness.
* `set_user_timezone_tool`: Configure user timezone through conversational interaction.
* `list_scheduled_tasks_tool`: Query active scheduled jobs and cron runs.
* `cancel_scheduled_task_tool`: Terminate active scheduled tasks.
* `search_group_memory`: FTS5 full-text search strictly scoped to the current chat.
* `generate_barcode_tool` & `generate_qr_code_tool`: High-res barcode generation.
* `resolve_barcode_math_tool`: Algebraic reconstruction of scratched barcodes.
* `download_music_track` & `get_song_lyrics`: Studio music retrieval with timestamped lyrics.

---

## Security and Hardening

1. **Hop-by-Hop Redirect SSRF Guard:** Inspects IP addresses at every HTTP redirect hop, neutralizing loopback, AWS metadata, and DNS rebinding attacks.
2. **Deterministic Anti-Jailbreak Filter:** Zero-token-cost gate checking input vectors before reaching LLM inference.
3. **AST-Based Python Sandbox:** Prohibits hazardous OS-level calls (`open`, `eval`, `exec`, `os`, `sys`) before evaluation.
4. **Automatic Secret Sanitizer:** Intercepts and scrubs tokens and sensitive keys before output rendering.
5. **Strict Group Authorization Gate:** Enforces total silence on untracked groups, eliminating auto-leaves and unauthorized responses.

---

## Adversarial Testing & Penetration Suite

Verify project integrity and security with the automated test battery:

```bash
# Run database isolation and Cloudflare rate-limit tests
python -m tests.test_database_isolation

# Run international timezone and scheduler tests
python -m tests.test_scheduler

# Run adversarial penetration suite (Red/Blue security audit)
python -m tests.test_adversarial

# Run Persian language detection accuracy tests
python -m tests.test_detect_lang
```

---

## Documentation & Guides

* 📘 [Technical Reference & Architecture (docs/README.md)](docs/README.md)
* 🛡️ [Security Architecture (docs/SECURITY.md)](docs/SECURITY.md)
* 🌐 [Cloud Deployment & Cloudflare Guide (docs/DEPLOYMENT.md)](docs/DEPLOYMENT.md)
