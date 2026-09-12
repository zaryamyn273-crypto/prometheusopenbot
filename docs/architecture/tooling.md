# Tooling Matrix (~90 tools, 76 public schemas)

Every tool is a plain function decorated with `@register_tool(name,
description, category)`; the registry auto-builds OpenAI-compatible schemas.
Internal `bot_*` helpers never reach the model. Failed tools auto-retry
through `TOOL_FALLBACKS` with argument remapping.

Removed for being uncalled/duplicated/theater: `darkweb_search`,
`internal_resilient_fallback_search`, `autonomous_system_health_check`,
`bot_rate_guard`, `bot_output_compactor`, `bot_prompt_token_saver`,
`bot_alias_resolver`, `bot_d1_remember`, `bot_d1_recall`.

## 📊 Finance (`src/tools/financial/`)
- Live crypto from Binance + Nobitex/Wallex with geo-block fallback
  (`get_price`, `get_crypto_overview`).
- Tehran gold/coins (`get_gold_and_coin_price`); free-market fiat
  (`get_dollar_price`, `get_fiat_overview`, `get_global_forex_rates`).

## 🌐 Web & network (`src/tools/web_network/`)
- Smart search: Tavily AI (optional key) + DDG/Bing/Brave/Mojeek/Wikipedia
  engines racing with relevance dedup (`tavily_search`, `web_search`,
  `deep_search_and_read`).
- Live news (`live_news`), Digikala products (`digikala_search`),
  `check_website_status`, `resolve_dns` (DoH), `check_ssl_certificate`,
  `get_ip_info`, `get_weather` (wttr.in → Open-Meteo, keyless).

## 🎵 Media & audio (`src/tools/media/`)
- Full-track music via Persian portals → YouTube 320kbps (`download_music_track`,
  `YT_COOKIES_FILE` supported for datacenter bot-checks).
- Lyrics incl. synced `.lrc` (`get_song_lyrics`, LRCLIB → lyrics.ovh → crawl).
- Whisper STT with SSRF-guarded fetch (`transcribe_audio_tool`).
- QR (`generate_qr_code_tool`), Telegraph publishing (`publish_telegraph_article`).

## 🔬 Scientific & general (`src/tools/scientific/`)
- Sandboxed math evaluator, stats, unit/color/JSON/hash/base64/UUID tools,
  official clock (`get_current_datetime_info`).

## 🛡️ System & admin (`src/tools/admin/`, `src/tools/system/`)
- Python/JavaScript/shell **only in E2B cloud** (`execute_python_code`,
  `e2b_run_code`, `e2b_run_command`); DISABLED without `E2B_API_KEY`.
- Telemetry (`admin_system_diagnostics`), D1-backed ban/mute/user tools,
  group governance (`list_joined_groups_tool`, `leave_group_by_admin_tool`…).

## 🐙 GitHub (`src/tools/github/`)
- 12 tools: repo/issue/commit/release/code search, readmes, files, stats,
  trending. `github_search_code` falls back to web results without a token.

## 🗄️ Memory (`src/tools/database/`)
- D1 records (store/retrieve/search/list/delete), KV store/retrieve,
  conversation-history search, admin-memory manager.
