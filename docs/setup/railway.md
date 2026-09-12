# Deploy on Railway

Railway is the recommended zero-ops target (`nixpacks.toml` + `railway.json`
are already in the repo).

1. Fork or push this repo to your GitHub account.
2. Railway dashboard → **New Project > Deploy from GitHub repo** → pick it.
3. **Variables** tab → add at minimum (see [keys.md](keys.md) for the rest).
   Values live ONLY in Railway — never commit them to the repo:
   - `TELEGRAM_BOT_TOKEN`
   - `ADMIN_ID`
   - `ROUTER_API_KEY` (+ `ROUTER_BASE_URL`, `ROUTER_MODEL` if not OpenAI)
   - `TAVILY_API_KEYS` (comma-separated; optional but recommended for search)
   - `DAILY_USER_LIMIT` (default `40`; daily AI answers per user, auto-reset)
   - `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` (+ `CLOUDFLARE_D1_ID`,
     `CLOUDFLARE_KV_ID`) for persistent memory — without them the bot still
     runs, on RAM only.
4. Deploy. Nixpacks provisions Python 3.12 + `ffmpeg` automatically.
5. Health: Railway can probe `GET /healthz` on `$PORT` (defaults to 8080).
   The bot answers `200 {"status":"ok"}` while its event loop is alive and
   `503` when wedged — point any uptime monitor at it.

Notes:
- Misconfigured env fails **fast at boot** with a clear bilingual message
  (Pydantic schema in `src/core/settings.py`) instead of crash-looping.
- Market pre-sync writes to Cloudflare KV; on the free tier set
  `ENABLE_FINANCIAL_SYNC=0` to stay inside the write quota.
- YouTube cookies (optional): attach a Volume with your `cookies.txt`
  and set `YT_COOKIES_FILE` to its container path.
