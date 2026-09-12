# Architecture Overview

Single process, async throughout (`python-telegram-bot` long polling).

```
Telegram update
  → gatekeepers (ban/mute/rate-limit/STOP switch)
  → background archive to D1 queue (fire-and-forget)
  → Tier 0/1 triage  ──hit──▶ reply (no AI, minimal modules)
  → Tier 2: prefetch hints + typing loop + ReAct agent (up to 8 tool rounds)
  → media/text delivery (+ caption translation) → reply
```

## 3-tier memory

1. **L1** — in-process RAM cache with TTL + sliding refresh + FIFO cap.
2. **Cloudflare KV** — distributed cache/sessions; quota-aware writes
   (same-value skip, per-key throttle, 429 circuit breaker).
3. **Cloudflare D1** — serverless SQL (FTS5 search) via write-behind batch
   queue; schema migrates with single-statement DDL + warm-boot probe.

Without Cloudflare credentials everything degrades to L1 RAM — no crash.

## Lazy tool loading (only active tools exist at any moment)

- `import src.tools` registers **nothing**. Tool modules import on demand:
  schema filtering loads only matching categories, execution auto-loads the
  owner module, fallbacks resolve lazily.
- `import bot` pulls **no** `ai_service` (PIL), no tool modules: ~93 fewer
  modules, ~29% less RSS at startup (measured).
- Command handlers and the AI branch import their modules function-locally.
- Full cabinet loads only for complex multi-intent turns, stall escalation,
  stress tests, or explicit `ensure_all()`.

## Deterministic fast paths (zero LLM rounds)

- Clock/date, social chatter, market boards: answered by Tier 0/1 triage
  *before* prefetch/typing/AI spin up; non-Persian output gets one cheap
  translation call instead of a reasoning loop.

## Liveness

- `/healthz` (stdlib HTTP, `$PORT`/8080): `200 ok` while the asyncio loop
  heartbeats every 15s, `503 stale` when wedged >90s, `starting` in grace.
  Docker `HEALTHCHECK` + compose healthcheck consume it.
- Startup config is Pydantic-validated (`src/core/settings.py`): bad env
  exits(2) with a clear message instead of crash-looping.

## Repo layout (condensed)

```text
prometheusopenbot/
├── bot.py                     # entrypoint: handlers, triage, delivery, polling
├── requirements.txt           # Python deps (slim: no pydantic-core bloat beyond settings)
├── .env.example               # 3 required vars + documented optionals
├── Dockerfile / docker-compose.yml / nixpacks.toml / railway.json
├── SECURITY.md
├── src/
│   ├── core/                  # config, settings (Pydantic), database (D1/KV/L1),
│   │                          #   ai_service (ReAct loop), http (pooled clients),
│   │                          #   i18n (fa/en chrome + 20 LLM languages), health (/healthz)
│   ├── tools/                 # lazily-loaded tool modules + registry
│   │   ├── financial/ web_network/ media/ scientific/ github/
│   │   ├── system/ (+ e2b_sandbox.py)  admin/  files/  database/  dev/
│   │   ├── internal/          # prefetch + fallback helpers (never shown to model)
│   │   └── registry.py        # lazy loader + smart schema filter + fallbacks
│   ├── ui/                    # Telegram inline keyboards + admin panel texts
│   └── utils/                 # formatter, display names
├── tests/                     # master / battery / stress / rigorous / media /
│                              #   financial / e2b / i18n / lazy suites
└── assets/                    # static assets + Persian TTF font
```
