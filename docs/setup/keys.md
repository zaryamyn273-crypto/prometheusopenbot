# API Keys Setup

To run with full features you need a few keys and IDs. Some are **required**
(for first boot), some **optional** (for side tools). Only **3 variables**
are required to boot: `TELEGRAM_BOT_TOKEN`, `ADMIN_ID`, `ROUTER_API_KEY`.

## 1. Telegram Bot Token (TELEGRAM_BOT_TOKEN) — [required 🔴]
- **Use:** the bot's identity for connecting to Telegram servers and sending/receiving messages.
- **How to get it:**
  1. Open [@BotFather](https://t.me/BotFather) on Telegram.
  2. Send `/newbot`.
  3. Pick a display name, then a username (must end in `bot`).
  4. BotFather gives you a token like `1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ`.
  5. For groups: run `/setprivacy` in BotFather, pick your bot, set it to `Disable` so it can read group messages.

## 2. Admin Numeric ID (ADMIN_ID) — [required 🔴]
- **Use:** identity of the owner/super-admin for the admin panel, Python execution, user bans and group management.
- **How to get it:**
  1. Open [@userinfobot](https://t.me/userinfobot) or [@JsonDumpBot](https://t.me/JsonDumpBot).
  2. Press start to get your numeric ID (e.g. `123456789`).
  3. Put it in `ADMIN_ID`.

## 3. AI Key and Endpoint (ROUTER_API_KEY and ROUTER_BASE_URL) — [required 🔴]
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

## 4. Cloudflare Account, D1 and KV — [optional 🟡]
- **Use:** permanent chat history, full-text search over old group messages, ban lists, distributed cloud cache. Without it the bot keeps working on RAM (L1).
- **How to get it free:**
  1. Create an account at [cloudflare.com](https://cloudflare.com).
  2. **Account ID:** open Workers & D1 in the dashboard; the 32-char account ID is on the right column.
  3. **API Token:** *My Profile > API Tokens > Create Token*, pick the *Edit Cloudflare Workers* template (least privilege: D1 edit + KV edit on the two resources below).
  4. **D1 database:** *Workers & Pages > D1 SQL Database*, create one (e.g. `prometheus-db`), copy the Database UUID into `CLOUDFLARE_D1_ID`.
  5. **KV namespace:** *Workers & Pages > KV*, create one (e.g. `prometheus-kv`), copy the Namespace ID into `CLOUDFLARE_KV_ID`.

## 5. Tavily Web Search Key (TAVILY_API_KEY) — [optional ⚪]
- **Use:** fast AI search engine for live news, version comparisons, same-day events.
- **How to get it free:**
  1. Go to [tavily.com](https://tavily.com) and sign up (free plan: 1000 searches/month, no card).
  2. Copy your key (starts with `tvly-`) into `TAVILY_API_KEY`.

## 6. AllRatesToday Rates Key (ALLRATESTODAY_API_KEY) — [optional ⚪]
- **Use:** direct live fiat rates (USD, EUR, AED...) and Iranian gold/coin prices.
- **How to get it:**
  1. Go to [allratestoday.com](https://allratestoday.com), sign up, get an `art_live_...` key.
  2. *(Without it the bot falls back to live web scrapers automatically.)*

## 7. GitHub Token (GITHUB_TOKEN) — [optional ⚪]
- **Use:** higher rate limits for the 12 GitHub tools (code/commit/issue/release search).
- **How to get it free:**
  1. Go to [github.com/settings/tokens](https://github.com/settings/tokens).
  2. *Generate new token (classic)*, tick `public_repo` (nothing more), put the `ghp_...` token in `GITHUB_TOKEN`.

## 8. Spotify Keys (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET) — [optional ⚪]
- **Use:** official high-quality covers and exact metadata for foreign tracks.
- **How to get it free:**
  1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).
  2. Create an app, copy `Client ID` and `Client Secret`.
  3. *(Without them the bot uses iTunes API + default metadata.)*

## 9. E2B Cloud Sandbox (E2B_API_KEY) — [optional ⚪]
- **Use:** the ONLY place AI-written Python/JavaScript/shell ever runs. Without it, code execution tools answer DISABLED (there is deliberately no local fallback — see [SECURITY.md](../../SECURITY.md)).
- **How to get it free:**
  1. Sign up at [e2b.dev](https://e2b.dev).
  2. Get a key from the [E2B dashboard](https://e2b.dev/dashboard?tab=keys) (starts with `e2b_`).
  3. Put it in `E2B_API_KEY`. (Optional: `E2B_TEMPLATE` for a custom template, `E2B_TIMEOUT_SEC` for the run cap.)

## 10. YouTube Cookies (YT_COOKIES_FILE) — [optional ⚪]
- **Use:** only needed if YouTube flags your server IP as a bot and music downloads fail with `Sign in to confirm you're not a bot`. Leave empty otherwise.
- **How to get it:**
  1. Export a Netscape cookies file from youtube.com with a browser extension (e.g. Get cookies.txt).
  2. Place the file next to the bot (on Railway: a Volume, on Docker: `./cookies`) and set its path in `YT_COOKIES_FILE`.

## Environment Variables (full reference)

| Variable | Type | Default | Use |
| :--- | :---: | :---: | :--- |
| `TELEGRAM_BOT_TOKEN` | required 🔴 | - | Telegram bot token from BotFather |
| `ADMIN_ID` | required 🔴 | - | Numeric Telegram user ID of the super-admin |
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
| `E2B_API_KEY` | optional ⚪ | `""` | E2B cloud sandbox (without it: code exec DISABLED) |
| `E2B_TEMPLATE` | optional ⚪ | `""` | Custom E2B template (empty = default) |
| `E2B_TIMEOUT_SEC` | optional ⚪ | `30` | E2B run cap in seconds (5–120) |
| `YT_COOKIES_FILE` | optional ⚪ | `""` | YouTube cookies file (only if music downloads hit bot-check) |
| `ENABLE_FINANCIAL_SYNC` | optional ⚪ | `1` | Background price sync (`0` = off, saves KV quota) |
| `FINANCIAL_SYNC_INTERVAL_SEC` | optional ⚪ | `900` | Price sync interval in seconds (min 300) |
| `PORT` | optional ⚪ | `8080` | Local port for the `/healthz` probe |
