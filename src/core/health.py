"""Minimal liveness probe (stdlib only, no extra deps).

Long-polling bots have a nasty failure mode: the process stays alive while
the asyncio loop is wedged, so Railway/Docker think everything is fine.
This module runs a tiny threaded HTTP server exposing ``GET /healthz``:

- ``200 {"status": "ok"}`` — event loop heartbeating normally.
- ``503 {"status": "stale"|"starting"}`` — loop stuck (or still booting).

Wiring: :func:`start_health_server` is called once from ``__main__`` before
polling starts; :func:`heartbeat` is called every ~15s by an asyncio task
spawned in ``post_init``. If the loop freezes, heartbeats stop and the probe
goes 503, letting the orchestrator restart the container.
"""
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

_STARTED_AT = time.monotonic()
_LAST_BEAT = 0.0
_BEAT_LOCK = threading.Lock()

# Startup grace: no heartbeat expected before the bot loop is running.
STARTUP_GRACE_SEC = 120.0
# A loop that hasn't beaten in this long is considered wedged.
STALE_AFTER_SEC = 90.0


def heartbeat() -> None:
    """Mark the event loop alive. Called periodically from inside the loop."""
    global _LAST_BEAT
    with _BEAT_LOCK:
        _LAST_BEAT = time.monotonic()


def _snapshot() -> tuple:
    with _BEAT_LOCK:
        last = _LAST_BEAT
    uptime = time.monotonic() - _STARTED_AT
    if last <= 0 and uptime < STARTUP_GRACE_SEC:
        return 200, {"status": "starting", "uptime_s": round(uptime, 1)}
    age = time.monotonic() - last if last > 0 else float("inf")
    if age < STALE_AFTER_SEC:
        return 200, {"status": "ok", "uptime_s": round(uptime, 1),
                     "loop_lag_s": round(age, 1)}
    return 503, {"status": "stale", "uptime_s": round(uptime, 1),
                 "last_beat_age_s": round(age, 1) if age != float("inf") else None}


class _Handler(BaseHTTPRequestHandler):
    server_version = "PrometheusHealth/1.0"

    def log_message(self, *args):  # keep probe traffic out of the logs
        pass

    def do_GET(self):
        try:
            path = (self.path or "/").split("?", 1)[0].rstrip("/") or "/"
            if path == "/healthz":
                code, body = _snapshot()
            elif path in ("", "/"):
                code, body = 200, {"service": "prometheus-openbot", "probe": "/healthz"}
            else:
                code, body = 404, {"status": "not-found"}
            data = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass


def start_health_server(port: int = 0) -> object:
    """Start the probe server in a daemon thread. Never raises.

    Port: explicit arg > $PORT (Railway) > 8080. Returns the server or None.
    """
    if not port:
        try:
            port = int(os.getenv("PORT", "8080") or 8080)
        except Exception:
            port = 8080
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    except Exception as e:
        logger.warning(f"Health server bind failed on :{port} ({e}) — continuing without /healthz.")
        return None
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5},
                         name="healthz", daemon=True)
    t.start()
    logger.info(f"Health probe listening on :{port} (/healthz).")
    return server
