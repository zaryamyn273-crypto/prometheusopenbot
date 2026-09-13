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

## Tools Matrix & Telegram Commands

### 1. Telegram Slash Commands:
* `/del <count>` or `/purge <count>`: Bulk delete recent bot messages or delete replied-to messages.
* `/railway [status|redeploy|vars]`: Monitor Railway services, trigger instant container redeploys, or inspect environment variables.
* `/sh <linux command>`: Execute authenticated shell commands with directory persistence and log upload.
* `/remind <time> <text>` or `/schedule`: Schedule tasks, recurring cron jobs, or reminders with timezone intelligence.
* `/schedules`: List all active scheduled tasks for current chat.
* `/cancel_schedule <id>`: Cancel a scheduled task by numeric ID.
* `/timezone` or `/tz`: View or set local timezone.
* `/whois`: Extract numeric user ID, username, and identity metadata.
* `/admin`: Master Admin glass control dashboard.
* `/ban` and `/unban`: Manage user blacklist across D1 and RAM.

### 2. Autonomous Agent Tools:
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
