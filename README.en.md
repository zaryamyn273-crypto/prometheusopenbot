# Prometheus — Multi-Modal, Agentic & Hardened Telegram Assistant
> An advanced agentic assistant connected to modern frontier LLMs, equipped with a real-time matrix of ~90 tools (finance, web search, media, high-res vision, voice STT, international task scheduling, deep OSINT reconnaissance, GitHub account automation, Railway cloud management, damaged barcode reconstruction, secure file inspection, and sandbox execution). Prometheus never hallucinates; it reasons independently, calls the verified tool, and delivers referenced facts.

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

* 🗑️ **Bulk Message Purge & Intelligent Chat Cleanup:**
  - Rapid bulk deletion of bot messages via `/purge <count>`, `/del <count>`, or `/clean <count>`.
  - Full natural language understanding for admin cleanup prompts ("delete your last 10 messages", "پاک کن پیام‌هات رو").
  - Synchronous atomic deletion across Telegram using batching, Cloudflare D1 message persistence, and in-memory RAM buffers with ephemeral self-deleting confirmations.
* 🚂 **Railway Cloud Infrastructure & Service Manager:**
  - Direct integration with Railway GraphQL API authenticated via environment variables (zero secrets stored in git).
  - Commands and agent tools (`/railway status`, `/railway redeploy [service]`, `/railway vars`) providing real-time container health metrics, deployment tracking, and instant service redeploys directly from Telegram.
  - **Hardened Linux Shell (`/sh`):** Persistent working directory tracking across commands (`cd`), 35-second execution timeout, pre-authenticated environment, and automatic `.log` file upload when output exceeds Telegram limits.
* 🕵️‍♂️ **Deep OSINT Person Reconnaissance & Digital Footprint Dossier:**
  - Specialized `osint_person_dossier` tool executing parallel reconnaissance across GitHub, Keybase (cryptographic identities & PGP proofs), Telegram, Reddit, HackerNews, Gravatar, and advanced web dorking.
  - Footprint visibility assessment (Low / Moderate / High Visibility) synthesizing comprehensive profiles of public exposure.
* 🐙 **GitHub Account Automation & Dev Tools:**
  - Direct repository creation for public or private repos (`github_create_repository`).
  - Automated file commits and branch updates (`github_create_or_update_file`).
  - Arch Linux and AUR packaging generator (`github_generate_pkgbuild`).
  - Modern C++20 build configuration generator (`github_generate_cmake`).
  - Multi-faceted GitHub search engine with technical Persian-to-English developer keyword expansion.
* 🏷️ **GS1 & Multi-Wildcard Damaged Barcode Reconstruction Engine:**
  - Official GS1 country prefix table (identifying 626 Iran, Germany, USA/Canada, France, Japan, etc.).
  - Multi-variable algebraic Modulo-10 and Modulo-11 parity solvers for barcodes with multiple missing or scratched digits (`??`) across EAN-13, EAN-8, UPC-A, and ISBN-10 standards.
  - Re-generates pristine, scan-ready vector barcodes with complete mathematical checksum verification.
* 🌍 **Multilingual & Timezone-Aware Distributed Task Scheduler (`scheduler`):**
  - Persistent scheduling of reminders, recurring cron jobs, and automated alerts backed by Cloudflare D1 SQL.
  - **Dynamic Timezone Inference:** Automatically resolves the user's country and timezone based on their language and locale (Persian ➔ `Asia/Tehran`, English ➔ `UTC`, Arabic ➔ `Asia/Dubai`, German ➔ `Europe/Berlin`, etc.).
  - **Natural Timezone Recognition:** Extracts arbitrary city/timezones directly from user text ("at 14:00 London time", "tomorrow at 9 am est", "at 18:00 UTC").
* 🚪 **Strict Group Authorization Gate (Zero Auto-Approval & Zero Auto-Leave):**
  - When invited to any group by non-admins, the bot enters a strict `pending` status.
  - **Never Auto-Approves, Never Auto-Leaves:** Remains 100% silent until the Master Admin explicitly approves or rejects via private inline buttons.
