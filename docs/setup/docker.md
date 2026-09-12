# Run with Docker (one-liner)

Pinned interpreter (`python:3.12-slim`, multi-stage build), non-root runtime
user, `ffmpeg` baked in, and a `HEALTHCHECK` wired to `/healthz`.

## Quickstart

```bash
cp .env.example .env   # set TELEGRAM_BOT_TOKEN, ADMIN_ID, ROUTER_API_KEY
docker compose up -d --build
docker compose logs -f
curl -s http://127.0.0.1:8080/healthz
```

Expected: `{"status": "ok", "uptime_s": …}`.

## Details

- `Dockerfile`: builder stage compiles/installs deps, runtime stage ships
  only the app + `ffmpeg` + `curl`. Runs as UID 10001 (`bot`), never root.
- `docker-compose.yml`: `restart: unless-stopped`, `.env` file, healthcheck
  every 30s (60s start period), `./cookies:/app/cookies:ro` volume for
  optional YouTube cookies (`YT_COOKIES_FILE=/app/cookies/youtube_cookies.txt`).
- Only port **8080 bound to localhost** is exposed, and only for `/healthz`;
  Telegram uses outbound long-polling, no inbound ports needed.
- Stop: `docker compose down`. Update: `git pull && docker compose up -d --build`.

## Without compose

```bash
docker build -t prometheus-openbot .
docker run -d --name prometheus --restart unless-stopped \
  --env-file .env -p 127.0.0.1:8080:8080 prometheus-openbot
```
