# Security Policy — Prometheus OpenBot

> Plain-language version: this bot runs AI-generated code, scrapes the web,
> and lives on your server. Below is exactly what protects you, what does
> NOT protect you, and how to report a hole.

## Supported versions

| Version | Supported |
| ------- | --------- |
| `main` (latest) | ✅ |
| Older commits / forks | ❌ (update first, then report) |

## Threat model

### 1. Remote code execution via AI-generated code — CONTAINED
- Python code the model writes **only ever runs inside the E2B cloud
  sandbox** (`e2b_run_code`, `execute_python_code`). There is **no local
  fallback**: without `E2B_API_KEY` the tool answers DISABLED instead of
  executing anything on the host. A local Python "sandbox" without
  cgroups/containers is not a sandbox — so this project doesn't have one.
- Static gates run before any execution, on both paths:
  - AST validator (`src/core/security.py`): blocks `import`, `eval`,
    `exec`, `open`, `getattr/setattr`, dunder attribute chains.
  - Destructive-shell patterns (`rm -rf /`, `mkfs`, `dd … of=/dev/…`,
    fork-bombs, shutdown/reboot, …) are **never executed, even on direct
    admin order**.
  - Code mentioning secrets (`.env`, `*_TOKEN`, `*_API_KEY`, `cloudflare`)
    is refused before dispatch.
- `/sh` (raw host shell) is reachable **only** by the numeric Telegram admin
  typing it themselves. The model has no tool that reaches the host shell.

### 2. Indirect prompt injection via web content — MITIGATED (best-effort)
Web pages, lyrics, search snippets and READMEs are **untrusted input** and
end up in the model's context. Defenses, in order:
1. **Authority never comes from text.** Admin-only tools check the numeric
   Telegram `caller_id` against `ADMIN_ID` in Python code — never a name,
   role-play or "ignore previous instructions" found in a message.
2. **Jailbreak guard** in the system prompt + AST validator for code tools.
3. **Secret masking** (`sanitize_output`): known keys and key-shaped patterns
   (`ghp_…`, `tvly-…`, `e2b_…`, `sk-…`, bot tokens) are replaced with
   `[SECRET]` before anything reaches a chat.
4. **Residual risk (honest):** prompt-injection defense is probabilistic, not
   cryptographic. Treat model output as untrusted; keep `ADMIN_ID` secret and
   never paste untrusted text into admin-only commands.

### 3. Secret leakage — MASKED
- All tool outputs and logs pass the sanitizer before delivery.
- Shell/`/sh` output in groups is masked; full output only in admin PV.
- Never commit `.env` (git-ignored). Rotate any key that touched a chat.

### 4. SSRF & local file access — CONSTRAINED
- URL fetchers match the **parsed hostname only** against private-range
  blocklists (`127/8`, `10/8`, `172.16/12`, `192.168/16`, `169.254/16`,
  `*.internal/.local`, cloud metadata hosts).
- Local audio reads are restricted to `/tmp`. Document reads refuse
  `bot.py`, `.env`, `config.py`, `*.pem/*.key`, `.git`, and anything with
  `token/secret/private_key` in the path.

### 5. Telegram-layer abuse — GATED
- Banned users get radio silence via a pre-handler gatekeeper; muted users
  are archived but never answered.
- Per-user rate limiting; destructive group actions require the numeric admin.

### 6. Cloud credential scope (your job, 2 minutes)
- Cloudflare API token: least privilege — only **D1 edit + KV edit** on the
  two resources the bot uses.
- GitHub token (optional): `public_repo`, nothing more.
- E2B key (optional): keep it out of chats; it can spend your E2B balance.

## Reporting a vulnerability (Responsible Disclosure)

1. **Do NOT open a public issue** for security holes.
2. Use **GitHub → Security → Report a vulnerability** (private vulnerability
   reporting) on this repo, or contact a maintainer privately.
3. Include: affected commit, repro steps (redacted keys!), impact assessment.
4. We aim to acknowledge within **72 hours** and ship a fix before any
   public disclosure. Please give us that window (90 days max, then
   coordinated disclosure).

## Security checklist for operators

- [ ] `.env` never committed, never pasted anywhere except Railway Variables.
- [ ] `ADMIN_ID` is your numeric ID (via @userinfobot), privacy mode OFF via BotFather `/setprivacy` → Disable (groups only).
- [ ] Cloudflare/GitHub tokens are least-privilege (see §6).
- [ ] You understand `/sh` runs raw shell as the deploy user — use Docker (see `docs/setup/docker.md`).
