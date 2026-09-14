import os
import re
import json
import time
import logging
import asyncio
import threading
from itertools import islice
import httpx
from datetime import datetime
import pytz
import jdatetime
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple, Union

from src.core.config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_D1_ID,
    CLOUDFLARE_KV_ID,
    ADMIN_ID,
    DAILY_USER_LIMIT,
)

logger = logging.getLogger(__name__)

# ============================================================================
# High-Performance Multi-Tier Storage Engine:
# Tier 1: Sub-millisecond In-Memory LRU L1 Fast Buffer
# Tier 2: Cloudflare Workers KV Global Distributed Key-Value Store
# Tier 3: Cloudflare D1 Serverless SQL with Bulletproof Write-Behind Queue
# ============================================================================

_L1_CACHE: OrderedDict[str, Dict[str, Any]] = OrderedDict()
_L1_LOCK = threading.Lock()
_MEMORY_DIRECTIVES: List[str] = []
_BANNED_USERS: set = set()
_BANNED_USERNAMES: set = set()
_BANNED_DETAILS: Dict[int, Dict[str, Any]] = {}
_MUTED_UNTIL: Dict[int, float] = {}
_MUTED_USERNAMES: Dict[str, float] = {}
_USERNAME_TO_ID_MAP: Dict[str, int] = {}
_DISPLAY_NAME_TO_ID_MAP: Dict[str, Dict[str, Any]] = {}
_CHAT_DISPLAY_NAMES: Dict[int, Dict[str, Dict[str, Any]]] = {}
_CHAT_HISTORIES: Dict[int, List[Dict[str, Any]]] = {}
_ACTIVE_GROUPS: Dict[int, Dict[str, Any]] = {}
# Chats awaiting admin activation (bot was added by a non-admin).
# Mirrored from D1 `tracked_groups.status == 'pending'` at startup.
_PENDING_GROUPS: set = set()
_USER_TIMEZONES: Dict[int, str] = {}
# Bot Self-Mute State (Admin-directed quiet/silence mode per-chat or global)
_BOT_SELF_MUTED_CHATS: Dict[int, float] = {}
_BOT_SELF_MUTED_GLOBAL_UNTIL: float = 0.0

# Asynchronous Write-Behind Batch Message Queue & Worker Guard
_D1_WRITE_QUEUE: Optional[asyncio.Queue] = None
_BATCH_WORKER_TASK: Optional[asyncio.Task] = None

_http_limits = httpx.Limits(max_keepalive_connections=200, max_connections=400, keepalive_expiry=600.0)
_cf_client: Optional[httpx.AsyncClient] = None
_cf_client_loop: Optional[asyncio.AbstractEventLoop] = None

def get_cf_client() -> httpx.AsyncClient:
    # No auth header in the pool — token is attached per-request via _cf_headers()
    # so Railway variable rotation works without restart.
    global _cf_client, _cf_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if (
        _cf_client is None
        or _cf_client.is_closed
        or (_cf_client_loop is not None and current_loop is not None and _cf_client_loop != current_loop)
    ):
        _cf_client = httpx.AsyncClient(
            limits=_http_limits,
            http2=True,
            timeout=8.0,
            headers={
                "Content-Type": "application/json"
            }
        )
        _cf_client_loop = current_loop
    return _cf_client


_CACHED_BEARER: str = ""
_CACHED_HEADERS: Dict[str, str] = {}

def _cf_headers() -> Dict[str, str]:
    global _CACHED_BEARER, _CACHED_HEADERS
    tok = os.getenv("CLOUDFLARE_API_TOKEN") or CLOUDFLARE_API_TOKEN
    if tok != _CACHED_BEARER:
        _CACHED_BEARER = tok
        _CACHED_HEADERS = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
        }
    return _CACHED_HEADERS

_CACHED_KV_KEY: Tuple[str, str] = ("", "")
_CACHED_KV_BASE_URL: str = ""

def _get_kv_base_url() -> str:
    global _CACHED_KV_KEY, _CACHED_KV_BASE_URL
    acc = os.getenv("CLOUDFLARE_ACCOUNT_ID") or CLOUDFLARE_ACCOUNT_ID or ""
    kv = os.getenv("CLOUDFLARE_KV_ID") or CLOUDFLARE_KV_ID or ""
    pair = (acc, kv)
    if pair != _CACHED_KV_KEY:
        _CACHED_KV_KEY = pair
        _CACHED_KV_BASE_URL = f"https://api.cloudflare.com/client/v4/accounts/{acc}/storage/kv/namespaces/{kv}/values" if (acc and kv) else ""
    return _CACHED_KV_BASE_URL

try:
    _TEHRAN_TZ = pytz.timezone("Asia/Tehran")
except Exception:
    _TEHRAN_TZ = None

_TS_LOCK = threading.Lock()
_LAST_TS_SEC: int = 0
_CACHED_TIMESTAMPS: Tuple[str, str, str] = ("", "", "")
_LAST_DATE_KEY: Tuple[int, int, int] = (0, 0, 0)
_CACHED_DATE_PREFIX: str = ""
_CACHED_JDATE_STR: str = ""

def get_tehran_timestamps() -> Tuple[str, str, str]:
    """Returns (created_at_iso, time_str, jalali_date_str) with high-speed 1-second memoization."""
    global _LAST_TS_SEC, _CACHED_TIMESTAMPS, _LAST_DATE_KEY, _CACHED_DATE_PREFIX, _CACHED_JDATE_STR
    current_sec = int(time.time())
    if current_sec == _LAST_TS_SEC:
        return _CACHED_TIMESTAMPS

    with _TS_LOCK:
        if current_sec == _LAST_TS_SEC:
            return _CACHED_TIMESTAMPS
        try:
            tz = _TEHRAN_TZ or pytz.timezone("Asia/Tehran")
            now = datetime.now(tz)
            date_key = (now.year, now.month, now.day)
            if date_key != _LAST_DATE_KEY:
                j_now = jdatetime.datetime.fromgregorian(datetime=now)
                _CACHED_DATE_PREFIX = f"{now.year:04d}-{now.month:02d}-{now.day:02d}"
                _CACHED_JDATE_STR = f"{j_now.year:04d}/{j_now.month:02d}/{j_now.day:02d}"
                _LAST_DATE_KEY = date_key

            time_str = f"{now.hour:02d}:{now.minute:02d}:{now.second:02d}"
            iso_str = f"{_CACHED_DATE_PREFIX} {time_str}"
            res = (iso_str, time_str, _CACHED_JDATE_STR)
            _CACHED_TIMESTAMPS = res
            _LAST_TS_SEC = current_sec
            return res
        except Exception:
            iso_fallback = time.strftime("%Y-%m-%d %H:%M:%S")
            res = (iso_fallback, iso_fallback, iso_fallback)
            _CACHED_TIMESTAMPS = res
            _LAST_TS_SEC = current_sec
            return res

# --- Tier 1: L1 Fast Sub-Millisecond Memory Buffer ---

_L1_HITS = 0
_L1_MISSES = 0
_L1_LAST_HIT_AT: float = 0.0


def l1_get(key: str) -> Optional[str]:
    global _L1_HITS, _L1_MISSES, _L1_LAST_HIT_AT
    now = time.time()
    with _L1_LOCK:
        item = _L1_CACHE.get(key)
        if item is None:
            _L1_MISSES += 1
            return None
        if now > item["expires_at"]:
            _L1_CACHE.pop(key, None)
            _L1_MISSES += 1
            return None
        # Sliding refresh: hot keys live longer (up to +50% of original TTL).
        hits = item["hits"] + 1
        item["hits"] = hits
        if hits % 5 == 0:
            item["expires_at"] = min(item["expires_at"] + 60.0, now + item["ttl"] * 1.5)
        # True LRU touch: move to most recently used position
        _L1_CACHE.move_to_end(key)
        _L1_HITS += 1
        _L1_LAST_HIT_AT = now
        return item["value"]

_L1_MAX_SIZE = 800
_L1_LOW_WATER = 700


def l1_set(key: str, value: str, ttl_sec: int = 300):
    now = time.time()
    try:
        _ttl = max(30, int(ttl_sec))
    except Exception:
        _ttl = 300

    # Fast type check avoiding unnecessary str() allocations
    clean_val = value if isinstance(value, str) else str(value or "")
    if len(clean_val) > 65536:
        clean_val = clean_val[:65536]

    with _L1_LOCK:
        # Fast path: in-place update for existing keys with zero eviction checks
        existing = _L1_CACHE.get(key)
        if existing is not None:
            existing["value"] = clean_val
            existing["expires_at"] = now + _ttl
            existing["ttl"] = _ttl
            existing["set_at"] = now
            _L1_CACHE.move_to_end(key)
            return

        # New key: bound capacity without massive low-water mark dump storms
        if len(_L1_CACHE) >= _L1_MAX_SIZE:
            for old_k in list(islice(_L1_CACHE, 32)):
                old_v = _L1_CACHE.get(old_k)
                if old_v is not None and now > old_v.get("expires_at", 0.0):
                    _L1_CACHE.pop(old_k, None)
            while len(_L1_CACHE) >= _L1_MAX_SIZE:
                try:
                    _L1_CACHE.popitem(last=False)
                except KeyError:
                    break

        _L1_CACHE[key] = {
            "value": clean_val,
            "expires_at": now + _ttl,
            "ttl": _ttl,
            "hits": 0,
            "set_at": now,
        }

def l1_delete(key: str):
    with _L1_LOCK:
        _L1_CACHE.pop(key, None)
    with _KV_NEG_LOCK:
        _KV_NEGATIVE_CACHE.pop(key, None)

# --- Tier 2: High-Speed Cloudflare Workers KV Operations ---
# Cloudflare free plan allows ~1000 KV writes/day. The 5-minute bulk market
# syncer alone would burn ~6000 writes/day (error 10048), so cloud writes are
# quota-aware: same-value rewrites are skipped, bulk keys persist to cloud at
# most once per _KV_SLOW_CLOUD_INTERVAL_SEC, and a circuit breaker pauses all
# cloud PUTs after a 429. L1 RAM always stays hot, so reads never break.
_KV_SLOW_CLOUD_INTERVAL_SEC = 3600
_KV_SLOW_PREFIXES = (
    "CRYPTO_", "GOLD_", "FIAT_", "FOREX_", "FINANCIAL_",
    "WEATHER_", "LIVE_NEWS_", "SEARCH_", "GH_SEARCH_",
    "music_v2_", "DEEP_", "WEBPAGE_", "D1_STORE_",
)
_KV_CIRCUIT_OPEN_UNTIL: float = 0.0
_KV_LAST_CLOUD_WRITE: Dict[str, float] = {}
_KV_LAST_CLOUD_HASH: Dict[str, int] = {}
_KV_LAST_CLOUD_ERROR: str = ""
_KV_IN_FLIGHT_WRITES: set = set()
_KV_IN_FLIGHT_READS: Dict[str, asyncio.Future] = {}
_KV_NEGATIVE_CACHE: OrderedDict[str, float] = OrderedDict()
_KV_NEGATIVE_MAX_SIZE: int = 1000
_KV_NEG_LOCK = threading.Lock()

def _set_kv_negative_cache(key: str, ttl_sec: float = 60.0):
    now = time.time()
    with _KV_NEG_LOCK:
        if len(_KV_NEGATIVE_CACHE) >= _KV_NEGATIVE_MAX_SIZE:
            for old_k in list(islice(_KV_NEGATIVE_CACHE, 64)):
                if now >= _KV_NEGATIVE_CACHE.get(old_k, 0.0):
                    _KV_NEGATIVE_CACHE.pop(old_k, None)
            while len(_KV_NEGATIVE_CACHE) >= _KV_NEGATIVE_MAX_SIZE:
                try:
                    _KV_NEGATIVE_CACHE.popitem(last=False)
                except KeyError:
                    break
        _KV_NEGATIVE_CACHE[key] = now + ttl_sec
        _KV_NEGATIVE_CACHE.move_to_end(key)

def kv_cloud_circuit_open() -> bool:
    return time.time() < _KV_CIRCUIT_OPEN_UNTIL

def _kv_open_circuit(retry_after_sec: float, reason: str, key: str):
    global _KV_CIRCUIT_OPEN_UNTIL, _KV_LAST_CLOUD_ERROR
    _KV_CIRCUIT_OPEN_UNTIL = time.time() + max(60.0, float(retry_after_sec))
    _KV_LAST_CLOUD_ERROR = reason
    logger.warning(f"Cloudflare KV write throttled ({reason}) on key '{key}'; cloud PUTs paused, L1 RAM keeps serving reads.")

async def kv_get_cache_async(key: str) -> Optional[str]:
    val = l1_get(key)
    if val is not None:
        return val

    # Fast negative cache check to avoid hammering KV for cold missing keys
    now = time.time()
    with _KV_NEG_LOCK:
        neg_exp = _KV_NEGATIVE_CACHE.get(key)
        if neg_exp is not None:
            if now < neg_exp:
                return None
            _KV_NEGATIVE_CACHE.pop(key, None)

    base_url = _get_kv_base_url()
    if not base_url:
        return None

    # Anti-stampede: coalesce concurrent reads for the same cold key
    loop = asyncio.get_running_loop()
    fut = _KV_IN_FLIGHT_READS.get(key)
    if fut is not None and not fut.done() and fut.get_loop() is loop:
        try:
            return await asyncio.shield(fut)
        except asyncio.CancelledError:
            raise
        except Exception:
            return l1_get(key)

    fut = loop.create_future()
    _KV_IN_FLIGHT_READS[key] = fut

    try:
        client = get_cf_client()
        url = f"{base_url}/{key}"
        resp = await client.get(url, headers=_cf_headers(), timeout=3.5)
        result: Optional[str] = None
        if resp.status_code == 200:
            result = resp.text
            l1_set(key, result, ttl_sec=120)
            with _KV_NEG_LOCK:
                _KV_NEGATIVE_CACHE.pop(key, None)
        elif resp.status_code == 404:
            _set_kv_negative_cache(key, ttl_sec=60.0)
        if not fut.done():
            fut.set_result(result)
        return result
    except Exception as e:
        logger.debug(f"KV get error ({key}): {e}")
        if not fut.done():
            fut.set_result(None)
        return None
    finally:
        if not fut.done():
            fut.set_result(None)
        if _KV_IN_FLIGHT_READS.get(key) is fut:
            _KV_IN_FLIGHT_READS.pop(key, None)