* 🛡️ **Zero Cross-Group Collision & Cloudflare Quota Shield:**
  - Per-chat isolated display-name indexing (`_CHAT_DISPLAY_NAMES`) preventing identity collisions.
  - Debounced Write-Behind Coalescer (3.0s window): multi-row batch inserts **reduce Cloudflare D1 calls by >95%**, protecting against rate limits and 429 errors.
  - Enriched 23-column message schemas with isolated 30-message rolling RAM buffers per group.
* 🇮🇷 **100% Persian Language Accuracy & Sarcastic Persona:**
  - Eliminates erroneous Arabic language detection on Persian prompts.
  - Crisp, technical, concise, and direct responses with a touch of intelligent, dry wit and subtle sarcasm.
* ☁️ **E2B Cloud Code Sandbox (Zero-Leak Security):**
  - Isolated Python and shell execution in ephemeral cloud sandboxes with zero local server RCE risk.

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

# 3. Install and run
pip install -r requirements.txt
python bot.py

# Or deploy with Docker:
docker compose up -d --build
```

> **Zero Secrets Guarantee:** No credentials or API keys exist in git history or source code; all variables are loaded dynamically at runtime.

---

## Telegram Commands Matrix

Prometheus provides an extensive command ecosystem. To prevent cross-bot collision and noise, **in supergroups commands require the `_prometheus` suffix or a bot mention** (e.g., `/help_prometheus` or `/del_prometheus 10`). In direct private messages (PV), both standard and suffixed commands execute identically.

### 1. Core & General Commands
* **`/start`**
  - **Description:** Initializes personal interaction, introduces capabilities, verifies permissions, and loads session state.
  - **Permission:** Public (All Users).
* **`/help`**
  - **Description:** Multilingual interactive guide detailing available features, tools, group etiquette, and usage syntax.
  - **Permission:** Public.
* **`/tools` (or `/tools_prometheus`)**
  - **Description:** Displays the live categorized catalog of connected agent tools (web search, vision, OSINT, financial tables, file generation, etc.).
  - **Permission:** Public.
* **`/clear` (or `/clear_prometheus`)**
  - **Description:** Resets the active rolling conversation window in RAM for the current chat, initiating a pristine zero-context session.
  - **Permission:** Public.
* **`/id` or `/getid` (or `/id_prometheus`)**
  - **Description:** Extracts numeric identifiers (`user_id` / `chat_id`), username, and chat metadata of the sender or replied-to message.
  - **Permission:** Public.

### 2. Live Intelligence, Finance & Media
* **`/search <query>`**
  - **Description:** Triggers a sub-second speculative web search race across Tavily AI, Bing, and DuckDuckGo, synthesizing factual, cited results.
  - **Example:** `/search quantum computing breakthrough 2026`
  - **Permission:** Public.
* **`/crypto [symbol]`**
  - **Description:** Fetches real-time cryptocurrency rates (BTC, ETH, USDT, TON, SOL) with 24-hour price change percentage.
  - **Example:** `/crypto btc` or `/crypto` (for market overview).
  - **Permission:** Public.
* **`/gold`**
  - **Description:** Displays live gold spot prices (18K, melted gold), sovereign coins, and international bullion rates.
  - **Permission:** Public.
* **`/weather <city>`**
  - **Description:** Retrieves real-time meteorological conditions, temperature, humidity, wind speed, and atmospheric forecast for any city.
  - **Example:** `/weather Tokyo` or `/weather London`
  - **Permission:** Public.
* **`/calc <expression>`**
  - **Description:** High-precision algebraic and scientific calculator supporting trigonometry, percentages, and factorials without LLM arithmetic errors.
  - **Example:** `/calc (1450 * 0.18) + sqrt(256)`
  - **Permission:** Public.
* **`/music <track / artist>`**
  - **Description:** Searches and downloads studio-grade 320kbps audio files accompanied by synchronized `.lrc` lyric files.
  - **Example:** `/music Hans Zimmer Time`
  - **Permission:** Public.

### 3. International Task Scheduler & Timezone
* **`/remind <time> <message>` (or `/schedule`)**
  - **Description:** Schedules tasks, recurring cron jobs, or reminders with persistent Cloudflare D1 SQL storage (fully resilient against restarts).
  - **Examples:**
    - `/remind 15m Check oven`
    - `/remind tomorrow at 5 pm Dubai time Project sync`
    - `/remind at 14:00 London time Team meeting`
    - `/remind */30 * * * * System heartbeat check`
  - **Permission:** Public.
* **`/schedules`**
  - **Description:** Lists all active scheduled tasks for the current chat along with task ID, recurrence type, and next execution timestamp.
  - **Permission:** Public.
* **`/cancel_schedule <id>`**
  - **Description:** Cancels and purges a scheduled task by its numeric ID (`/cancel_schedule 4`).
  - **Permission:** Public (Task owner or Admin).
* **`/timezone <city/zone>` (or `/tz`)**
  - **Description:** Views or updates user local timezone preference for accurate scheduling (`/tz London` or `/tz America/New_York`).
  - **Permission:** Public.

### 4. Message Cleanup & Bulk Purge
* **`/del` (Reply Mode)**
  - **Description:** Immediately deletes the specific replied-to message.
  - **Permission:** Master Admin and Group Administrators.
* **`/purge <count>` (or `/del <count>`, `/clean <count>`)**
  - **Description:** Rapidly purges the last N messages sent by the bot (1 to 100) with atomic synchronization across Telegram API, Cloudflare D1, and RAM buffer, accompanied by a 4-second self-destructing confirmation notice.
  - **Example:** `/purge 10` (Also responds to natural language: "delete your last 10 messages").
  - **Permission:** Master Admin and Group Administrators.

### 5. Railway Cloud Infrastructure Management
* **`/railway status`**
  - **Description:** Real-time infrastructure telemetry displaying project status, environment (`production`), active services (`prometheusopenbot`, `9router`), and deployment states (SUCCESS / BUILDING / CRASHED).
  - **Permission:** Master Admin Only.
* **`/railway redeploy [service]`**
  - **Description:** Triggers an immediate zero-downtime container rebuild and redeployment on Railway via GraphQL API without opening the web dashboard.
  - **Example:** `/railway redeploy prometheusopenbot`
  - **Permission:** Master Admin Only.
* **`/railway vars [service]`**
  - **Description:** Inspects deployed environment variables with strict zero-leak masking for tokens, passwords, and sensitive keys.
  - **Permission:** Master Admin Only.

### 6. Linux Terminal Shell & Cloud Sandboxes
* **`/sh <command>` (or `/bash`)**
  - **Description:** Hardened server terminal shell with working directory persistence (`cd`), 35-second timeout, pre-authenticated Railway/GitHub credentials, and automatic document upload (`shell_output.log`) for large outputs exceeding 3500 characters.
  - **Example:** `/sh uname -a && free -m` or `/sh cd src && ls -la`
  - **Permission:** Master Admin Only (Destructive commands remain permanently blocked).
* **`/e2b <code>`**
  - **Description:** Executes Python or JavaScript inside isolated cloud micro-containers powered by E2B with zero host RCE risk.
  - **Permission:** Master Admin Only.
* **`/e2bsh <command>`**
  - **Description:** Runs bash commands inside the remote E2B sandbox environment.
  - **Permission:** Master Admin Only.
* **`/e2bstatus`**
  - **Description:** Reports the health, connectivity, and token validity of the E2B cloud client.
  - **Permission:** Master Admin Only.
* **`/set_e2b <api_key>`**
  - **Description:** Sets or hot-swaps the runtime E2B API key in the admin session.
  - **Permission:** Master Admin Only.
* **`/set_github <token>`**
  - **Description:** Sets or updates the personal GitHub token for automated repository creation and file commits.
  - **Permission:** Master Admin Only.

### 7. User & Quota Administration
* **`/limit`**
  - **Description:** Displays the user's daily quota consumption and remaining AI requests (default: 40 AI turns per day, resetting at 00:00 UTC).
  - **Permission:** Public (Master Admin has unlimited quota).
* **`/setquota <user_id> <limit>`**
  - **Description:** Adjusts or overrides a specific user's daily message allowance.
  - **Example:** `/setquota 987654321 150`
  - **Permission:** Master Admin Only.
* **`/resetquota <user_id>`**
  - **Description:** Resets a user's daily quota counter back to zero consumed.
  - **Permission:** Master Admin Only.
* **`/ban <target>`**
  - **Description:** Blacklists a user across all bot layers and D1 SQL by numeric ID, username, or reply.
  - **Permission:** Master Admin Only.
* **`/unban <target>`**
  - **Description:** Removes a user from the global blacklist and restores access.
  - **Permission:** Master Admin Only.
* **`/mute` & `/unmute`**
  - **Description:** Restricts or restores user speaking permissions within the current group.
  - **Permission:** Master Admin and Group Administrators.
* **`/mutelist`**
  - **Description:** Lists all muted users in the current group.
  - **Permission:** Master Admin and Group Administrators.

### 8. Group & Network Operations
* **`/admin` (or `/panel`)**
  - **Description:** Master Admin control dashboard showing real-time resource telemetry, RAM metrics, D1 connectivity, and system state.
  - **Permission:** Master Admin Only.
* **`/groups`**
  - **Description:** Lists all groups the bot has joined, showing ID, title, and approval status (`active` / `pending`).
  - **Permission:** Master Admin Only.
* **`/leave <group_id>`**
  - **Description:** Directly commands the bot to exit a specific group cleanly without deleting archived history.
  - **Permission:** Master Admin Only.
* **`/bangroup <group_id>`**
  - **Description:** Permanently blacklists a group, commands the bot to depart, and forbids re-invitation.
  - **Permission:** Master Admin Only.
* **`/channels`**
  - **Description:** Lists connected broadcast channels monitored by the bot.
  - **Permission:** Master Admin Only.
* **`/net`**
  - **Description:** Diagnoses server network connectivity and evaluates egress access to global APIs.
  - **Permission:** Master Admin Only.
* **`/remember <key> <value>`**
  - **Description:** Stores a permanent rule, invariant fact, or directive into immutable long-term memory (`manage_admin_memory`).
  - **Permission:** Master Admin Only.
* **`/forget <key>`**
  - **Description:** Deletes a permanent rule or fact from long-term memory.
  - **Permission:** Master Admin Only.

---

## Autonomous Agent Tools Matrix
* `purge_chat_messages_tool`: Clean up recent bot messages in response to admin natural language requests.
* `railway_status_tool` & `railway_redeploy_tool`: Live status and container redeploy management for Railway.
* `osint_person_dossier`: Multi-platform public footprint and identity dossier generation.
* `github_create_repository` & `github_create_or_update_file`: Automated GitHub repo creation and file commits.
* `github_generate_pkgbuild` & `github_generate_cmake`: Packaging scaffolding for Arch Linux and CMake projects.
* `reconstruct_damaged_barcode_tool`: Algebraic Modulo-10/11 barcode repair with GS1 country origin lookup.
* `schedule_task_tool` & `set_user_timezone_tool`: Timezone-aware cron job and task scheduling.
* `download_music_track` & `get_song_lyrics`: Studio 320kbps music download with synced `.lrc` lyrics.

---

## Security and Hardening

1. **Hop-by-Hop Redirect SSRF Guard:** Inspects IP destinations at every redirect step to eliminate DNS rebinding and private IP access (`127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`).
2. **Deterministic Anti-Jailbreak Filter:** Zero-cost NFKC unicode pre-filter blocking DAN, persona hijacks, and prompt injection before model token consumption.
3. **AST-Based Python Sandbox:** Abstract Syntax Tree parsing rejecting dangerous standard library calls (`os`, `sys`, `eval`, `exec`).
4. **Automatic Secret Sanitizer:** Automatic redaction of Telegram tokens, API keys, and database credentials with `[SECRET]`.
5. **Strict Group Authorization Gate:** Enforces radio-silence in unverified groups until explicit Master Admin consent.

---

## Adversarial Testing & Penetration Suite

```bash
# Run database isolation and Cloudflare quota tests
python -m tests.test_database_isolation

# Run international scheduler and timezone tests
python -m tests.test_scheduler

# Run adversarial security and anti-jailbreak suite
python -m tests.test_adversarial

# Run language fidelity and detection tests
python -m tests.test_detect_lang
```

---

## Documentation & Guides

* 📘 [Comprehensive Technical Documentation (docs/README.md)](docs/README.md)
* 🛡️ [Security Architecture & Hardening Specifications (docs/SECURITY.md)](docs/SECURITY.md)
* 🌐 [Cloud & Container Deployment Guide (docs/DEPLOYMENT.md)](docs/DEPLOYMENT.md)
