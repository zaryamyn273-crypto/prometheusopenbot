# Prometheus OpenBot — multi-stage, pinned interpreter (python:3.12-slim).
# Stage 1 builds wheels/sdists; stage 2 ships only runtime bits + ffmpeg.
# Run:  cp .env.example .env  (fill it)  &&  docker compose up -d --build

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080
# ffmpeg (music pipeline) + curl (HEALTHCHECK). Nothing else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 bot
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=bot:bot . .
USER bot
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1
CMD ["python", "bot.py"]