async def kv_set_cache_async(key: str, value: str, expiration_ttl: int = 300, cloud_write: bool = True, cloud_min_interval_sec: Optional[int] = None) -> bool:
    """
    Quota-aware cache writer. L1 RAM is ALWAYS updated (reads stay instant).
    Cloud PUTs are skipped when: value unchanged since last cloud write,
    per-key throttle interval not elapsed, or the 429 circuit breaker is open.
    Returns True when the value is safely cached (L1), even if the cloud sync
    was deferred — use get_cache_health_async() to inspect cloud state.
    """
    val_str = value if isinstance(value, str) else str(value or "")
    clean_ttl = max(60, int(expiration_ttl))
    l1_set(key, val_str, ttl_sec=clean_ttl)
    with _KV_NEG_LOCK:
        _KV_NEGATIVE_CACHE.pop(key, None)

    base_url = _get_kv_base_url()
    if not cloud_write or not base_url:
        return True
    if kv_cloud_circuit_open():
        return True

    if cloud_min_interval_sec is None:
        cloud_min_interval_sec = _KV_SLOW_CLOUD_INTERVAL_SEC if key.startswith(_KV_SLOW_PREFIXES) else 0

    now = time.time()
    if now - _KV_LAST_CLOUD_WRITE.get(key, 0.0) < max(0, int(cloud_min_interval_sec)):
        return True

    val_hash = hash(val_str)
    if key in _KV_LAST_CLOUD_WRITE and _KV_LAST_CLOUD_HASH.get(key) == val_hash:
        return True

    # Coalesce concurrent cloud writes for the exact same key
    if key in _KV_IN_FLIGHT_WRITES:
        return True
    _KV_IN_FLIGHT_WRITES.add(key)

    # Memory optimization: bound tracking structures with islice to avoid full list allocation
    if len(_KV_LAST_CLOUD_WRITE) >= 2000:
        for old_k in list(islice(_KV_LAST_CLOUD_WRITE, 400)):
            _KV_LAST_CLOUD_WRITE.pop(old_k, None)
            _KV_LAST_CLOUD_HASH.pop(old_k, None)

    try:
        client = get_cf_client()
        url = f"{base_url}/{key}?expiration_ttl={clean_ttl}"
        resp = await client.put(url, headers=_cf_headers(), content=val_str.encode("utf-8"), timeout=3.5)
        if resp.status_code == 200:
            _KV_LAST_CLOUD_WRITE[key] = now
            _KV_LAST_CLOUD_HASH[key] = val_hash
            return True
        if resp.status_code == 429:
            try:
                body = resp.json()
                err_code = (body.get("errors") or [{}])[0].get("code")
            except Exception:
                err_code = None
            try:
                raw_ra = resp.headers.get("Retry-After", 300)
                retry_after = float(raw_ra) if raw_ra else 300.0
            except (ValueError, TypeError):
                retry_after = 300.0
            if err_code == 10048:
                _kv_open_circuit(12 * 3600, "free daily write quota exhausted (10048)", key)
            else:
                _kv_open_circuit(retry_after, f"HTTP 429 (code {err_code})", key)
            return True
        logger.debug(f"KV set HTTP {resp.status_code} ({key}): {resp.text[:150]}")
        return True
    except Exception as e:
        logger.debug(f"KV set error ({key}): {e}")
        return True
    finally:
        _KV_IN_FLIGHT_WRITES.discard(key)

async def kv_get_cloud_async(key: str) -> Optional[str]:
    """Direct Cloudflare KV read that bypasses L1 (used for startup warmup)."""
    base_url = _get_kv_base_url()
    if not base_url:
        return None
    try:
        client = get_cf_client()
        url = f"{base_url}/{key}"
        resp = await client.get(url, headers=_cf_headers(), timeout=4.0)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        logger.debug(f"KV cloud GET error ({key}): {e}")
    return None

_WARMUP_KEYS = [f"CRYPTO_PRICE_{s}" for s in (
    "BTC", "ETH", "SOL", "BNB", "TON", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK", "SUI", "PEPE", "NOT", "USDT"
)] + [
    "CRYPTO_OVERVIEW_GRID", "GOLD_COIN_PRICES", "FIAT_OVERVIEW_RATES",
    "FOREX_RATES_USD", "FOREX_RATES_EUR", "FINANCIAL_5MIN_DASHBOARD",
]

_HEALTH_MEMO: Dict[str, Any] = {"at": 0.0, "data": None}


async def warm_l1_from_cloud_async() -> int:
    """
    Startup warmer: pulls the last persisted bulk-market keys from cloud KV
    straight into L1 RAM. Reads are cheap (100k/day free), so a fresh deploy
    serves instant answers instead of starting with a cold cache.
    Keys are fetched concurrently with bounded concurrency.
    """
    if not _get_kv_base_url():
        return 0

    sem = asyncio.Semaphore(8)

    async def _warm_one(k: str) -> bool:
        async with sem:
            try:
                val = await kv_get_cloud_async(k)
                if val:
                    l1_set(k, val, ttl_sec=600)
                    return True
            except Exception:
                pass
            return False

    warmed = 0
    try:
        results = await asyncio.gather(*[_warm_one(k) for k in _WARMUP_KEYS], return_exceptions=True)
        warmed = sum(1 for r in results if r is True)
    except Exception:
        pass
    logger.info(f"L1 warmup from Cloudflare KV: {warmed}/{len(_WARMUP_KEYS)} keys restored.")
    return warmed

async def get_cache_health_async() -> Dict[str, Any]:
    """Reports L1 size, KV circuit state, D1 reachability and D1 queue depth."""
    now = time.time()
    try:
        _tot = _L1_HITS + _L1_MISSES
        _hit_rate = round(100.0 * _L1_HITS / _tot, 1) if _tot else 0.0
    except Exception:
        _hit_rate = 0.0

    # Memoize only the D1 reachability network probe for 30s so health daemons don't hammer D1
    d1_reachable = False
    memo_data = _HEALTH_MEMO.get("data")
    if memo_data is not None and (now - float(_HEALTH_MEMO.get("at", 0.0))) < 30.0:
        d1_reachable = bool(memo_data.get("d1_reachable", False))
    else:
        try:
            res = await execute_d1_query("SELECT 1 AS ok", [])
            d1_reachable = bool(res.get("success"))
        except Exception:
            d1_reachable = False
        _HEALTH_MEMO["at"] = now
        _HEALTH_MEMO["data"] = {"d1_reachable": d1_reachable}

    return {
        "l1_keys": len(_L1_CACHE),
        "l1_hit_rate_pct": _hit_rate,
        "l1_hits": _L1_HITS,
        "l1_misses": _L1_MISSES,
        "kv_circuit_open": kv_cloud_circuit_open(),
        "kv_last_cloud_error": _KV_LAST_CLOUD_ERROR or "none",
        "kv_cloud_writes_tracked": len(_KV_LAST_CLOUD_WRITE),
        "d1_queue_depth": _D1_WRITE_QUEUE.qsize() if _D1_WRITE_QUEUE is not None else -1,
        "d1_batch_worker_alive": bool(_BATCH_WORKER_TASK and not _BATCH_WORKER_TASK.done()),
        "d1_reachable": d1_reachable,
    }

# --- Tier 3: High-Power Cloudflare D1 SQL Operations ---

async def execute_d1_query(sql: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_D1_ID:
        return {"success": False, "results": []}

    clean_params = [
        p if isinstance(p, (int, float, str, bool)) or p is None else str(p)
        for p in params
    ] if params else []

    try:
        client = get_cf_client()
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/d1/database/{CLOUDFLARE_D1_ID}/query"
        body = {"sql": sql, "params": clean_params}
        resp = await client.post(url, headers=_cf_headers(), json=body, timeout=6.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("result"):
                return {"success": True, "results": data["result"][0].get("results", [])}
            logger.warning(f"D1 API returned success=False or empty result: {data.get('errors')}")
        else:
            logger.error(f"D1 HTTP {resp.status_code}: {resp.text[:200]} | SQL: {sql[:100]} | params: {clean_params[:4]}")
    except Exception as e:
        logger.error(f"D1 Query error: {e}")
    return {"success": False, "results": []}

_cf_sync_client: Optional[httpx.Client] = None

def get_cf_sync_client() -> httpx.Client:
    global _cf_sync_client
    if _cf_sync_client is None or _cf_sync_client.is_closed:
        _cf_sync_client = httpx.Client(
            limits=_http_limits,
            timeout=5.0,
            headers={
                "Content-Type": "application/json"
            }
        )
    return _cf_sync_client

def execute_d1_query_sync(sql: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_D1_ID:
        return {"success": False, "results": []}

    clean_params = []
    if params:
        for p in params:
            if isinstance(p, (int, float, str, bool)) or p is None:
                clean_params.append(p)
            else:
                clean_params.append(str(p))

    try:
        client = get_cf_sync_client()
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/d1/database/{CLOUDFLARE_D1_ID}/query"
        resp = client.post(url, headers=_cf_headers(), json={"sql": sql, "params": clean_params})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and data.get("result"):
                return {"success": True, "results": data["result"][0].get("results", [])}
    except Exception as e:
        logger.error(f"D1 sync error: {e}")
    return {"success": False, "results": []}

# --- Bulletproof Asynchronous Write-Behind Worker Engine ---

_BATCH_DEBOUNCE_SEC = 3.0
_BATCH_MAX_SIZE = 50

_MESSAGE_COLS = (
    "chat_id, user_id, message_id, user_name, username, chat_title, chat_type, "
    "msg_kind, reply_to_msg_id, reply_to_user, reply_to_text, role, content, "
    "msg_date, msg_time, created_at, thread_id, forward_from, sender_chat_id, "
    "detected_lang, char_count, has_media, extra_meta"
)

async def _flush_batch_to_d1(batch: List[Dict[str, Any]]):
    """Safely flushes a batch of messages to Cloudflare D1 with high-efficiency chunking and retries."""
    if not batch:
        return

    # Sanitize each item
    clean_batch = []
    for m in batch:
        clean_batch.append({
            "chat_id": int(m.get("chat_id", 0)),
            "user_id": int(m.get("user_id", 0)),
            "message_id": int(m.get("message_id", 0) or 0),
            "user_name": str(m.get("user_name", ""))[:120],
            "username": str(m.get("username", ""))[:80],
            "chat_title": str(m.get("chat_title", ""))[:150],
            "chat_type": str(m.get("chat_type", ""))[:30],
            "msg_kind": str(m.get("msg_kind", "text"))[:20] or "text",
            "reply_to_msg_id": int(m.get("reply_to_msg_id", 0) or 0),
            "reply_to_user": str(m.get("reply_to_user", ""))[:80],
            "reply_to_text": str(m.get("reply_to_text", ""))[:200],
            "role": str(m.get("role", "user"))[:20],
            "content": str(m.get("content", ""))[:6000],
            "msg_date": str(m.get("msg_date", ""))[:30],
            "msg_time": str(m.get("msg_time", ""))[:30],
            "created_at": str(m.get("created_at", ""))[:40],
            "thread_id": int(m.get("thread_id", 0) or 0),
            "forward_from": str(m.get("forward_from", ""))[:120],
            "sender_chat_id": int(m.get("sender_chat_id", 0) or 0),
            "detected_lang": str(m.get("detected_lang", ""))[:10],
            "char_count": int(m.get("char_count", 0) or 0),
            "has_media": int(m.get("has_media", 0) or 0),
            "extra_meta": str(m.get("extra_meta", "{}"))[:500],
        })

    # Chunk into 25 items per SQL insert (25 * 23 = 575 params, safely below SQLite 999 limit)
    chunk_size = 25
    for i in range(0, len(clean_batch), chunk_size):
        sub_batch = clean_batch[i:i + chunk_size]
        if len(sub_batch) == 1:
            m = sub_batch[0]
            sql = f"INSERT INTO messages ({_MESSAGE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            params = [
                m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"],
                m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"],
                m["reply_to_user"], m["reply_to_text"], m["role"], m["content"],
                m["msg_date"], m["msg_time"], m["created_at"],
                m["thread_id"], m["forward_from"], m["sender_chat_id"],
                m["detected_lang"], m["char_count"], m["has_media"], m["extra_meta"]
            ]
            for attempt in range(3):
                res = await execute_d1_query(sql, params)
                if res.get("success"):
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        else:
            val_placeholders = ["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in sub_batch]
            params = []
            for m in sub_batch:
                params.extend([
                    m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"],
                    m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"],
                    m["reply_to_user"], m["reply_to_text"], m["role"], m["content"],
                    m["msg_date"], m["msg_time"], m["created_at"],
                    m["thread_id"], m["forward_from"], m["sender_chat_id"],
                    m["detected_lang"], m["char_count"], m["has_media"], m["extra_meta"]
                ])
            sql = f"INSERT INTO messages ({_MESSAGE_COLS}) VALUES {', '.join(val_placeholders)}"

            success = False
            for attempt in range(3):
                res = await execute_d1_query(sql, params)
                if res.get("success"):
                    success = True
                    break
                await asyncio.sleep(0.2 * (attempt + 1))

            if not success:
                single_sql = f"INSERT INTO messages ({_MESSAGE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                for m in sub_batch:
                    try:
                        await execute_d1_query(single_sql, [
                            m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"],
                            m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"],
                            m["reply_to_user"], m["reply_to_text"], m["role"], m["content"],
                            m["msg_date"], m["msg_time"], m["created_at"],
                            m["thread_id"], m["forward_from"], m["sender_chat_id"],
                            m["detected_lang"], m["char_count"], m["has_media"], m["extra_meta"]
                        ])
                    except Exception:
                        pass

async def _d1_batch_writer_loop():
    """
    Continuous Background Queue Worker with Adaptive Debouncing:
    Gathers messages over a 3-second window or up to 50 items and flushes them
    in a single multi-row query. Reduces Cloudflare D1 requests by over 95%.
    """
    batch = []
    last_flush = time.time()
    while True:
        try:
            if _D1_WRITE_QUEUE is None:
                await asyncio.sleep(0.5)
                continue

            time_since_flush = time.time() - last_flush
            wait_time = max(0.1, _BATCH_DEBOUNCE_SEC - time_since_flush) if batch else 5.0

            try:
                item = await asyncio.wait_for(_D1_WRITE_QUEUE.get(), timeout=wait_time)
                batch.append(item)
                _D1_WRITE_QUEUE.task_done()
            except asyncio.TimeoutError:
                pass

            # Drain any immediately ready items from queue up to _BATCH_MAX_SIZE
            while not _D1_WRITE_QUEUE.empty() and len(batch) < _BATCH_MAX_SIZE:
                try:
                    b_item = _D1_WRITE_QUEUE.get_nowait()
                    batch.append(b_item)
                    _D1_WRITE_QUEUE.task_done()
                except Exception:
                    break

            now = time.time()
            if batch and (len(batch) >= _BATCH_MAX_SIZE or (now - last_flush) >= _BATCH_DEBOUNCE_SEC):
                to_flush = batch
                batch = []
                last_flush = now
                await _flush_batch_to_d1(to_flush)

        except asyncio.CancelledError:
            if batch:
                await _flush_batch_to_d1(batch)
            break
        except Exception as e:
            logger.error(f"D1 batch write loop exception: {e}")
            await asyncio.sleep(1.0)

async def flush_write_queue_async():
    """Immediately drains and persists all pending messages in memory to D1."""
    global _D1_WRITE_QUEUE
    if _D1_WRITE_QUEUE is None or _D1_WRITE_QUEUE.empty():
        return
    pending = []
    while not _D1_WRITE_QUEUE.empty():
        try:
            item = _D1_WRITE_QUEUE.get_nowait()
            pending.append(item)
            _D1_WRITE_QUEUE.task_done()
        except Exception:
            break
    if pending:
        await _flush_batch_to_d1(pending)

def ensure_batch_worker():
    global _D1_WRITE_QUEUE, _BATCH_WORKER_TASK
    if _D1_WRITE_QUEUE is None:
        _D1_WRITE_QUEUE = asyncio.Queue(maxsize=20000)
    if _BATCH_WORKER_TASK is None or _BATCH_WORKER_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _BATCH_WORKER_TASK = loop.create_task(_d1_batch_writer_loop())
        except RuntimeError:
            pass

# --- Database Initialization & Advanced Schema ---

def init_db():
    logger.info("Initializing Cloudflare D1 SQL Schema & Advanced Tracked Groups Table...")
    schema = """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER,
        user_name TEXT,
        username TEXT,
        chat_title TEXT,
        chat_type TEXT DEFAULT '',
        msg_kind TEXT DEFAULT 'text',
        reply_to_msg_id INTEGER DEFAULT 0,
        reply_to_user TEXT DEFAULT '',
        reply_to_text TEXT DEFAULT '',
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        msg_date TEXT,
        msg_time TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        message_id INTEGER DEFAULT 0,
        thread_id INTEGER DEFAULT 0,
        forward_from TEXT DEFAULT '',
        sender_chat_id INTEGER DEFAULT 0,
        detected_lang TEXT DEFAULT '',
        char_count INTEGER DEFAULT 0,
        has_media INTEGER DEFAULT 0,
        extra_meta TEXT DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS admin_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directive TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS custom_data_store (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_name TEXT UNIQUE NOT NULL,
        data_value TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT DEFAULT '',
        reason TEXT,
        banned_by INTEGER DEFAULT 0,
        source_chat_id INTEGER DEFAULT 0,
        source_chat_title TEXT DEFAULT '',
        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS muted_users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT DEFAULT '',
        reason TEXT,
        muted_by INTEGER DEFAULT 0,
        source_chat_id INTEGER DEFAULT 0,
        source_chat_title TEXT DEFAULT '',
        until_ts REAL DEFAULT 0,
        muted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS user_mappings (
        username TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tracked_groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        chat_type TEXT,
        member_count INTEGER DEFAULT 0,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        username TEXT DEFAULT '',
        invite_link TEXT DEFAULT '',
        status TEXT DEFAULT 'active'
    );
    CREATE TABLE IF NOT EXISTS daily_usage (
        user_id INTEGER NOT NULL,
        day TEXT NOT NULL,
        used INTEGER DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, day)
    );
    CREATE TABLE IF NOT EXISTS quota_overrides (
        user_id INTEGER PRIMARY KEY,
        limit_n INTEGER NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY,
        timezone TEXT DEFAULT '',
        language TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS scheduled_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        user_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        title TEXT NOT NULL,
        action_type TEXT DEFAULT 'reminder',
        payload TEXT NOT NULL,
        schedule_type TEXT DEFAULT 'once',
        interval_seconds INTEGER DEFAULT 0,
        cron_expr TEXT DEFAULT '',
        next_run_ts REAL NOT NULL,
        is_recurring INTEGER DEFAULT 0,
        status TEXT DEFAULT 'active',
        timezone TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_run_at TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(chat_id, thread_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_lang ON messages(chat_id, detected_lang);
    CREATE INDEX IF NOT EXISTS idx_messages_search ON messages(chat_id, content);
    CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(chat_id, user_id, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_user_name ON messages(chat_id, user_name);
    CREATE INDEX IF NOT EXISTS idx_messages_username ON messages(chat_id, username);
    CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(chat_id, msg_date, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_kind ON messages(chat_id, msg_kind, id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_reply ON messages(chat_id, reply_to_msg_id);
    CREATE INDEX IF NOT EXISTS idx_messages_id_desc ON messages(id DESC);
    CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_user_mappings_uid ON user_mappings(user_id);
    CREATE INDEX IF NOT EXISTS idx_tracked_groups_added ON tracked_groups(added_at DESC);
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, user_name, username, tokenize='unicode61');
    CREATE INDEX IF NOT EXISTS idx_custom_data ON custom_data_store(key_name);
    CREATE INDEX IF NOT EXISTS idx_custom_data_cat ON custom_data_store(category, key_name);
    CREATE INDEX IF NOT EXISTS idx_banned_username ON banned_users(username);
    CREATE INDEX IF NOT EXISTS idx_scheduled_next ON scheduled_jobs(status, next_run_ts);
    """
    # D1 REST /query runs exactly ONE statement per call — a batched multi-statement
    # string fails (or silently runs only the first CREATE). Split, never batch.
    # Trigger bodies contain inner semicolons, so they are executed whole, separately.
    # Fast path: a single sqlite_master probe skips all DDL on warm boots
    # (20 serial round-trips at startup would stall boot when CF is slow).
    _need_ddl = True
    try:
        _probe = execute_d1_query_sync(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index') LIMIT 60"
        )
        if _probe.get("success"):
            _have = {str(r.get("name", "")) for r in (_probe.get("results") or [])}
            _need_ddl = not {"messages", "admin_memories", "custom_data_store",
                             "banned_users", "muted_users", "user_mappings",
                             "tracked_groups", "daily_usage", "quota_overrides", "messages_fts",
                             "scheduled_jobs", "user_preferences"}.issubset(_have)
    except Exception:
        _need_ddl = True
    if _need_ddl:
        for _stmt in schema.split(";"):
            _s = _stmt.strip()
            if _s:
                execute_d1_query_sync(_s)

    # Migrate DBs created before username/invite_link/status/enriched columns existed (no-op if present).
    for _mig in (
        "ALTER TABLE tracked_groups ADD COLUMN username TEXT DEFAULT ''",
        "ALTER TABLE tracked_groups ADD COLUMN invite_link TEXT DEFAULT ''",
        "ALTER TABLE tracked_groups ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE messages ADD COLUMN thread_id INTEGER DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN forward_from TEXT DEFAULT ''",
        "ALTER TABLE messages ADD COLUMN sender_chat_id INTEGER DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN detected_lang TEXT DEFAULT ''",
        "ALTER TABLE messages ADD COLUMN char_count INTEGER DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN has_media INTEGER DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN extra_meta TEXT DEFAULT '{}'",
        "ALTER TABLE scheduled_jobs ADD COLUMN timezone TEXT DEFAULT ''",
    ):
        try:
            execute_d1_query_sync(_mig)
        except Exception:
            pass

    # Synchronize FTS Triggers (Automatic high-speed real-time sync into messages_fts)
    execute_d1_query_sync("""CREATE TRIGGER IF NOT EXISTS trg_messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, content, user_name, username) VALUES (new.id, new.content, new.user_name, new.username);
    END;""")
    execute_d1_query_sync("""CREATE TRIGGER IF NOT EXISTS trg_messages_ad AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, content, user_name, username) VALUES ('delete', old.id, old.content, old.user_name, old.username);
    END;""")

    # A D1 hiccup must NEVER prevent boot: RAM works standalone.
    try:
        sync_memory_from_d1_sync()
    except Exception as e:
        logger.warning(f"D1 startup sync skipped: {e}")

def sync_memory_from_d1_sync():
    # Only rebound names need `global` (_USERNAME_TO_ID_MAP/_ACTIVE_GROUPS are mutated in place).
    global _MEMORY_DIRECTIVES, _BANNED_USERS, _BANNED_USERNAMES
    mem_res = execute_d1_query_sync("SELECT directive FROM admin_memories ORDER BY id ASC")
    if mem_res["success"]:
        _MEMORY_DIRECTIVES = [row["directive"] for row in mem_res["results"] if "directive" in row]

    ban_res = execute_d1_query_sync("SELECT user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title, banned_at FROM banned_users")
    if ban_res["success"]:
        for row in ban_res["results"]:
            uid = row.get("user_id")
            if uid:
                uid_int = int(uid)
                _BANNED_USERS.add(uid_int)
                _BANNED_DETAILS[uid_int] = row
            u = (row.get("username") or "").lower().lstrip("@")
            if u:
                _BANNED_USERNAMES.add(u)

    try:
        mute_res = execute_d1_query_sync("SELECT user_id, username, until_ts FROM muted_users")
        if mute_res.get("success"):
            _now = time.time()
            for row in mute_res["results"]:
                try:
                    _until = float(row.get("until_ts") or 0)
                except Exception:
                    _until = 0
                if _until > _now:
                    if row.get("user_id"):
                        _MUTED_UNTIL[int(row["user_id"])] = _until
                    if row.get("username"):
                        _MUTED_USERNAMES[str(row["username"]).lower().lstrip("@")] = _until
    except Exception:
        pass

    map_res = execute_d1_query_sync("SELECT username, user_id FROM user_mappings")
    if map_res["success"]:
        for r in map_res["results"]:
            if r.get("username") and r.get("user_id"):
                _USERNAME_TO_ID_MAP[r["username"].lower().lstrip("@")] = r["user_id"]

    group_res = execute_d1_query_sync("SELECT chat_id, title, chat_type, member_count, added_by, added_at, username, invite_link, status FROM tracked_groups")
    if group_res.get("success"):
        for g in group_res["results"]:
            try:
                _cid = g.get("chat_id")
                if _cid is None:
                    continue
                _ACTIVE_GROUPS[int(_cid)] = g
                if str(g.get("status") or "active") == "pending":
                    _PENDING_GROUPS.add(int(_cid))
            except Exception:
                continue

    # Daily quota backfill: today's counters survive restarts (no free quota).
    try:
        _du_res = execute_d1_query_sync("SELECT user_id, used FROM daily_usage WHERE day = ?", [_today_key()])
    except Exception:
        _du_res = {"success": False, "results": []}
    if _du_res.get("success"):
        for _r in (_du_res.get("results") or []):
            try:
                if _r.get("user_id") and int(_r.get("used") or 0) > 0:
                    _DAILY_RAM[(int(_r["user_id"]), _today_key())] = int(_r["used"])
            except Exception:
                continue

    # Quota-override backfill: personal limits survive restarts too.
    try:
        _qo_res = execute_d1_query_sync("SELECT user_id, limit_n FROM quota_overrides")
    except Exception:
        _qo_res = {"success": False, "results": []}
    if _qo_res.get("success"):
        for _r in (_qo_res.get("results") or []):
            try:
                _n = int(_r.get("limit_n") or 0)
                if _r.get("user_id") and 1 <= _n <= 10000:
                    _QUOTA_OVERRIDES[int(_r["user_id"])] = _n
            except Exception:
                continue

    logger.info(f"D1 Synced: {len(_MEMORY_DIRECTIVES)} perpetual directives, {len(_BANNED_USERS)} banned users, {len(_ACTIVE_GROUPS)} active groups.")

async def sync_memory_from_d1_async():
    """Continuously refreshes perpetual memory, ban list, and tracked groups from Cloudflare D1."""
    # Only rebound names need `global` (_USERNAME_TO_ID_MAP/_ACTIVE_GROUPS are mutated in place).
    global _MEMORY_DIRECTIVES, _BANNED_USERS, _BANNED_USERNAMES
    mem_res = await execute_d1_query("SELECT directive FROM admin_memories ORDER BY id ASC")
    if mem_res["success"]:
        _MEMORY_DIRECTIVES = [row["directive"] for row in mem_res["results"] if "directive" in row]

    ban_res = await execute_d1_query("SELECT user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title, banned_at FROM banned_users")
    if ban_res["success"]:
        for row in ban_res["results"]:
            uid = row.get("user_id")
            if uid:
                uid_int = int(uid)
                _BANNED_USERS.add(uid_int)
                _BANNED_DETAILS[uid_int] = row
            u = (row.get("username") or "").lower().lstrip("@")
            if u:
                _BANNED_USERNAMES.add(u)

    map_res = await execute_d1_query("SELECT username, user_id FROM user_mappings")
    if map_res["success"]:
        for r in map_res["results"]:
            if r.get("username") and r.get("user_id"):
                _USERNAME_TO_ID_MAP[r["username"].lower().lstrip("@")] = r["user_id"]

    group_res = await execute_d1_query("SELECT chat_id, title, chat_type, member_count, added_by, added_at, username, invite_link, status FROM tracked_groups")
    if group_res.get("success"):
        for g in group_res["results"]:
            try:
                _cid = g.get("chat_id")
                if _cid is None:
                    continue
                _ACTIVE_GROUPS[int(_cid)] = g
                if str(g.get("status") or "active") == "pending":
                    _PENDING_GROUPS.add(int(_cid))
            except Exception:
                continue

# --- Tracked Groups Management ---

async def track_group_presence_async(chat_id: int, title: str, chat_type: str = "supergroup", added_by: int = 0, username: str = "", invite_link: str = "", status: str = "pending"):
    clean_chat_id = int(chat_id)
    clean_by = int(added_by or 0)
    # Never auto-approve unless explicitly added or approved by the Master Admin
    if status == "active" and clean_by != ADMIN_ID and clean_by != 0:
        clean_status = "pending"
    else:
        clean_status = (status or "pending").strip().lower() or "pending"
    if clean_by == ADMIN_ID:
        clean_status = "active"
    if clean_status not in ("active", "pending", "left"):
        clean_status = "pending"
    _ACTIVE_GROUPS[clean_chat_id] = {
        "chat_id": clean_chat_id,
        "title": title,
        "chat_type": chat_type,
        "username": username or "",
        "invite_link": invite_link or "",
        "status": clean_status,
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    if clean_status == "pending":
        _PENDING_GROUPS.add(clean_chat_id)
    else:
        _PENDING_GROUPS.discard(clean_chat_id)
    await execute_d1_query(
        "INSERT OR REPLACE INTO tracked_groups (chat_id, title, chat_type, added_by, username, invite_link, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [clean_chat_id, title, chat_type, clean_by, username or "", invite_link or "", clean_status]
    )

async def set_group_status_async(chat_id: int, status: str) -> bool:
    """Mark a tracked group active/pending/left in RAM + D1. Never deletes."""
    try:
        clean_chat_id = int(chat_id)
    except Exception:
        return False
    clean_status = (status or "").strip().lower()
    if clean_status not in ("active", "pending", "left"):
        return False
    rec = _ACTIVE_GROUPS.get(clean_chat_id) or {"chat_id": clean_chat_id, "title": ""}
    rec["status"] = clean_status
    _ACTIVE_GROUPS[clean_chat_id] = rec
    if clean_status == "pending":
        _PENDING_GROUPS.add(clean_chat_id)
    else:
        _PENDING_GROUPS.discard(clean_chat_id)
    res = await execute_d1_query(
        "UPDATE tracked_groups SET status = ? WHERE chat_id = ?", [clean_status, clean_chat_id]
    )
    if res.get("success"):
        return True
    # Row may not exist yet (RAM-only tracking) — insert a minimal row instead.
    ins = await execute_d1_query(
        "INSERT OR IGNORE INTO tracked_groups (chat_id, title, status) VALUES (?, ?, ?)",
        [clean_chat_id, str(rec.get("title") or ""), clean_status]
    )
    return bool(ins.get("success"))

def is_group_approved(chat_id: int) -> bool:
    """Sync RAM check: is this group explicitly approved and ACTIVE by Master Admin?"""
    try:
        cid = int(chat_id)
        if cid in _PENDING_GROUPS:
            return False
        rec = _ACTIVE_GROUPS.get(cid)
        return bool(rec and rec.get("status") == "active")
    except Exception:
        return False

def is_group_pending(chat_id: int) -> bool:
    """Sync RAM check: is this chat awaiting admin activation?"""
    try:
        cid = int(chat_id)
        if cid in _PENDING_GROUPS:
            return True
        rec = _ACTIVE_GROUPS.get(cid)
        if not rec or rec.get("status") != "active":
            return True
        return False
    except Exception:
        return True

async def remove_group_presence_async(chat_id: int, purge_messages: bool = False):
    """
    Mark a group as LEFT on exit/kick. Group info and message history are
    PRESERVED in D1 by design (purge_messages defaults to False; pass True
    only for an explicit privacy wipe).
    """
    clean_chat_id = int(chat_id)
    await set_group_status_async(clean_chat_id, "left")

    # Wipe RAM context history for this group (memory only, D1 untouched)
    for k in (clean_chat_id, chat_id, str(chat_id), str(clean_chat_id)):
        if k in _CHAT_HISTORIES:
            del _CHAT_HISTORIES[k]

    # 3. Only on explicit request: permanently delete stored chat records from D1
    if purge_messages:
        await execute_d1_query("DELETE FROM messages WHERE chat_id = ?", [clean_chat_id])
        logger.info(f"Group {clean_chat_id} messages purged from Cloudflare D1 and RAM.")

# ============================================================================
# Daily per-user quota (global scale, 24h auto-reset via UTC day buckets).
# Hot path is pure RAM (sub-ms, no network); D1 persists counts and backfills
# them at startup, so restarts never grant free quota. No cron needed — the
# day key rolls over automatically at 00:00 UTC.
# ============================================================================
_DAILY_RAM: Dict[tuple, int] = {}


def _today_key() -> str:
    try:
        return time.strftime("%Y-%m-%d", time.gmtime())
    except Exception:
        return "1970-01-01"


def seconds_until_daily_reset() -> int:
    """Seconds until next 00:00 UTC (when every user's quota auto-resets)."""
    try:
        now = time.time()
        day_start = now - (now % 86400)
        return int(day_start + 86400 - now)
    except Exception:
        return 3600


def _daily_prune() -> None:
    """Bound RAM: keep only today's buckets (same pattern as rate limiter)."""
    try:
        if len(_DAILY_RAM) <= 20000:
            return
        today = _today_key()
        for k in [k for k in _DAILY_RAM if k[1] != today]:
            del _DAILY_RAM[k]
    except Exception:
        pass


def get_daily_used(user_id: int) -> int:
    """Sync RAM read of today's consumed quota (0 on miss)."""
    try:
        return int(_DAILY_RAM.get((int(user_id), _today_key()), 0))
    except Exception:
        return 0


async def get_daily_usage_async(user_id: int) -> tuple:
    """(used, effective_limit) with D1 fallback when RAM missed (e.g. restart)."""
    try:
        uid = int(user_id)
    except Exception:
        return 0, DAILY_USER_LIMIT
    used = get_daily_used(uid)
    if used:
        return used, get_user_limit(uid)
    try:
        res = await execute_d1_query(
            "SELECT used FROM daily_usage WHERE user_id = ? AND day = ?",
            [uid, _today_key()],
        )
        if res.get("success") and res.get("results"):
            used = int(res["results"][0].get("used") or 0)
            if used > 0:
                _DAILY_RAM[(uid, _today_key())] = used
    except Exception:
        pass
    return used, get_user_limit(uid)


async def bump_daily_usage_async(user_id: int) -> tuple:
    """Consume one unit of today's quota. Returns (allowed, used, limit).

    D1 persistence is best-effort (graceful when Cloudflare is unreachable —
    RAM still enforces the limit for this process lifetime).
    """
    try:
        uid = int(user_id)
    except Exception:
        return True, 0, DAILY_USER_LIMIT
    _daily_prune()
    day = _today_key()
    used = get_daily_used(uid) + 1
    _DAILY_RAM[(uid, day)] = used
    limit = get_user_limit(uid)
    try:
        asyncio.create_task(execute_d1_query(
            "INSERT INTO daily_usage (user_id, day, used, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, day) DO UPDATE SET used = excluded.used, updated_at = CURRENT_TIMESTAMP",
            [uid, day, used],
        ))
    except Exception:
        pass
    return used <= limit, used, limit


# --- Per-user quota overrides (admin can raise/lower anyone's daily limit).
# Same architecture as daily_usage: RAM hot path + D1 persistence + startup
# backfill. Absent override => global DAILY_USER_LIMIT.
_QUOTA_OVERRIDES: Dict[int, int] = {}


def get_user_limit(user_id: int) -> int:
    """Effective daily limit for a user: personal override or global default."""
    try:
        return int(_QUOTA_OVERRIDES.get(int(user_id), DAILY_USER_LIMIT))
    except Exception:
        return DAILY_USER_LIMIT


async def set_user_quota_async(user_id: int, limit_n: int) -> bool:
    """Admin sets a personal daily quota (1..10000)."""
    try:
        uid = int(user_id)
        n = int(limit_n)
    except Exception:
        return False
    if n < 1 or n > 10000:
        return False
    _QUOTA_OVERRIDES[uid] = n
    try:
        await execute_d1_query(
            "INSERT INTO quota_overrides (user_id, limit_n, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET limit_n = excluded.limit_n, updated_at = CURRENT_TIMESTAMP",
            [uid, n],
        )
    except Exception:
        pass
    return True


async def adjust_user_quota_async(user_id: int, delta: int):
    """Admin nudges a personal quota by delta. Returns new limit or None."""
    try:
        d = int(delta)
    except Exception:
        return None
    if d == 0:
        return get_user_limit(user_id)
    new_n = get_user_limit(user_id) + d
    if new_n < 1 or new_n > 10000:
        return None
    ok = await set_user_quota_async(user_id, new_n)
    return new_n if ok else None


async def clear_user_quota_async(user_id: int) -> bool:
    """Admin removes a personal override (back to global default)."""
    try:
        uid = int(user_id)
    except Exception:
        return False
    _QUOTA_OVERRIDES.pop(uid, None)
    try:
        await execute_d1_query("DELETE FROM quota_overrides WHERE user_id = ?", [uid])
    except Exception:
        pass
    return True


async def get_all_tracked_groups_async() -> List[Dict[str, Any]]:
    try:
        res = await execute_d1_query("SELECT chat_id, title, chat_type, added_by, added_at, username, invite_link, status FROM tracked_groups ORDER BY added_at DESC")
    except Exception:
        res = {"success": False, "results": []}
    if not res.get("success"):
        res = await execute_d1_query("SELECT chat_id, title, chat_type, added_at FROM tracked_groups ORDER BY added_at DESC")
    if res["success"]:
        return res["results"]
    return list(_ACTIVE_GROUPS.values())

async def get_user_timezone_async(user_id: int, fallback_lang: str = "fa") -> str:
    """Gets configured timezone for user with multi-tier RAM + D1 + Language fallback."""
    uid = int(user_id or 0)
    if not uid:
        return "Asia/Tehran" if fallback_lang == "fa" else "UTC"
    if uid in _USER_TIMEZONES:
        return _USER_TIMEZONES[uid]
    res = await execute_d1_query("SELECT timezone FROM user_preferences WHERE user_id = ?", [uid])
    if res.get("success") and res.get("results"):
        tz = str(res["results"][0].get("timezone") or "").strip()
        if tz:
            _USER_TIMEZONES[uid] = tz
            return tz
    inferred = "Asia/Tehran" if fallback_lang == "fa" else "UTC"
    _USER_TIMEZONES[uid] = inferred
    return inferred

async def set_user_timezone_async(user_id: int, timezone_name: str) -> bool:
    """Saves user timezone to fast RAM and persists to D1."""
    uid = int(user_id or 0)
    clean_tz = str(timezone_name or "").strip()
    if not uid or not clean_tz:
        return False
    _USER_TIMEZONES[uid] = clean_tz
    res = await execute_d1_query(
        "INSERT INTO user_preferences (user_id, timezone) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET timezone = excluded.timezone, updated_at = CURRENT_TIMESTAMP",
        [uid, clean_tz]
    )
    return bool(res.get("success"))

# --- High-Performance Isolated Per-Group Chat Memory Engine ---

async def save_message_async(
    chat_id: int,
    user_id: int,
    role: str,
    content: str,
    user_name: str = "",
    username: str = "",
    chat_title: str = "",
    message_id: int = 0,
    chat_type: str = "",
    msg_kind: str = "text",
    reply_to_msg_id: int = 0,
    reply_to_user: str = "",
    reply_to_text: str = "",
    thread_id: int = 0,
    forward_from: str = "",
    sender_chat_id: int = 0,
    detected_lang: str = "",
    char_count: int = 0,
    has_media: int = 0,
    extra_meta: Optional[Union[Dict[str, Any], str]] = None,
):
    ensure_batch_worker()
    now_ts = time.time()
    clean_username = (username or "").strip().lower().lstrip("@")
    created_at_iso, time_str, j_date_str = get_tehran_timestamps()
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    clean_user_id = int(user_id) if isinstance(user_id, (int, str)) and str(user_id).lstrip("-").isdigit() else 0
    clean_thread_id = int(thread_id or 0)
    clean_fwd = str(forward_from or "")[:120]
    clean_sender_chat = int(sender_chat_id or 0)
    clean_lang = str(detected_lang or "")[:10]
    clean_chars = int(char_count) if char_count > 0 else len(str(content or ""))
    clean_media = int(has_media or 0)
    if isinstance(extra_meta, dict):
        clean_extra = json.dumps(extra_meta, ensure_ascii=False)
    else:
        clean_extra = str(extra_meta or "{}")

    # 1. Update In-Memory L1 Tracking
    if clean_chat_id < 0 and clean_chat_id not in _ACTIVE_GROUPS:
        asyncio.create_task(track_group_presence_async(clean_chat_id, chat_title or "گروه ناشناس", status="pending"))

    if clean_username and user_id:
        prev_uid = _USERNAME_TO_ID_MAP.get(clean_username)
        _USERNAME_TO_ID_MAP[clean_username] = user_id
        if prev_uid != user_id:
            try:
                asyncio.create_task(
                    execute_d1_query(
                        "INSERT OR REPLACE INTO user_mappings (username, user_id) VALUES (?, ?)",
                        [clean_username, int(user_id)]
                    )
                )
            except RuntimeError:
                pass

    # Ultra-Fast Per-Chat Isolated Display Name Indexing (Prevents cross-group identity collisions)
    clean_display = str(user_name or "").strip()
    if clean_display and clean_user_id:
        norm_key = re.sub(r"[\s_\-\.]+", " ", clean_display).lower().strip()
        user_identity_obj = {
            "user_id": clean_user_id,
            "display_name": clean_display,
            "username": clean_username,
            "chat_id": clean_chat_id,
            "chat_title": chat_title,
            "updated_at": created_at_iso
        }
        if clean_chat_id not in _CHAT_DISPLAY_NAMES:
            if len(_CHAT_DISPLAY_NAMES) > 300:
                for k in list(_CHAT_DISPLAY_NAMES.keys())[:50]:
                    _CHAT_DISPLAY_NAMES.pop(k, None)
            _CHAT_DISPLAY_NAMES[clean_chat_id] = {}
        _CHAT_DISPLAY_NAMES[clean_chat_id][norm_key] = user_identity_obj

        if len(_DISPLAY_NAME_TO_ID_MAP) > 2000:
            for k in list(_DISPLAY_NAME_TO_ID_MAP.keys())[:500]:
                _DISPLAY_NAME_TO_ID_MAP.pop(k, None)
        _DISPLAY_NAME_TO_ID_MAP[norm_key] = user_identity_obj

    # Invalidate search memo for this specific chat so search is always fresh
    if _SEARCH_MEMO.get("cache") and clean_chat_id:
        _pfx = f"{clean_chat_id}|"
        stale_keys = [k for k in _SEARCH_MEMO["cache"] if k.startswith(_pfx)]
        for sk in stale_keys:
            _SEARCH_MEMO["cache"].pop(sk, None)

    # 2. Update RAM context immediately for sub-millisecond turn continuity.
    # Key is ALWAYS the normalized int chat_id: per-group isolation depends on it.
    if clean_chat_id not in _CHAT_HISTORIES:
        _CHAT_HISTORIES[clean_chat_id] = []

    _clean_kind = (msg_kind or "text").strip().lower() or "text"
    _clean_ctype = (chat_type or "").strip().lower()
    _ram_content = content[:2000] if (isinstance(content, str) and len(content) > 2000) else content
    _CHAT_HISTORIES[clean_chat_id].append({
        "role": role,
        "content": _ram_content,
        "user_id": clean_user_id,
        "message_id": int(message_id or 0),
        "user_name": user_name,
        "username": clean_username,
        "chat_title": chat_title,
        "chat_type": _clean_ctype,
        "msg_kind": _clean_kind,
        "reply_to_msg_id": int(reply_to_msg_id or 0),
        "reply_to_user": (reply_to_user or "")[:80],
        "reply_to_text": (reply_to_text or "")[:200],
        "thread_id": clean_thread_id,
        "forward_from": clean_fwd,
        "sender_chat_id": clean_sender_chat,
        "detected_lang": clean_lang,
        "char_count": clean_chars,
        "has_media": clean_media,
        "extra_meta": clean_extra,
        "msg_date": j_date_str,
        "msg_time": time_str,
        "time": now_ts
    })
    
    # Rolling Window: Strictly up to 30 last messages per group in isolated RAM buffer.
    try:
        from src.core.config import MAX_RAM_TURNS_PER_CHAT as _MAX_TURNS
    except Exception:
        _MAX_TURNS = 30
    if len(_CHAT_HISTORIES[clean_chat_id]) > _MAX_TURNS:
        _CHAT_HISTORIES[clean_chat_id] = _CHAT_HISTORIES[clean_chat_id][-_MAX_TURNS:]

    # Global RAM Guard: Prevent unbounded chat growth across hundreds of groups
    if len(_CHAT_HISTORIES) > 150:
        chats_by_recency = sorted(
            _CHAT_HISTORIES.keys(),
            key=lambda cid: (_CHAT_HISTORIES[cid][-1].get("time", 0) if _CHAT_HISTORIES[cid] else 0)
        )
        for cid in chats_by_recency[:40]:
            _CHAT_HISTORIES.pop(cid, None)

    # 3. Push to High-Speed Write-Behind Queue (zero HTTP blocking).
    msg_record = {
        "chat_id": clean_chat_id,
        "user_id": clean_user_id,
        "message_id": int(message_id or 0),
        "user_name": str(user_name or ("Assistant" if role == "assistant" else "User")),
        "username": clean_username,
        "chat_title": str(chat_title),
        "chat_type": _clean_ctype,
        "msg_kind": _clean_kind,
        "reply_to_msg_id": int(reply_to_msg_id or 0),
        "reply_to_user": str(reply_to_user or "")[:80],
        "reply_to_text": str(reply_to_text or "")[:200],
        "role": str(role),
        "content": str(content),
        "msg_date": j_date_str,
        "msg_time": time_str,
        "created_at": created_at_iso,
        "thread_id": clean_thread_id,
        "forward_from": clean_fwd,
        "sender_chat_id": clean_sender_chat,
        "detected_lang": clean_lang,
        "char_count": clean_chars,
        "has_media": clean_media,
        "extra_meta": clean_extra,
    }

    try:
        _D1_WRITE_QUEUE.put_nowait(msg_record)
    except Exception:
        # Direct fallback if queue full
        try:
            asyncio.create_task(_flush_batch_to_d1([msg_record]))
        except RuntimeError:
            pass


async def get_recent_message_ids_for_purge_async(
    chat_id: int,
    count: int = 10,
    only_bot: bool = True
) -> List[int]:
    """
    Returns message_ids in reverse chronological order (newest first).
    If only_bot is True, returns only assistant messages.
    Checks RAM first, then D1 database if needed.
    """
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    if not clean_chat_id:
        return []

    target_count = max(1, min(100, int(count)))
    collected: List[int] = []
    seen = set()

    # 1. Inspect in-memory RAM buffer
    if clean_chat_id in _CHAT_HISTORIES and _CHAT_HISTORIES[clean_chat_id]:
        for m in reversed(_CHAT_HISTORIES[clean_chat_id]):
            mid = int(m.get("message_id") or 0)
            role = str(m.get("role") or "").lower()
            if mid > 0 and mid not in seen:
                if not only_bot or role == "assistant":
                    collected.append(mid)
                    seen.add(mid)
                    if len(collected) >= target_count:
                        return collected

    # 2. Query D1 database if RAM did not have enough
    if len(collected) < target_count:
        needed = target_count - len(collected)
        try:
            cond = "AND role = 'assistant'" if only_bot else ""
            sql = f"SELECT message_id FROM messages WHERE chat_id = ? {cond} AND message_id > 0 ORDER BY id DESC LIMIT ?"
            d1_rows = await execute_d1_query(sql, [clean_chat_id, needed + 10])
            for r in d1_rows:
                mid = int(r.get("message_id") or 0)
                if mid > 0 and mid not in seen:
                    collected.append(mid)
                    seen.add(mid)
                    if len(collected) >= target_count:
                        break
        except Exception as e:
            logger.debug(f"D1 message ids query error: {e}")

    return collected


async def purge_messages_from_db_and_ram_async(chat_id: int, message_ids: List[int]) -> int:
    """Removes given message IDs from both in-memory buffer and D1 persistent storage."""
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    if not clean_chat_id or not message_ids:
        return 0

    id_set = set(int(mid) for mid in message_ids if int(mid) > 0)
    if not id_set:
        return 0

    # 1. Clean from in-memory RAM
    if clean_chat_id in _CHAT_HISTORIES and _CHAT_HISTORIES[clean_chat_id]:
        _CHAT_HISTORIES[clean_chat_id] = [
            m for m in _CHAT_HISTORIES[clean_chat_id]
            if int(m.get("message_id") or 0) not in id_set
        ]

    # 2. Clean from D1 database
    try:
        placeholders = ",".join("?" for _ in id_set)
        sql = f"DELETE FROM messages WHERE chat_id = ? AND message_id IN ({placeholders})"
        await execute_d1_query(sql, [clean_chat_id, *list(id_set)])
    except Exception as e:
        logger.debug(f"D1 purge deletion error: {e}")

    return len(id_set)

async def get_chat_context_async(chat_id: int, max_tokens: int = 20000) -> List[Dict[str, Any]]:
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    if not clean_chat_id:
        return []

    # 1. Zero-Cost RAM Hit (Zero Cloudflare API calls, sub-microsecond latency)
    if clean_chat_id in _CHAT_HISTORIES and _CHAT_HISTORIES[clean_chat_id]:
        selected = []
        token_count = 0
        for m in reversed(_CHAT_HISTORIES[clean_chat_id]):
            t_len = len(m.get("content", "")) // 3
            if token_count + t_len > max_tokens:
                break
            selected.append(m)
            token_count += t_len
        return list(reversed(selected))

    # 2. Cold Miss: Fetch from Cloudflare D1 with strict per-chat isolation and 30-message rolling window
    try:
        from src.core.config import MAX_RAM_TURNS_PER_CHAT as _MAX_TURNS
    except Exception:
        _MAX_TURNS = 30

    res = await execute_d1_query(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        [clean_chat_id, _MAX_TURNS]
    )
    if res["success"] and res["results"]:
        msgs = list(reversed(res["results"]))
        _CHAT_HISTORIES[clean_chat_id] = msgs
        return msgs
    return []

def clear_chat_context(chat_id: int):
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    # Wipe RAM under every plausible key form so no stale turns survive
    for k in (clean_chat_id, chat_id, str(chat_id), str(clean_chat_id)):
        if k in _CHAT_HISTORIES:
            _CHAT_HISTORIES[k] = []
    try:
        asyncio.create_task(execute_d1_query("DELETE FROM messages WHERE chat_id = ?", [clean_chat_id]))
    except RuntimeError:
        pass


async def get_recent_messages_for_summary_async(chat_id: int, count: int = 50) -> List[Dict[str, Any]]:
    """
    Fetches up to `count` (typically 50 or 100) recent messages from RAM and Cloudflare D1
    specifically for group chat summarization. Returns clean, chronological list.
    """
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    if not clean_chat_id:
        return []

    target_count = max(5, min(120, int(count or 50)))

    # 1. Inspect RAM buffer first
    ram_msgs = list(_CHAT_HISTORIES.get(clean_chat_id, []))
    if len(ram_msgs) >= target_count:
        return ram_msgs[-target_count:]

    # 2. If RAM has fewer than target_count, fetch from Cloudflare D1
    try:
        res = await execute_d1_query(
            f"SELECT {_MESSAGE_COLS} FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            [clean_chat_id, target_count]
        )
        if res.get("success") and res.get("results"):
            d1_msgs = list(reversed(res["results"]))
            # Combine D1 messages and any newer RAM messages
            seen_mids = {int(m.get("message_id") or 0) for m in d1_msgs if int(m.get("message_id") or 0) > 0}
            combined = list(d1_msgs)
            for rm in ram_msgs:
                rmid = int(rm.get("message_id") or 0)
                if rmid > 0 and rmid in seen_mids:
                    continue
                combined.append(rm)

            # Update RAM with the combined set up to 120
            _CHAT_HISTORIES[clean_chat_id] = combined[-120:]
            return combined[-target_count:]
    except Exception as e:
        logger.warning(f"Error fetching messages from D1 for summary: {e}")

    return ram_msgs[-target_count:] if ram_msgs else []


def format_messages_for_summary(messages: List[Dict[str, Any]]) -> str:
    """
    Transforms raw message records into a structured, easily consumable text transcript
    for AI summarization.
    """
    if not messages:
        return ""
    lines = []
    for idx, m in enumerate(messages, 1):
        role = m.get("role", "user")
        sender = m.get("user_name") or m.get("username") or ("ربات" if role == "assistant" else "کاربر")
        time_tag = ""
        if m.get("msg_time"):
            time_tag = f"[{m.get('msg_time')}] "
        elif m.get("created_at"):
            time_tag = f"[{str(m.get('created_at'))[11:16]}] "

        kind_tag = ""
        mkind = str(m.get("msg_kind") or "text").lower()
        if mkind not in ("text", "command"):
            kind_tag = f"[{mkind}] "

        content = str(m.get("content") or "").strip()
        if not content and m.get("has_media"):
            content = f"[{mkind}]"
        # Sanitize newlines inside a single message to keep transcript compact
        content_clean = content.replace("\n", " ")[:300]
        if content_clean:
            lines.append(f"{idx}. {time_tag}{sender}: {kind_tag}{content_clean}")
    return "\n".join(lines)

# --- Multi-Strategy Deep Semantic Search in Cloudflare D1 ---

_SEARCH_MEMO: Dict[str, Any] = {"cache": {}, "order": []}
_SEARCH_MEMO_MAX = 200


def _search_memo_get(key: str) -> Optional[List[Dict[str, Any]]]:
    try:
        hit = _SEARCH_MEMO["cache"].get(key)
        if hit is not None and (time.time() - hit[0]) < 45.0:
            return hit[1]
    except Exception:
        pass
    return None


def _search_memo_put(key: str, val: List[Dict[str, Any]]) -> None:
    try:
        _SEARCH_MEMO["cache"][key] = (time.time(), val)
        _SEARCH_MEMO["order"].append(key)
        while len(_SEARCH_MEMO["order"]) > _SEARCH_MEMO_MAX:
            _SEARCH_MEMO["cache"].pop(_SEARCH_MEMO["order"].pop(0), None)
    except Exception:
        pass


async def search_group_memory(
    chat_id: int,
    query: str,
    user_identifier: Optional[str] = None,
    limit: int = 10,
    msg_date: Optional[str] = None,
    msg_kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lightning-Fast Multi-Tier Memory Search Engine (v2):
    1. Tier 1: Zero-latency (<0.001s) scored search in Hot In-Memory Buffer.
    2. Tier 2: Cloudflare D1 FTS5 full-text search, LIKE fallback on old DBs.
    Filters: user_identifier (id/@username/display name), msg_date (YYYY-MM-DD
    or شمسی YYYY/MM/DD), msg_kind (text/voice/photo/video/file/...).
    Results are relevance-scored (phrase > all-tokens > any-token) and the
    final merge is memoized for 45s.
    """
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    if not clean_chat_id:
        return []
    clean_q = (query or "").strip().lower()
    if not clean_q:
        return []

    words = [w.lower() for w in clean_q.split() if len(w) > 1]
    tokens = words or [clean_q]
    _memo_key = f"{clean_chat_id}|{clean_q}|{user_identifier or ''}|{msg_date or ''}|{msg_kind or ''}|{limit}"
    _memo_hit = _search_memo_get(_memo_key)
    if _memo_hit is not None:
        return _memo_hit

    target_uid = None
    if user_identifier:
        uid, _ = await resolve_target_identifier(user_identifier)
        target_uid = uid

    def _score(m: Dict[str, Any]) -> float:
        c = str(m.get("content", "")).lower()
        u_name = str(m.get("user_name", "")).lower()
        u_nick = str(m.get("username", "")).lower()
        hay = f"{c} {u_name} {u_nick}"
        if clean_q in hay:
            return 3.0 + sum(1 for t in tokens if t in hay) * 0.2
        hits = sum(1 for tok in tokens if tok in hay)
        if hits == len(tokens):
            return 2.0
        if hits:
            return 1.0 * hits / max(1, len(tokens))
        return 0.0

    def _passes_filters(m: Dict[str, Any]) -> bool:
        if target_uid and m.get("user_id") != target_uid:
            return False
        if msg_date and str(m.get("msg_date", "")) != str(msg_date):
            return False
        if msg_kind and str(m.get("msg_kind", "text")).lower() != str(msg_kind).lower():
            return False
        return True

    # --- Tier 1: Ultra-Fast In-Memory RAM Search (scored, sub-millisecond) ---
    ram_matches: List[Dict[str, Any]] = []
    if clean_chat_id != 0 and clean_chat_id in _CHAT_HISTORIES:
        _scored = []
        for m in reversed(_CHAT_HISTORIES[clean_chat_id]):
            if not _passes_filters(m):
                continue
            s = _score(m)
            if s > 0:
                _scored.append((s, m))
        _scored.sort(key=lambda x: x[0], reverse=True)
        ram_matches = [m for _, m in _scored[:limit]]

    if len(ram_matches) >= limit:
        _search_memo_put(_memo_key, ram_matches)
        return ram_matches

    # --- Tier 2: Cloudflare D1 FTS5 full-text search (LIKE fallback) ---
    where_parts = []
    params: List[Any] = []

    _fts_rows: List[Dict[str, Any]] = []
    _fts_ok = False
    try:
        fts_where_parts = ["m.chat_id = ?"]
        fts_params = [clean_chat_id]
        if target_uid:
            fts_where_parts.append("m.user_id = ?")
            fts_params.append(target_uid)
        if msg_date:
            fts_where_parts.append("m.msg_date = ?")
            fts_params.append(str(msg_date))
        if msg_kind:
            fts_where_parts.append("m.msg_kind = ?")
            fts_params.append(str(msg_kind).lower())

        _fts_q = " ".join(f'"{w.replace(chr(34), "")}"' for w in tokens[:6]) or f'"{clean_q.replace(chr(34), "")}"'
        _fts_where = " AND ".join(fts_where_parts)
        _fts_where_sql = f"AND {_fts_where}" if _fts_where else ""
        _fts_sql = (
            "SELECT m.role, m.user_name, m.username, m.user_id, m.chat_title, m.chat_type, m.msg_kind, "
            "m.reply_to_msg_id, m.reply_to_user, m.reply_to_text, m.content, m.msg_date, m.msg_time, m.created_at, "
            "m.thread_id, m.forward_from, m.sender_chat_id, m.detected_lang, m.char_count, m.has_media, m.extra_meta "
            "FROM messages_fts f JOIN messages m ON m.rowid = f.rowid "
            f"WHERE messages_fts MATCH ? {_fts_where_sql} ORDER BY m.id DESC LIMIT ?"
        )
        _res = await execute_d1_query(_fts_sql, [_fts_q] + fts_params + [limit])
        if _res.get("success") and _res.get("results"):
            _fts_rows = _res["results"]
            _fts_ok = True
    except Exception as _e:
        logger.debug(f"FTS query fallback: {_e}")
        _fts_ok = False

    if not _fts_ok:
        where_parts.append("chat_id = ?")
        params.append(clean_chat_id)
        if target_uid:
            where_parts.append("user_id = ?")
            params.append(target_uid)
        if msg_date:
            where_parts.append("msg_date = ?")
            params.append(str(msg_date))
        if msg_kind:
            where_parts.append("msg_kind = ?")
            params.append(str(msg_kind).lower())

        if len(words) > 1:
            like_clauses = " AND ".join(["(content LIKE ? OR user_name LIKE ? OR username LIKE ? OR reply_to_text LIKE ?)" for _ in words])
            where_parts.append(f"({like_clauses})")
            for w in words:
                pattern = f"%{w}%"
                params.extend([pattern, pattern, pattern, pattern])
        elif clean_q:
            where_parts.append("(content LIKE ? OR user_name LIKE ? OR username LIKE ? OR reply_to_text LIKE ?)")
            pattern = f"%{clean_q}%"
            params.extend([pattern, pattern, pattern, pattern])

        where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        sql = ("SELECT role, user_name, username, user_id, chat_title, chat_type, msg_kind, reply_to_msg_id, "
               "reply_to_user, reply_to_text, content, msg_date, msg_time, created_at, "
               "thread_id, forward_from, sender_chat_id, detected_lang, char_count, has_media, extra_meta "
               f"FROM messages {where_sql} ORDER BY id DESC LIMIT ?")
        params.append(limit)

        res = await execute_d1_query(sql, params)
        if res["success"] and res["results"]:
            _fts_rows = res["results"]

    if _fts_rows:
        # Merge RAM + D1 matches by relevance score, avoiding duplicates
        seen_texts = {m.get("content") for m in ram_matches}
        _pool = list(ram_matches) + [r for r in _fts_rows if r.get("content") not in seen_texts]
        _pool_scored = [(_score(m), m) for m in _pool]
        _pool_scored.sort(key=lambda x: x[0], reverse=True)
        merged = [m for _, m in _pool_scored[:limit]]
        _search_memo_put(_memo_key, merged)
        return merged

    _search_memo_put(_memo_key, ram_matches)
    return ram_matches

# --- Cloudflare D1 Permanent Custom Data Store (Store / Retrieve / Search) ---

# In-Memory Hot L1 RAM index for Custom Records
_CUSTOM_RECORDS_L1: Dict[str, Dict[str, Any]] = {}

async def store_custom_record_d1(key_name: str, data_value: str, category: str = "general") -> bool:
    clean_k = key_name.strip().replace(" ", "_").lower()
    created_iso, _, _ = get_tehran_timestamps()
    if len(_CUSTOM_RECORDS_L1) > 1000:
        for ek in list(_CUSTOM_RECORDS_L1.keys())[:200]:
            del _CUSTOM_RECORDS_L1[ek]

    _CUSTOM_RECORDS_L1[clean_k] = {
        "key_name": clean_k,
        "data_value": str(data_value),
        "category": str(category),
        "updated_at": created_iso
    }
    sql = "INSERT OR REPLACE INTO custom_data_store (key_name, data_value, category, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)"
    res = await execute_d1_query(sql, [clean_k, data_value, category])
    await kv_set_cache_async(f"D1_STORE_{clean_k}", data_value, expiration_ttl=86400 * 7)
    return res.get("success", False)

async def delete_custom_record_d1(key_name: str) -> bool:
    clean_k = key_name.strip().replace(" ", "_").lower()
    if clean_k in _CUSTOM_RECORDS_L1:
        del _CUSTOM_RECORDS_L1[clean_k]
    l1_delete(f"D1_STORE_{clean_k}")
    # Also invalidate cloud KV entry if configured
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_KV_ID:
        try:
            client = get_cf_client()
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{CLOUDFLARE_KV_ID}/values/D1_STORE_{clean_k}"
            await client.delete(url, headers=_cf_headers(), timeout=3.5)
        except Exception as e:
            logger.debug(f"KV delete error for {clean_k}: {e}")
    sql = "DELETE FROM custom_data_store WHERE key_name = ?"
    res = await execute_d1_query(sql, [clean_k])
    return res.get("success", False)

async def list_custom_records_d1(category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    if category:
        sql = "SELECT key_name, data_value, category, updated_at FROM custom_data_store WHERE category = ? ORDER BY id DESC LIMIT ?"
        res = await execute_d1_query(sql, [category, limit])
    else:
        sql = "SELECT key_name, data_value, category, updated_at FROM custom_data_store ORDER BY id DESC LIMIT ?"
        res = await execute_d1_query(sql, [limit])
    if res.get("success") and res.get("results"):
        return res["results"]
    return list(_CUSTOM_RECORDS_L1.values())[:limit]

async def retrieve_custom_record_d1(key_name: str) -> Optional[str]:
    clean_k = key_name.strip().replace(" ", "_").lower()
    if clean_k in _CUSTOM_RECORDS_L1:
        return _CUSTOM_RECORDS_L1[clean_k]["data_value"]

    cached = await kv_get_cache_async(f"D1_STORE_{clean_k}")
    if cached is not None:
        _CUSTOM_RECORDS_L1[clean_k] = {"key_name": clean_k, "data_value": cached, "category": "general", "updated_at": ""}
        return cached

    sql = "SELECT data_value, category, updated_at FROM custom_data_store WHERE key_name = ? LIMIT 1"
    res = await execute_d1_query(sql, [clean_k])
    if res["success"] and res["results"]:
        row = res["results"][0]
        val = row.get("data_value")
        if val is not None:
            val_str = str(val)
            _CUSTOM_RECORDS_L1[clean_k] = {
                "key_name": clean_k,
                "data_value": val_str,
                "category": row.get("category", "general"),
                "updated_at": row.get("updated_at", "")
            }
            await kv_set_cache_async(f"D1_STORE_{clean_k}", val_str, expiration_ttl=86400 * 7)
            return val_str
    return None

async def search_custom_records_d1(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    clean_q = query.strip().lower()
    if not clean_q:
        return []

    # 1. Zero-latency search in Hot L1 RAM
    ram_hits = []
    for k, record in _CUSTOM_RECORDS_L1.items():
        if clean_q in k or clean_q in record.get("data_value", "").lower() or clean_q in record.get("category", "").lower():
            ram_hits.append(record)
            if len(ram_hits) >= limit:
                break

    if len(ram_hits) > 0:
        return ram_hits

    # 2. Serverless SQL search in Cloudflare D1
    sql = "SELECT key_name, data_value, category, updated_at FROM custom_data_store WHERE key_name LIKE ? OR data_value LIKE ? ORDER BY id DESC LIMIT ?"
    res = await execute_d1_query(sql, [f"%{clean_q}%", f"%{clean_q}%", limit])
    if res["success"] and res["results"]:
        for r in res["results"]:
            _CUSTOM_RECORDS_L1[r["key_name"]] = r
        # Merge RAM and D1 results cleanly
        seen_keys = {m["key_name"] for m in ram_hits}
        merged = list(ram_hits)
        for r in res["results"]:
            if r["key_name"] not in seen_keys:
                seen_keys.add(r["key_name"])
                merged.append(r)
                if len(merged) >= limit:
                    break
        return merged
    return ram_hits

# --- Admin Perpetual Memory & Directives ---

async def add_admin_memory_async(directive: str) -> bool:
    """
    Instantly updates active RAM directives (0.001ms) so the model immediately
    obeys the new order on the very next token, then persists to Cloudflare D1.
    """
    clean_d = directive.strip()
    if not clean_d:
        return False
    if clean_d not in _MEMORY_DIRECTIVES:
        _MEMORY_DIRECTIVES.append(clean_d)
    # Also mirror into KV for high-speed multi-instance synchronization
    await kv_set_cache_async("D1_ADMIN_DIRECTIVES_BLOB", json.dumps(_MEMORY_DIRECTIVES, ensure_ascii=False), expiration_ttl=86400 * 30)
    res = await execute_d1_query("INSERT OR REPLACE INTO admin_memories (directive) VALUES (?)", [clean_d])
    return res.get("success", False)

def add_admin_memory(directive: str) -> bool:
    clean_d = directive.strip()
    if not clean_d:
        return False
    if clean_d not in _MEMORY_DIRECTIVES:
        _MEMORY_DIRECTIVES.append(clean_d)
    execute_d1_query_sync("INSERT OR REPLACE INTO admin_memories (directive) VALUES (?)", [clean_d])
    return True

async def remove_admin_memory_async(directive: str) -> bool:
    clean_d = directive.strip()
    matched = [m for m in _MEMORY_DIRECTIVES if clean_d in m or m in clean_d]
    for m in (matched or [clean_d]):
        if m in _MEMORY_DIRECTIVES:
            _MEMORY_DIRECTIVES.remove(m)
    await kv_set_cache_async("D1_ADMIN_DIRECTIVES_BLOB", json.dumps(_MEMORY_DIRECTIVES, ensure_ascii=False), expiration_ttl=86400 * 30)
    # First attempt exact deletion to avoid SQLite LIKE pattern complexity limits on long strings
    res = await execute_d1_query("DELETE FROM admin_memories WHERE directive = ?", [clean_d])
    if not res.get("success") or (res.get("meta", {}).get("changes", 0) == 0 and matched):
        # Delete matched directives directly by exact value
        for m in matched:
            res = await execute_d1_query("DELETE FROM admin_memories WHERE directive = ?", [m])
    return res.get("success", False)

def remove_admin_memory(directive: str) -> bool:
    clean_d = directive.strip()
    matched = [m for m in _MEMORY_DIRECTIVES if clean_d in m or m in clean_d]
    for m in (matched or [clean_d]):
        if m in _MEMORY_DIRECTIVES:
            _MEMORY_DIRECTIVES.remove(m)
    execute_d1_query_sync("DELETE FROM admin_memories WHERE directive = ?", [clean_d])
    if matched:
        for m in matched:
            execute_d1_query_sync("DELETE FROM admin_memories WHERE directive = ?", [m])
    return True

def get_all_admin_memories() -> List[str]:
    return list(_MEMORY_DIRECTIVES)

# --- Advanced Moderation & User/Username Management ---

def normalize_identity_str(text: str) -> str:
    """Normalizes Persian/Arabic variations, ZWNJ, and spacing for ultra-robust identity matching."""
    if not text:
        return ""
    t = str(text).strip()
    # Arabic to Persian characters
    t = t.replace("ي", "ی").replace("ك", "ک").replace("ة", "ه").replace("ۀ", "ه")
    # Invisible zero-width chars / ZWNJ
    for z in ("\u200c", "\u200b", "\u200d", "\ufeff", "\u00ad"):
        t = t.replace(z, " ")
    # Replace punctuation and special dividers with space
    t = re.sub(r"[\s_\-\.:;,/\\|]+", " ", t).strip().lower()
    return t


async def _probe_live_telegram_chat(target: Union[int, str]):
    """Best-effort live profile lookup from Telegram Bot API."""
    try:
        from src.tools.admin import group_manager as _gm
        bot = _gm.get_bot_instance()
        if not bot:
            return None
        return await bot.get_chat(target)
    except Exception:
        return None


async def resolve_target_full_identity(identifier: str, chat_id: int = 0) -> Dict[str, Any]:
    """
    Super-Charged Multi-Strategy Telegram Identity Resolver.
    Resolves:
      - Numeric user ID (e.g. 123456789)
      - Telegram @username (with or without @)
      - Display name / real name (Persian, Latin, partial, normalized)
      - Live Telegram Bot API probe via get_chat(user_id / @username) if bot context exists.
    Returns rich dict:
      user_id, username, first_name, last_name, display_name, chat_id, chat_title,
      last_seen, msg_count, is_banned, is_muted, bio, candidates (if multiple matches).
    """
    clean_id = str(identifier or "").strip()
    clean_cid = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    res: Dict[str, Any] = {
        "user_id": None,
        "username": None,
        "first_name": None,
        "last_name": None,
        "display_name": None,
        "chat_id": None,
        "chat_title": None,
        "last_seen": None,
        "msg_count": 0,
        "is_banned": False,
        "is_muted": False,
        "bio": None,
        "candidates": []
    }
    if not clean_id:
        return res

    # 1. Direct Numeric ID Check
    if clean_id.lstrip("-").isdigit():
        uid = int(clean_id)
        res["user_id"] = uid
        res["is_banned"] = is_user_banned(uid)
        res["is_muted"] = (is_user_muted(uid) > 0)

        # Check in-memory maps
        for u, i in _USERNAME_TO_ID_MAP.items():
            if i == uid:
                res["username"] = u
                break
        for dn, rec in _DISPLAY_NAME_TO_ID_MAP.items():
            if rec.get("user_id") == uid:
                res["first_name"] = rec.get("display_name")
                res["display_name"] = rec.get("display_name")
                res["chat_id"] = rec.get("chat_id")
                res["chat_title"] = rec.get("chat_title")
                break

        # Check D1 user_mappings
        if not res["username"]:
            m_res = await execute_d1_query("SELECT username FROM user_mappings WHERE user_id = ?", [uid])
            if m_res.get("success") and m_res.get("results"):
                u = m_res["results"][0].get("username")
                if u:
                    res["username"] = str(u).lower().lstrip("@")
                    _USERNAME_TO_ID_MAP[res["username"]] = uid

        # Check D1 messages
        d_res = await execute_d1_query(
            "SELECT user_name, username, chat_id, chat_title, msg_date, msg_time, created_at, COUNT(*) as cnt FROM messages WHERE user_id = ? GROUP BY user_id ORDER BY id DESC LIMIT 1",
            [uid]
        )
        if d_res.get("success") and d_res.get("results"):
            row = d_res["results"][0]
            if not res["first_name"]:
                res["first_name"] = row.get("user_name")
                res["display_name"] = row.get("user_name")
            if not res["username"] and row.get("username"):
                res["username"] = str(row["username"]).lower().lstrip("@")
            res["chat_id"] = res["chat_id"] or row.get("chat_id")
            res["chat_title"] = res["chat_title"] or row.get("chat_title")
            res["last_seen"] = f"{row.get('msg_date', '')} {row.get('msg_time', '')}".strip() or row.get("created_at")
            res["msg_count"] = row.get("cnt", 1)

        # Live Telegram Bot API probe if username/name still missing
        if not res["username"] or not res["first_name"]:
            tg = await _probe_live_telegram_chat(uid)
            if tg:
                res["username"] = res["username"] or (getattr(tg, "username", None) or "").lower() or None
                res["first_name"] = res["first_name"] or getattr(tg, "first_name", None)
                res["last_name"] = getattr(tg, "last_name", None)
                res["bio"] = getattr(tg, "bio", None) or getattr(tg, "description", None)
                res["display_name"] = f"{res['first_name'] or ''} {res['last_name'] or ''}".strip() or res["first_name"]

        return res

    # 2. Telegram @username check (starts with @, or in _USERNAME_TO_ID_MAP, or standard username pattern)
    clean_u = clean_id.lstrip("@").strip().lower()
    is_explicit_username = clean_id.startswith("@") or bool(re.match(r"^[a-zA-Z0-9_]{4,32}$", clean_u))
    if is_explicit_username:
        # Check in RAM
        if clean_u in _USERNAME_TO_ID_MAP:
            res["user_id"] = _USERNAME_TO_ID_MAP[clean_u]
            res["username"] = clean_u

        # Check D1 user_mappings
        if not res["user_id"]:
            u_res = await execute_d1_query("SELECT user_id FROM user_mappings WHERE username = ?", [clean_u])
            if u_res.get("success") and u_res.get("results"):
                uid = u_res["results"][0].get("user_id")
                if uid:
                    res["user_id"] = int(uid)
                    res["username"] = clean_u
                    _USERNAME_TO_ID_MAP[clean_u] = res["user_id"]

        # Check D1 messages
        if not res["user_id"]:
            m_res = await execute_d1_query(
                "SELECT user_id, user_name, chat_id, chat_title, msg_date, msg_time, created_at, COUNT(*) as cnt FROM messages WHERE username = ? OR username = ? GROUP BY user_id ORDER BY id DESC LIMIT 1",
                [clean_u, f"@{clean_u}"]
            )
            if m_res.get("success") and m_res.get("results"):
                row = m_res["results"][0]
                if row.get("user_id"):
                    res["user_id"] = int(row["user_id"])
                    res["username"] = clean_u
                    res["first_name"] = row.get("user_name")
                    res["display_name"] = row.get("user_name")
                    res["chat_id"] = row.get("chat_id")
                    res["chat_title"] = row.get("chat_title")
                    res["last_seen"] = f"{row.get('msg_date', '')} {row.get('msg_time', '')}".strip() or row.get("created_at")
                    res["msg_count"] = row.get("cnt", 1)

        # Check banned_users table
        if not res["user_id"]:
            b_res = await execute_d1_query("SELECT user_id, first_name FROM banned_users WHERE username = ? OR username = ?", [clean_u, f"@{clean_u}"])
            if b_res.get("success") and b_res.get("results"):
                row = b_res["results"][0]
                if row.get("user_id"):
                    res["user_id"] = int(row["user_id"])
                    res["username"] = clean_u
                    res["first_name"] = row.get("first_name")

        # Live Telegram Bot API probe
        if not res["user_id"] or not res["first_name"]:
            tg = await _probe_live_telegram_chat(f"@{clean_u}")
            if tg:
                res["user_id"] = res["user_id"] or getattr(tg, "id", None)
                res["username"] = clean_u
                res["first_name"] = res["first_name"] or getattr(tg, "first_name", None)
                res["last_name"] = getattr(tg, "last_name", None)
                res["bio"] = getattr(tg, "bio", None) or getattr(tg, "description", None)
                res["display_name"] = f"{res['first_name'] or ''} {res['last_name'] or ''}".strip() or res["first_name"]

        if res["user_id"]:
            res["is_banned"] = is_user_banned(res["user_id"], clean_u)
            res["is_muted"] = (is_user_muted(res["user_id"], clean_u) > 0)
            return res

    # 3. Search by Display Name / Real Name (Persian/Latin/Fuzzy/Normalized)
    target_name = clean_id.lstrip("@").strip()
    norm_target = normalize_identity_str(target_name)
    compact_target = norm_target.replace(" ", "")

    # Step 3a-1: Check isolated per-chat display names first (avoids cross-group name collision)
    if clean_cid and clean_cid in _CHAT_DISPLAY_NAMES:
        chat_map = _CHAT_DISPLAY_NAMES[clean_cid]
        if norm_target in chat_map:
            rec = chat_map[norm_target]
            res["user_id"] = rec["user_id"]
            res["username"] = rec.get("username")
            res["first_name"] = rec.get("display_name")
            res["display_name"] = rec.get("display_name")
            res["chat_id"] = clean_cid
            res["chat_title"] = rec.get("chat_title")
            res["is_banned"] = is_user_banned(res["user_id"])
            res["is_muted"] = (is_user_muted(res["user_id"]) > 0)
            return res
        for k_name, rec in chat_map.items():
            if norm_target in k_name or k_name in norm_target or (compact_target and compact_target in k_name.replace(" ", "")):
                res["user_id"] = rec["user_id"]
                res["username"] = rec.get("username")
                res["first_name"] = rec.get("display_name")
                res["display_name"] = rec.get("display_name")
                res["chat_id"] = clean_cid
                res["chat_title"] = rec.get("chat_title")
                res["is_banned"] = is_user_banned(res["user_id"])
                res["is_muted"] = (is_user_muted(res["user_id"]) > 0)
                return res

    # Step 3a-2: Direct lookup in hot _DISPLAY_NAME_TO_ID_MAP
    if norm_target in _DISPLAY_NAME_TO_ID_MAP:
        rec = _DISPLAY_NAME_TO_ID_MAP[norm_target]
        res["user_id"] = rec["user_id"]
        res["username"] = rec.get("username")
        res["first_name"] = rec.get("display_name")
        res["display_name"] = rec.get("display_name")
        res["chat_id"] = rec.get("chat_id")
        res["chat_title"] = rec.get("chat_title")
        res["is_banned"] = is_user_banned(res["user_id"])
        res["is_muted"] = (is_user_muted(res["user_id"]) > 0)
        return res

    # Step 3b: Substring matching in _DISPLAY_NAME_TO_ID_MAP
    for k_name, rec in _DISPLAY_NAME_TO_ID_MAP.items():
        if norm_target in k_name or k_name in norm_target or (compact_target and compact_target in k_name.replace(" ", "")):
            res["user_id"] = rec["user_id"]
            res["username"] = rec.get("username")
            res["first_name"] = rec.get("display_name")
            res["display_name"] = rec.get("display_name")
            res["chat_id"] = rec.get("chat_id")
            res["chat_title"] = rec.get("chat_title")
            res["is_banned"] = is_user_banned(res["user_id"])
            res["is_muted"] = (is_user_muted(res["user_id"]) > 0)
            return res

    # Step 3c: Deep scan in hot RAM chat histories, checking current chat FIRST
    ordered_cids = [clean_cid] + [c for c in _CHAT_HISTORIES.keys() if c != clean_cid] if clean_cid else list(_CHAT_HISTORIES.keys())
    for cid in ordered_cids:
        msgs = _CHAT_HISTORIES.get(cid, [])
        for m in reversed(msgs):
            u_name = str(m.get("user_name", "")).strip()
            if u_name:
                norm_u = normalize_identity_str(u_name)
                if norm_target in norm_u or norm_u in norm_target or (compact_target and compact_target in norm_u.replace(" ", "")):
                    uid = m.get("user_id")
                    if uid and int(uid) != ADMIN_ID:
                        res["user_id"] = int(uid)
                        res["username"] = m.get("username")
                        res["first_name"] = u_name
                        res["display_name"] = u_name
                        res["chat_id"] = cid
                        res["chat_title"] = m.get("chat_title", "")
                        res["last_seen"] = f"{m.get('msg_date', '')} {m.get('msg_time', '')}".strip()
                        _DISPLAY_NAME_TO_ID_MAP[norm_u] = {
                            "user_id": int(uid),
                            "display_name": u_name,
                            "username": res["username"],
                            "chat_id": cid,
                            "chat_title": res["chat_title"],
                            "updated_at": ""
                        }
                        res["is_banned"] = is_user_banned(res["user_id"])
                        res["is_muted"] = (is_user_muted(res["user_id"]) > 0)
                        return res

    # Step 3d: Search in banned_users table
    b_sql = """
        SELECT user_id, username, first_name
        FROM banned_users
        WHERE (user_id IS NOT NULL AND user_id > 0 AND (username = ? OR username LIKE ? OR first_name = ? OR first_name LIKE ?))
           OR (username = ? OR username LIKE ? OR first_name = ? OR first_name LIKE ?)
        ORDER BY rowid DESC LIMIT 1
    """
    b_res = await execute_d1_query(b_sql, [target_name, f"%{target_name}%", target_name, f"%{target_name}%", target_name, f"%{target_name}%", target_name, f"%{target_name}%"])
    if b_res.get("success") and b_res.get("results"):
        row = b_res["results"][0]
        uid = row.get("user_id")
        if uid and int(uid) > 0:
            res["user_id"] = int(uid)
            res["username"] = row.get("username")
            res["first_name"] = row.get("first_name")
            res["display_name"] = row.get("first_name")
            res["is_banned"] = True
            return res

    # Step 3e: Multi-row candidate search in Cloudflare D1 messages table
    d1_sql = """
        SELECT user_id, user_name, username, chat_id, chat_title, msg_date, msg_time, created_at, COUNT(*) as cnt
        FROM messages
        WHERE user_id IS NOT NULL AND user_id > 0
          AND (user_name = ? OR user_name LIKE ? OR username = ? OR username LIKE ?)
        GROUP BY user_id
        ORDER BY id DESC LIMIT 5
    """
    d1_res = await execute_d1_query(d1_sql, [target_name, f"%{target_name}%", target_name, f"%{target_name}%"])
    if d1_res.get("success") and d1_res.get("results"):
        candidates = []
        for r in d1_res["results"]:
            c_uid = r.get("user_id")
            if not c_uid or int(c_uid) == ADMIN_ID:
                continue
            cand = {
                "user_id": int(c_uid),
                "username": str(r.get("username") or "").lower().lstrip("@") or None,
                "first_name": r.get("user_name"),
                "display_name": r.get("user_name"),
                "chat_id": r.get("chat_id"),
                "chat_title": r.get("chat_title"),
                "last_seen": f"{r.get('msg_date', '')} {r.get('msg_time', '')}".strip() or r.get("created_at"),
                "msg_count": r.get("cnt", 1),
                "is_banned": is_user_banned(int(c_uid)),
                "is_muted": (is_user_muted(int(c_uid)) > 0)
            }
            candidates.append(cand)

        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            res = candidates[0]
            res["candidates"] = candidates
            return res

    # Step 3f: Fallback to username search if clean_id looked like a username
    if is_explicit_username:
        res["username"] = clean_u

    return res


async def resolve_target_identifier(identifier: str) -> tuple[Optional[int], Optional[str]]:
    """Backward-compatible wrapper returning (user_id, username_or_display_name)."""
    info = await resolve_target_full_identity(identifier)
    uid = info.get("user_id")
    label = info.get("username") or info.get("first_name") or info.get("display_name")
    return (uid, label)


async def ban_target_async(
    target: Union[str, int],
    reason: str = "تخلف از قوانین",
    first_name: str = "",
    banned_by: int = 0,
    source_chat_id: int = 0,
    source_chat_title: str = ""
) -> bool:
    """Bans a user and stores full identity (numeric id, @username, display name, banner, source chat)."""
    target_str = str(target).strip()
    info = await resolve_target_full_identity(target_str)
    user_id = info.get("user_id")
    username = info.get("username") or ""
    resolved_name = info.get("first_name") or info.get("display_name") or ""
    clean_first = str(first_name or resolved_name or "")[:120].strip()

    if user_id == ADMIN_ID:
        return False

    # Live Telegram lookup fallback if any key piece of identity is missing
    if not user_id or not username or not clean_first:
        probe_target = user_id or (f"@{username}" if username else (target_str if target_str.startswith("@") else None))
        if probe_target:
            tg = await _probe_live_telegram_chat(probe_target)
            if tg:
                if not user_id and getattr(tg, "id", None):
                    user_id = int(tg.id)
                if not username and getattr(tg, "username", None):
                    username = tg.username.lower().lstrip("@")
                if not clean_first:
                    clean_first = f"{getattr(tg, 'first_name', '') or ''} {getattr(tg, 'last_name', '') or ''}".strip()

    clean_by = int(banned_by or 0)
    clean_src = int(source_chat_id or 0)
    clean_src_title = str(source_chat_title or "")[:150]
    clean_uname = str(username or "").lower().lstrip("@")

    # Update in-memory structures instantly
    if user_id:
        uid_int = int(user_id)
        _BANNED_USERS.add(uid_int)
        if uid_int in _CHAT_HISTORIES:
            del _CHAT_HISTORIES[uid_int]
        _BANNED_DETAILS[uid_int] = {
            "user_id": uid_int,
            "username": clean_uname,
            "first_name": clean_first,
            "reason": reason,
            "banned_by": clean_by,
            "source_chat_id": clean_src,
            "source_chat_title": clean_src_title,
            "banned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    if clean_uname:
        _BANNED_USERNAMES.add(clean_uname)
        if clean_uname in _USERNAME_TO_ID_MAP:
            mapped_id = _USERNAME_TO_ID_MAP[clean_uname]
            _BANNED_USERS.add(mapped_id)
            if mapped_id in _CHAT_HISTORIES:
                del _CHAT_HISTORIES[mapped_id]
            if user_id and mapped_id == user_id:
                _BANNED_DETAILS[user_id]["username"] = clean_uname

    # Persist complete identity in D1
    primary_id = int(user_id) if user_id else (_USERNAME_TO_ID_MAP.get(clean_uname, 0) if clean_uname else 0)
    sql = "INSERT OR REPLACE INTO banned_users (user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title, banned_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"
    res = await execute_d1_query(sql, [primary_id, clean_uname, clean_first, reason, clean_by, clean_src, clean_src_title])

    # Also backfill user_mappings if both are present
    if primary_id and clean_uname:
        _USERNAME_TO_ID_MAP[clean_uname] = primary_id
        try:
            asyncio.create_task(execute_d1_query("INSERT OR REPLACE INTO user_mappings (username, user_id) VALUES (?, ?)", [clean_uname, primary_id]))
        except Exception:
            pass

    return True if (user_id or clean_uname) else res.get("success", False)


async def unban_target_async(target: Union[str, int]) -> bool:
    target_str = str(target).strip()
    info = await resolve_target_full_identity(target_str)
    user_id = info.get("user_id")
    username = info.get("username") or ""

    # Immediately unban in RAM (Instant unblock)
    if user_id and int(user_id) in _BANNED_USERS:
        _BANNED_USERS.discard(int(user_id))
        _BANNED_DETAILS.pop(int(user_id), None)
    if username:
        clean_u = username.lower().lstrip("@")
        _BANNED_USERNAMES.discard(clean_u)
        mapped = _USERNAME_TO_ID_MAP.get(clean_u)
        if mapped and mapped in _BANNED_USERS:
            _BANNED_USERS.discard(mapped)
            _BANNED_DETAILS.pop(mapped, None)
    
    # Also search by target_str directly in RAM
    clean_target_str = target_str.lower().lstrip("@")
    _BANNED_USERNAMES.discard(clean_target_str)
    if clean_target_str.lstrip("-").isdigit():
        _BANNED_USERS.discard(int(clean_target_str))

    # Persist unban to Cloudflare D1 with comprehensive matching across user_id, username and first_name
    delete_queries = []
    if user_id:
        delete_queries.append(("DELETE FROM banned_users WHERE user_id = ?", [user_id]))
    if username:
        clean_u = username.lower().lstrip("@")
        delete_queries.append(("DELETE FROM banned_users WHERE username = ? OR username = ? OR first_name = ? OR first_name LIKE ?", [clean_u, f"@{clean_u}", clean_u, f"%{clean_u}%"]))
    
    clean_u_val = username.lower().lstrip("@") if username else ""
    if not clean_u_val or clean_target_str != clean_u_val:
        delete_queries.append(("DELETE FROM banned_users WHERE username = ? OR username = ? OR first_name = ? OR first_name LIKE ?", [clean_target_str, f"@{clean_target_str}", clean_target_str, f"%{clean_target_str}%"]))

    for sql, params in delete_queries:
        try:
            await execute_d1_query(sql, params)
        except Exception as e:
            logger.error(f"Error executing unban D1 query: {e}")

    return True

def ban_user(user_id: int, reason: str = "تخلف از قوانین"):
    clean_uid = int(user_id)
    _BANNED_USERS.add(clean_uid)
    execute_d1_query_sync("INSERT OR REPLACE INTO banned_users (user_id, reason) VALUES (?, ?)", [clean_uid, reason])
    if clean_uid in _CHAT_HISTORIES:
        del _CHAT_HISTORIES[clean_uid]

FA_MUTE_DUR_WORDS = {
    "دقیقه": 60, "دقيقه": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "ساعت": 3600, "ساعته": 3600, "hour": 3600, "hours": 3600, "h": 3600,
    "روز": 86400, "روزه": 86400, "day": 86400, "days": 86400, "d": 86400,
    "هفته": 604800, "week": 604800, "ماه": 2592000,
}


def parse_mute_duration_to_sec(text: str) -> int:
    try:
        _t = (text or "").strip().lower()
        if not _t:
            return 0
        _fa = {"۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"}
        for _k, _v in _fa.items():
            _t = _t.replace(_k, _v)
        _m = re.search(r"(\d+(?:\.\d+)?)", _t)
        if not _m:
            if "نیم ساعت" in _t or "نیم‌ساعت" in _t or "نیمساعت" in _t:
                return 1800
            if "ربع ساعت" in _t:
                return 900
            return 0
        _num = float(_m.group(1))
        for _w, _sec in FA_MUTE_DUR_WORDS.items():
            if _w in _t:
                return int(_num * _sec)
        return int(_num * 60)
    except Exception:
        return 0


def format_mute_remaining(sec: float, lang: str = "fa") -> str:
    try:
        _s = max(0, int(sec))
        if (lang or "fa") == "fa":
            if _s >= 86400:
                return f"{_s // 86400} روز و {(_s % 86400) // 3600} ساعت"
            if _s >= 3600:
                return f"{_s // 3600} ساعت و {(_s % 3600) // 60} دقیقه"
            if _s >= 60:
                return f"{_s // 60} دقیقه"
            return f"{_s} ثانیه"
        def _pl(n: int, one: str, many: str) -> str:
            return f"{n} {one if n == 1 else many}"
        if _s >= 86400:
            return f"{_pl(_s // 86400, 'day', 'days')} {_pl((_s % 86400) // 3600, 'hour', 'hours')}"
        if _s >= 3600:
            return f"{_pl(_s // 3600, 'hour', 'hours')} {_pl((_s % 3600) // 60, 'minute', 'minutes')}"
        if _s >= 60:
            return _pl(_s // 60, "minute", "minutes")
        return _pl(_s, "second", "seconds")
    except Exception:
        return ""


async def mute_target_async(target, duration_sec: int = 1800, reason: str = "سکوت موقت به دستور فرمانده", first_name: str = "", muted_by: int = 0, source_chat_id: int = 0, source_chat_title: str = "") -> tuple:
    target_str = str(target).strip()
    user_id, username = await resolve_target_identifier(target_str)
    if user_id == ADMIN_ID:
        return (False, 0, user_id, username)
    try:
        _dur = max(60, int(duration_sec or 0))
    except Exception:
        _dur = 1800
    _until = time.time() + _dur
    if user_id:
        _MUTED_UNTIL[int(user_id)] = _until
        if username:
            _MUTED_USERNAMES[str(username).lower().lstrip("@")] = _until
    elif username:
        _MUTED_USERNAMES[str(username).lower().lstrip("@")] = _until
        _mapped = _USERNAME_TO_ID_MAP.get(str(username).lower().lstrip("@"))
        if _mapped:
            _MUTED_UNTIL[int(_mapped)] = _until
    try:
        await execute_d1_query(
            "INSERT OR REPLACE INTO muted_users (user_id, username, first_name, reason, muted_by, source_chat_id, source_chat_title, until_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [int(user_id or 0), (username or ""), str(first_name or "")[:120], str(reason or "")[:200], int(muted_by or 0), int(source_chat_id or 0), str(source_chat_title or "")[:150], _until]
        )
    except Exception:
        pass
    return (True, _dur, user_id, username)


async def unmute_target_async(target) -> bool:
    try:
        target_str = str(target).strip()
    except Exception:
        return False
    user_id, username = await resolve_target_identifier(target_str)
    if user_id and int(user_id) in _MUTED_UNTIL:
        _MUTED_UNTIL.pop(int(user_id), None)
    if username:
        _MUTED_USERNAMES.pop(str(username).lower().lstrip("@"), None)
    _clean = target_str.lower().lstrip("@")
    _MUTED_USERNAMES.pop(_clean, None)
    if _clean.lstrip("-").isdigit():
        try:
            _MUTED_UNTIL.pop(int(_clean), None)
        except Exception:
            pass
    try:
        if user_id:
            await execute_d1_query("DELETE FROM muted_users WHERE user_id = ?", [int(user_id)])
        if username:
            await execute_d1_query("DELETE FROM muted_users WHERE username = ? OR username = ?", [str(username).lower().lstrip("@"), "@" + str(username).lower().lstrip("@")])
        await execute_d1_query("DELETE FROM muted_users WHERE username = ? OR username = ?", [_clean, "@" + _clean])
    except Exception:
        pass
    return True


def is_user_muted(user_id: int, username: str = "") -> float:
    try:
        clean_uid = int(user_id)
    except Exception:
        clean_uid = 0
    if clean_uid == ADMIN_ID:
        return 0.0
    _now = time.time()
    if clean_uid and clean_uid in _MUTED_UNTIL:
        _left = _MUTED_UNTIL[clean_uid] - _now
        if _left > 0:
            return _left
        _MUTED_UNTIL.pop(clean_uid, None)
    if username:
        _cu = str(username).strip().lower().lstrip("@")
        if _cu and _cu in _MUTED_USERNAMES:
            _left = _MUTED_USERNAMES[_cu] - _now
            if _left > 0:
                return _left
            _MUTED_USERNAMES.pop(_cu, None)
        _mapped = _USERNAME_TO_ID_MAP.get(_cu)
        if _mapped and _mapped in _MUTED_UNTIL:
            _left = _MUTED_UNTIL[_mapped] - _now
            if _left > 0:
                return _left
            _MUTED_UNTIL.pop(_mapped, None)
    return 0.0


# ============================================================================
# Bot Self-Mute Engine (Admin-ordered silence mode, per-chat or global)
# RAM-authoritative for sub-millisecond checks; mirrored to Cloudflare KV
# (global key + per-chat keys + chat index) so states survive restarts.
# ============================================================================

def is_bot_self_muted(chat_id: int = 0) -> float:
    """Remaining bot self-silence seconds for this chat (global mute applies everywhere). 0.0 = active."""
    global _BOT_SELF_MUTED_GLOBAL_UNTIL
    try:
        _now = time.time()
        _g = float(_BOT_SELF_MUTED_GLOBAL_UNTIL or 0.0)
        if _g > _now:
            return _g - _now
        if _g:
            _BOT_SELF_MUTED_GLOBAL_UNTIL = 0.0
        try:
            _cid = int(chat_id or 0)
        except Exception:
            _cid = 0
        if _cid in _BOT_SELF_MUTED_CHATS:
            _left = float(_BOT_SELF_MUTED_CHATS[_cid]) - _now
            if _left > 0:
                return _left
            _BOT_SELF_MUTED_CHATS.pop(_cid, None)
    except Exception:
        pass
    return 0.0


async def _update_bot_self_mute_index_async(chat_id: int, add: bool) -> None:
    try:
        raw = await kv_get_cache_async("BOT_SELF_MUTE_INDEX") or ""
        ids = {p.strip() for p in str(raw).split(",") if p.strip().lstrip("-").isdigit()}
        key = str(int(chat_id))
        if add:
            ids.add(key)
        else:
            ids.discard(key)
        await kv_set_cache_async("BOT_SELF_MUTE_INDEX", ",".join(sorted(ids)), expiration_ttl=604800, cloud_min_interval_sec=60)
    except Exception:
        pass


async def mute_bot_self_async(chat_id: int = 0, duration_sec: int = 3600, reason: str = "", muted_by: int = 0, scope: str = "chat") -> float:
    """Silence the bot itself. scope='chat' (this chat only) or 'global' (everywhere). Returns applied seconds."""
    global _BOT_SELF_MUTED_GLOBAL_UNTIL
    try:
        _dur = max(60, int(duration_sec or 0))
    except Exception:
        _dur = 3600
    _until = time.time() + _dur
    clean_scope = (scope or "chat").strip().lower()
    try:
        if clean_scope == "global":
            _BOT_SELF_MUTED_GLOBAL_UNTIL = _until
            await kv_set_cache_async("BOT_SELF_MUTE_GLOBAL", str(_until), expiration_ttl=min(_dur + 300, 604800), cloud_min_interval_sec=30)
        else:
            _cid = int(chat_id or 0)
            _BOT_SELF_MUTED_CHATS[_cid] = _until
            await kv_set_cache_async(f"BOT_SELF_MUTE_CHAT_{_cid}", str(_until), expiration_ttl=min(_dur + 300, 604800), cloud_min_interval_sec=30)
            await _update_bot_self_mute_index_async(_cid, True)
    except Exception:
        pass
    return float(_dur)


async def unmute_bot_self_async(chat_id: int = 0, scope: str = "chat") -> bool:
    """Wake the bot. scope='chat' | 'global' | 'all'."""
    global _BOT_SELF_MUTED_GLOBAL_UNTIL
    try:
        clean_scope = (scope or "chat").strip().lower()
        if clean_scope in ("global", "all", "both", "everywhere"):
            _BOT_SELF_MUTED_GLOBAL_UNTIL = 0.0
            try:
                await kv_set_cache_async("BOT_SELF_MUTE_GLOBAL", "0", expiration_ttl=60, cloud_min_interval_sec=10)
            except Exception:
                pass
        if clean_scope in ("chat", "all", "both"):
            try:
                _cid = int(chat_id or 0)
            except Exception:
                _cid = 0
            _BOT_SELF_MUTED_CHATS.pop(_cid, None)
            try:
                await kv_set_cache_async(f"BOT_SELF_MUTE_CHAT_{_cid}", "0", expiration_ttl=60, cloud_min_interval_sec=10)
            except Exception:
                pass
            await _update_bot_self_mute_index_async(_cid, False)
    except Exception:
        pass
    return True


async def restore_bot_self_mute_async() -> int:
    """Reload persisted self-mute states from KV after restart. Returns restored count."""
    global _BOT_SELF_MUTED_GLOBAL_UNTIL
    restored = 0
    try:
        g = await kv_get_cache_async("BOT_SELF_MUTE_GLOBAL")
        if g:
            try:
                _gv = float(str(g).strip())
            except Exception:
                _gv = 0.0
            if _gv > time.time():
                _BOT_SELF_MUTED_GLOBAL_UNTIL = _gv
                restored += 1
    except Exception:
        pass
    try:
        raw = await kv_get_cache_async("BOT_SELF_MUTE_INDEX") or ""
        for part in str(raw).split(","):
            part = part.strip()
            if not part:
                continue
            try:
                cid = int(part)
            except Exception:
                continue
            try:
                v = await kv_get_cache_async(f"BOT_SELF_MUTE_CHAT_{cid}")
                if v and float(str(v).strip()) > time.time():
                    _BOT_SELF_MUTED_CHATS[cid] = float(str(v).strip())
                    restored += 1
            except Exception:
                continue
    except Exception:
        pass
    return restored


async def get_muted_users_detailed_async():
    try:
        res = await execute_d1_query("SELECT user_id, username, first_name, reason, muted_by, source_chat_id, source_chat_title, until_ts, muted_at FROM muted_users ORDER BY muted_at DESC")
    except Exception:
        return []
    if res.get("success"):
        return res["results"]
    return []


def unban_user(user_id: int):
    clean_uid = int(user_id)
    if clean_uid in _BANNED_USERS:
        _BANNED_USERS.remove(clean_uid)
    execute_d1_query_sync("DELETE FROM banned_users WHERE user_id = ?", [clean_uid])

def is_user_banned(user_id: int, username: str = "") -> bool:
    """
    Sub-microsecond (<0.0001ms) In-Memory Zero-Tolerance Ban Enforcement:
    Checks numeric user ID and username against hot hashed sets with absolute admin immunity.
    """
    try:
        clean_uid = int(user_id)
    except Exception:
        clean_uid = 0

    if clean_uid == ADMIN_ID:
        return False
    if clean_uid and clean_uid in _BANNED_USERS:
        return True
    if username:
        clean_uname = str(username).strip().lower().lstrip("@")
        if clean_uname and clean_uname in _BANNED_USERNAMES:
            return True
        # Check reverse mapping: if username maps to an already-banned ID
        mapped_id = _USERNAME_TO_ID_MAP.get(clean_uname)
        if mapped_id and mapped_id in _BANNED_USERS:
            _BANNED_USERNAMES.add(clean_uname)
            return True
    return False

async def get_banned_users_detailed_async() -> List[Dict[str, Any]]:
    records = []
    try:
        res = await execute_d1_query("SELECT user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title, banned_at FROM banned_users ORDER BY banned_at DESC")
        if res.get("success") and res.get("results"):
            records = res["results"]
            # Hot sync in-memory sets with freshly queried D1 records
            for r in records:
                u_id = r.get("user_id")
                if u_id:
                    _BANNED_USERS.add(int(u_id))
                u_name = (r.get("username") or "").lower().lstrip("@")
                if u_name:
                    _BANNED_USERNAMES.add(u_name)
    except Exception:
        pass

    if not records and _BANNED_DETAILS:
        records = list(_BANNED_DETAILS.values())

    # Guarantee that every single record has user_id, username, and first_name (display name)
    for r in records:
        uid = r.get("user_id")
        if uid:
            uid_int = int(uid)
            mem = _BANNED_DETAILS.get(uid_int, {})
            if not r.get("username") and mem.get("username"):
                r["username"] = mem["username"]
            if not r.get("first_name") and mem.get("first_name"):
                r["first_name"] = mem["first_name"]

            # Reverse map check
            if not r.get("username"):
                for u, i in _USERNAME_TO_ID_MAP.items():
                    if i == uid_int:
                        r["username"] = u
                        break
            if not r.get("first_name"):
                for dn, rec in _DISPLAY_NAME_TO_ID_MAP.items():
                    if rec.get("user_id") == uid_int:
                        r["first_name"] = rec.get("display_name", "")
                        break

    return records or [
        {
            "user_id": uid,
            "username": _BANNED_DETAILS.get(uid, {}).get("username", ""),
            "first_name": _BANNED_DETAILS.get(uid, {}).get("first_name", ""),
            "reason": _BANNED_DETAILS.get(uid, {}).get("reason", "نامشخص"),
            "banned_by": _BANNED_DETAILS.get(uid, {}).get("banned_by", 0),
            "source_chat_id": 0,
            "source_chat_title": "",
            "banned_at": _BANNED_DETAILS.get(uid, {}).get("banned_at", "")
        }
        for uid in _BANNED_USERS
    ]

def get_banned_users() -> List[int]:
    return list(_BANNED_USERS)
