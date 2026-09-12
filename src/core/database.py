import re
import json
import time
import logging
import asyncio
import httpx
from datetime import datetime
import pytz
import jdatetime
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

_L1_CACHE: Dict[str, Dict[str, Any]] = {}
_MEMORY_DIRECTIVES: List[str] = []
_BANNED_USERS: set = set()
_BANNED_USERNAMES: set = set()
_MUTED_UNTIL: Dict[int, float] = {}
_MUTED_USERNAMES: Dict[str, float] = {}
_USERNAME_TO_ID_MAP: Dict[str, int] = {}
_DISPLAY_NAME_TO_ID_MAP: Dict[str, Dict[str, Any]] = {}
_CHAT_HISTORIES: Dict[int, List[Dict[str, Any]]] = {}
_ACTIVE_GROUPS: Dict[int, Dict[str, Any]] = {}
# Chats awaiting admin activation (bot was added by a non-admin).
# Mirrored from D1 `tracked_groups.status == 'pending'` at startup.
_PENDING_GROUPS: set = set()

# Asynchronous Write-Behind Batch Message Queue & Worker Guard
_D1_WRITE_QUEUE: Optional[asyncio.Queue] = None
_BATCH_WORKER_TASK: Optional[asyncio.Task] = None

_http_limits = httpx.Limits(max_keepalive_connections=200, max_connections=400, keepalive_expiry=600.0)
_cf_client: Optional[httpx.AsyncClient] = None

def get_cf_client() -> httpx.AsyncClient:
    # No auth header in the pool — token is attached per-request via _cf_headers()
    # so Railway variable rotation works without restart.
    global _cf_client
    if _cf_client is None or _cf_client.is_closed:
        _cf_client = httpx.AsyncClient(
            limits=_http_limits,
            http2=True,
            timeout=8.0,
            headers={
                "Content-Type": "application/json"
            }
        )
    return _cf_client


def _cf_headers() -> Dict[str, str]:
    try:
        from src.core.config import CLOUDFLARE_API_TOKEN as _tok
    except Exception:
        _tok = CLOUDFLARE_API_TOKEN
    return {
        "Authorization": f"Bearer {_tok}",
        "Content-Type": "application/json",
    }

def get_tehran_timestamps() -> Tuple[str, str, str]:
    """Returns (created_at_iso, time_str, jalali_date_str)."""
    try:
        tz = pytz.timezone("Asia/Tehran")
        now = datetime.now(tz)
        j_now = jdatetime.datetime.fromgregorian(datetime=now)
        time_str = now.strftime("%H:%M:%S")
        j_date_str = j_now.strftime("%Y/%m/%d")
        iso_str = now.strftime("%Y-%m-%d %H:%M:%S")
        return iso_str, time_str, j_date_str
    except Exception:
        iso_fallback = time.strftime("%Y-%m-%d %H:%M:%S")
        return iso_fallback, iso_fallback, iso_fallback

# --- Tier 1: L1 Fast Sub-Millisecond Memory Buffer ---

_L1_HITS = 0
_L1_MISSES = 0
_L1_LAST_HIT_AT: float = 0.0


def l1_get(key: str) -> Optional[str]:
    global _L1_HITS, _L1_MISSES, _L1_LAST_HIT_AT
    item = _L1_CACHE.get(key)
    if not item:
        _L1_MISSES += 1
        return None
    if time.time() > item["expires_at"]:
        try:
            del _L1_CACHE[key]
        except KeyError:
            pass
        _L1_MISSES += 1
        return None
    # Sliding refresh: hot keys live longer (up to +50% of original TTL).
    try:
        item["hits"] = item.get("hits", 0) + 1
        if item["hits"] % 5 == 0:
            item["expires_at"] = min(item["expires_at"] + 60.0, time.time() + item.get("ttl", 300) * 1.5)
    except Exception:
        pass
    _L1_HITS += 1
    _L1_LAST_HIT_AT = time.time()
    return item["value"]

_L1_PRUNE_COUNTER = 0


def l1_set(key: str, value: str, ttl_sec: int = 300):
    global _L1_PRUNE_COUNTER
    now = time.time()
    # Amortized memory guard: full prune scan at most once per 64 sets
    if len(_L1_CACHE) >= 1500:
        _L1_PRUNE_COUNTER += 1
        if _L1_PRUNE_COUNTER % 64 == 0:
            expired = [k for k, v in _L1_CACHE.items() if now > v.get("expires_at", 0)]
            for k in expired:
                del _L1_CACHE[k]
        if len(_L1_CACHE) >= 1500:
            # FIFO eviction of oldest inserted keys (dict preserves insertion order)
            for k in list(_L1_CACHE.keys())[:300]:
                del _L1_CACHE[k]

    try:
        _ttl = max(30, int(ttl_sec))
    except Exception:
        _ttl = 300
    _L1_CACHE[key] = {
        "value": value,
        "expires_at": now + _ttl,
        "ttl": _ttl,
        "hits": 0,
        "set_at": now,
    }

def l1_delete(key: str):
    if key in _L1_CACHE:
        del _L1_CACHE[key]

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

    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_KV_ID:
        return None

    try:
        client = get_cf_client()
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{CLOUDFLARE_KV_ID}/values/{key}"
        resp = await client.get(url, headers=_cf_headers(), timeout=3.5)
        if resp.status_code == 200:
            val_str = resp.text
            l1_set(key, val_str, ttl_sec=120)
            return val_str
    except Exception as e:
        logger.debug(f"KV get error ({key}): {e}")
    return None

async def kv_set_cache_async(key: str, value: str, expiration_ttl: int = 300, cloud_write: bool = True, cloud_min_interval_sec: Optional[int] = None) -> bool:
    """
    Quota-aware cache writer. L1 RAM is ALWAYS updated (reads stay instant).
    Cloud PUTs are skipped when: value unchanged since last cloud write,
    per-key throttle interval not elapsed, or the 429 circuit breaker is open.
    Returns True when the value is safely cached (L1), even if the cloud sync
    was deferred \u2014 use get_cache_health_async() to inspect cloud state.
    """
    clean_ttl = max(60, int(expiration_ttl))
    l1_set(key, value, ttl_sec=clean_ttl)

    if not cloud_write or not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_KV_ID:
        return True
    if kv_cloud_circuit_open():
        return True

    if cloud_min_interval_sec is None:
        cloud_min_interval_sec = _KV_SLOW_CLOUD_INTERVAL_SEC if key.startswith(_KV_SLOW_PREFIXES) else 0

    now = time.time()
    if now - _KV_LAST_CLOUD_WRITE.get(key, 0.0) < max(0, int(cloud_min_interval_sec)):
        return True

    val_hash = hash(value)
    if key in _KV_LAST_CLOUD_WRITE and _KV_LAST_CLOUD_HASH.get(key) == val_hash:
        return True

    try:
        client = get_cf_client()
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{CLOUDFLARE_KV_ID}/values/{key}?expiration_ttl={clean_ttl}"
        resp = await client.put(url, headers=_cf_headers(), content=value.encode("utf-8"), timeout=3.5)
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
            retry_after = float(resp.headers.get("Retry-After", 300))
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

async def kv_get_cloud_async(key: str) -> Optional[str]:
    """Direct Cloudflare KV read that bypasses L1 (used for startup warmup)."""
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_KV_ID:
        return None
    try:
        client = get_cf_client()
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/storage/kv/namespaces/{CLOUDFLARE_KV_ID}/values/{key}"
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
    Keys are fetched concurrently (10x faster cold start).
    """
    import asyncio as _aio
    warmed = 0

    async def _warm_one(k: str) -> bool:
        try:
            val = await kv_get_cloud_async(k)
            if val:
                l1_set(k, val, ttl_sec=600)
                return True
        except Exception:
            pass
        return False

    try:
        results = await _aio.gather(*[_warm_one(k) for k in _WARMUP_KEYS], return_exceptions=True)
        warmed = sum(1 for r in results if r is True)
    except Exception:
        pass
    logger.info(f"L1 warmup from Cloudflare KV: {warmed}/{len(_WARMUP_KEYS)} keys restored.")
    return warmed

async def get_cache_health_async() -> Dict[str, Any]:
    """Reports L1 size, KV circuit state, D1 reachability and D1 queue depth."""
    # NOTE: _KV_LAST_CLOUD_ERROR is only read here (no global decl needed).
    # Memoize the D1 probe for 30s so health daemons don't hammer D1
    try:
        if _HEALTH_MEMO.get("data") and (time.time() - float(_HEALTH_MEMO.get("at", 0))) < 30.0:
            snap = dict(_HEALTH_MEMO["data"])
            snap["l1_keys"] = len(_L1_CACHE)
            snap["d1_queue_depth"] = _D1_WRITE_QUEUE.qsize() if _D1_WRITE_QUEUE is not None else -1
            return snap
    except Exception:
        pass
    try:
        _tot = _L1_HITS + _L1_MISSES
        _hit_rate = round(100.0 * _L1_HITS / _tot, 1) if _tot else 0.0
    except Exception:
        _hit_rate = 0.0
    health: Dict[str, Any] = {
        "l1_keys": len(_L1_CACHE),
        "l1_hit_rate_pct": _hit_rate,
        "l1_hits": _L1_HITS,
        "l1_misses": _L1_MISSES,
        "kv_circuit_open": kv_cloud_circuit_open(),
        "kv_last_cloud_error": _KV_LAST_CLOUD_ERROR or "none",
        "kv_cloud_writes_tracked": len(_KV_LAST_CLOUD_WRITE),
        "d1_queue_depth": _D1_WRITE_QUEUE.qsize() if _D1_WRITE_QUEUE is not None else -1,
        "d1_batch_worker_alive": bool(_BATCH_WORKER_TASK and not _BATCH_WORKER_TASK.done()),
        "d1_reachable": False,
    }
    try:
        res = await execute_d1_query("SELECT 1 AS ok", [])
        health["d1_reachable"] = bool(res.get("success"))
    except Exception:
        pass
    try:
        _HEALTH_MEMO["at"] = time.time()
        _HEALTH_MEMO["data"] = dict(health)
    except Exception:
        pass
    return health

# --- Tier 3: High-Power Cloudflare D1 SQL Operations ---

async def execute_d1_query(sql: str, params: Optional[List[Any]] = None) -> Dict[str, Any]:
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

async def _flush_batch_to_d1(batch: List[Dict[str, Any]]):
    """Safely flushes a batch of messages to Cloudflare D1 with chunking, retries, and fallback."""
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
            "created_at": str(m.get("created_at", ""))[:40]
        })

    # Chunk into 5 items per SQL insert (5 * 16 = 80 params, strictly below SQLite 100 limit)
    chunk_size = 5
    for i in range(0, len(clean_batch), chunk_size):
        sub_batch = clean_batch[i:i + chunk_size]
        if len(sub_batch) == 1:
            m = sub_batch[0]
            sql = "INSERT INTO messages (chat_id, user_id, message_id, user_name, username, chat_title, chat_type, msg_kind, reply_to_msg_id, reply_to_user, reply_to_text, role, content, msg_date, msg_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            params = [m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"], m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"], m["reply_to_user"], m["reply_to_text"], m["role"], m["content"], m["msg_date"], m["msg_time"], m["created_at"]]
            for attempt in range(3):
                res = await execute_d1_query(sql, params)
                if res.get("success"):
                    break
                await asyncio.sleep(0.2 * (attempt + 1))
        else:
            val_placeholders = ["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in sub_batch]
            params = []
            for m in sub_batch:
                params.extend([
                    m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"],
                    m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"], m["reply_to_user"], m["reply_to_text"],
                    m["role"], m["content"], m["msg_date"], m["msg_time"], m["created_at"]
                ])
            sql = f"INSERT INTO messages (chat_id, user_id, message_id, user_name, username, chat_title, chat_type, msg_kind, reply_to_msg_id, reply_to_user, reply_to_text, role, content, msg_date, msg_time, created_at) VALUES {', '.join(val_placeholders)}"

            success = False
            for attempt in range(3):
                res = await execute_d1_query(sql, params)
                if res.get("success"):
                    success = True
                    break
                await asyncio.sleep(0.2 * (attempt + 1))

            if not success:
                single_sql = "INSERT INTO messages (chat_id, user_id, message_id, user_name, username, chat_title, chat_type, msg_kind, reply_to_msg_id, reply_to_user, reply_to_text, role, content, msg_date, msg_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                for m in sub_batch:
                    try:
                        await execute_d1_query(single_sql, [
                            m["chat_id"], m["user_id"], m["message_id"], m["user_name"], m["username"],
                            m["chat_title"], m["chat_type"], m["msg_kind"], m["reply_to_msg_id"], m["reply_to_user"], m["reply_to_text"],
                            m["role"], m["content"], m["msg_date"], m["msg_time"], m["created_at"]
                        ])
                    except Exception:
                        pass

async def _d1_batch_writer_loop():
    """
    Continuous Background Queue Worker:
    Drains messages from the memory queue and flushes them in batches with zero crashes.
    """
    # NOTE: _D1_WRITE_QUEUE is only read here (created in ensure_batch_worker).
    while True:
        try:
            if _D1_WRITE_QUEUE is None:
                await asyncio.sleep(0.5)
                continue

            batch = []
            # Wait for first item
            first_item = await _D1_WRITE_QUEUE.get()
            batch.append(first_item)
            _D1_WRITE_QUEUE.task_done()

            # Drain up to 20 messages per batch (optimal 200 SQL params)
            while not _D1_WRITE_QUEUE.empty() and len(batch) < 20:
                try:
                    item = _D1_WRITE_QUEUE.get_nowait()
                    batch.append(item)
                    _D1_WRITE_QUEUE.task_done()
                except Exception:
                    break

            if batch:
                await _flush_batch_to_d1(batch)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"D1 batch write loop exception: {e}")
            await asyncio.sleep(0.5)

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
        message_id INTEGER DEFAULT 0
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
    CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id DESC);
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
                             "tracked_groups", "daily_usage", "messages_fts"}.issubset(_have)
    except Exception:
        _need_ddl = True
    if _need_ddl:
        for _stmt in schema.split(";"):
            _s = _stmt.strip()
            if _s:
                execute_d1_query_sync(_s)

    # Migrate DBs created before username/invite_link/status existed (no-op if present).
    for _mig in (
        "ALTER TABLE tracked_groups ADD COLUMN username TEXT DEFAULT ''",
        "ALTER TABLE tracked_groups ADD COLUMN invite_link TEXT DEFAULT ''",
        "ALTER TABLE tracked_groups ADD COLUMN status TEXT DEFAULT 'active'",
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

    ban_res = execute_d1_query_sync("SELECT user_id, username FROM banned_users")
    if ban_res["success"]:
        _BANNED_USERS = {row["user_id"] for row in ban_res["results"] if "user_id" in row and row["user_id"]}
        _BANNED_USERNAMES = {row["username"].lower().lstrip("@") for row in ban_res["results"] if row.get("username")}

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

    logger.info(f"D1 Synced: {len(_MEMORY_DIRECTIVES)} perpetual directives, {len(_BANNED_USERS)} banned users, {len(_ACTIVE_GROUPS)} active groups.")

async def sync_memory_from_d1_async():
    """Continuously refreshes perpetual memory, ban list, and tracked groups from Cloudflare D1."""
    # Only rebound names need `global` (_USERNAME_TO_ID_MAP/_ACTIVE_GROUPS are mutated in place).
    global _MEMORY_DIRECTIVES, _BANNED_USERS, _BANNED_USERNAMES
    mem_res = await execute_d1_query("SELECT directive FROM admin_memories ORDER BY id ASC")
    if mem_res["success"]:
        _MEMORY_DIRECTIVES = [row["directive"] for row in mem_res["results"] if "directive" in row]

    ban_res = await execute_d1_query("SELECT user_id, username FROM banned_users")
    if ban_res["success"]:
        _BANNED_USERS = {row["user_id"] for row in ban_res["results"] if "user_id" in row and row["user_id"]}
        _BANNED_USERNAMES = {row["username"].lower().lstrip("@") for row in ban_res["results"] if row.get("username")}

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

async def track_group_presence_async(chat_id: int, title: str, chat_type: str = "supergroup", added_by: int = 0, username: str = "", invite_link: str = "", status: str = "active"):
    clean_chat_id = int(chat_id)
    clean_status = (status or "active").strip().lower() or "active"
    if clean_status not in ("active", "pending", "left"):
        clean_status = "active"
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
        [clean_chat_id, title, chat_type, added_by, username or "", invite_link or "", clean_status]
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

def is_group_pending(chat_id: int) -> bool:
    """Sync RAM check: is this chat awaiting admin activation?"""
    try:
        return int(chat_id) in _PENDING_GROUPS
    except Exception:
        return False

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
    """(used, limit) with D1 fallback when RAM missed (e.g. after restart)."""
    try:
        uid = int(user_id)
    except Exception:
        return 0, DAILY_USER_LIMIT
    used = get_daily_used(uid)
    if used:
        return used, DAILY_USER_LIMIT
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
    return used, DAILY_USER_LIMIT


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
    try:
        await execute_d1_query(
            "INSERT INTO daily_usage (user_id, day, used, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id, day) DO UPDATE SET used = excluded.used, updated_at = CURRENT_TIMESTAMP",
            [uid, day, used],
        )
    except Exception:
        pass
    return used <= DAILY_USER_LIMIT, used, DAILY_USER_LIMIT


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
):
    ensure_batch_worker()
    now_ts = time.time()
    clean_username = (username or "").strip().lower().lstrip("@")
    created_at_iso, time_str, j_date_str = get_tehran_timestamps()
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0
    clean_user_id = int(user_id) if isinstance(user_id, (int, str)) and str(user_id).lstrip("-").isdigit() else 0
    
    # 1. Update In-Memory L1 Tracking
    if clean_chat_id < 0 and clean_chat_id not in _ACTIVE_GROUPS:
        asyncio.create_task(track_group_presence_async(clean_chat_id, chat_title or "گروه ناشناس"))

    if clean_username and user_id:
        # Only hit D1 when the mapping is actually new/changed (saves 1 HTTP call per message)
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

    # Ultra-Fast In-Memory Display Name Indexing (Even for users without @username)
    clean_display = str(user_name or "").strip()
    if clean_display and clean_user_id:
        norm_key = re.sub(r"[\s_\-\.]+", " ", clean_display).lower().strip()
        _DISPLAY_NAME_TO_ID_MAP[norm_key] = {
            "user_id": clean_user_id,
            "display_name": clean_display,
            "username": clean_username,
            "chat_id": clean_chat_id,
            "chat_title": chat_title,
            "updated_at": created_at_iso
        }

    # 2. Update RAM context immediately for sub-millisecond turn continuity.
    # Key is ALWAYS the normalized int chat_id: per-group isolation depends on it.
    if clean_chat_id not in _CHAT_HISTORIES:
        _CHAT_HISTORIES[clean_chat_id] = []

    _clean_kind = (msg_kind or "text").strip().lower() or "text"
    _clean_ctype = (chat_type or "").strip().lower()
    _CHAT_HISTORIES[clean_chat_id].append({
        "role": role,
        "content": content,
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
        "msg_date": j_date_str,
        "msg_time": time_str,
        "time": now_ts
    })
    
    # Rolling Window: 60 turns per chat is about 20k tokens (user cap).
    # Newest turns always win; D1 keeps 100 percent of history forever.
    try:
        from src.core.config import MAX_RAM_TURNS_PER_CHAT as _MAX_TURNS
    except Exception:
        _MAX_TURNS = 60
    if len(_CHAT_HISTORIES[clean_chat_id]) > _MAX_TURNS:
        _CHAT_HISTORIES[clean_chat_id] = _CHAT_HISTORIES[clean_chat_id][-_MAX_TURNS:]

    # Global RAM Guard: Prevent unbounded chat growth across thousands of groups
    if len(_CHAT_HISTORIES) > 300:
        # Evict oldest inactive chats from RAM (D1 preserves 100% of history forever)
        chats_by_recency = sorted(
            _CHAT_HISTORIES.keys(),
            key=lambda cid: (_CHAT_HISTORIES[cid][-1].get("time", 0) if _CHAT_HISTORIES[cid] else 0)
        )
        for cid in chats_by_recency[:60]:
            del _CHAT_HISTORIES[cid]

    # 3. Push to High-Speed Write-Behind Queue (zero HTTP blocking).
    # Every group/supergroup message carries its own chat_id + message_id,
    # so D1 rows stay strictly separated per group.
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
        "created_at": created_at_iso
    }

    try:
        _D1_WRITE_QUEUE.put_nowait(msg_record)
    except Exception:
        # Direct fallback if queue full
        try:
            asyncio.create_task(
                execute_d1_query(
                    "INSERT INTO messages (chat_id, user_id, message_id, user_name, username, chat_title, chat_type, msg_kind, reply_to_msg_id, reply_to_user, reply_to_text, role, content, msg_date, msg_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        clean_chat_id, clean_user_id, int(message_id or 0), msg_record["user_name"], clean_username,
                        msg_record["chat_title"], msg_record["chat_type"], msg_record["msg_kind"], msg_record["reply_to_msg_id"],
                        msg_record["reply_to_user"], msg_record["reply_to_text"],
                        str(role), str(content), j_date_str, time_str, created_at_iso
                    ]
                )
            )
        except RuntimeError:
            pass

async def get_chat_context_async(chat_id: int, max_tokens: int = 20000) -> List[Dict[str, Any]]:
    clean_chat_id = int(chat_id) if isinstance(chat_id, (int, str)) and str(chat_id).lstrip("-").isdigit() else 0

    if clean_chat_id in _CHAT_HISTORIES and _CHAT_HISTORIES[clean_chat_id]:
        selected = []
        token_count = 0
        for m in reversed(_CHAT_HISTORIES[clean_chat_id]):
            t_len = len(m.get("content", "")) // 3
            if token_count + t_len > max_tokens:
                break
            selected.append({"role": m["role"], "content": m["content"]})
            token_count += t_len
        return list(reversed(selected))

    res = await execute_d1_query(
        "SELECT role, content, user_name, username, user_id, created_at FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 300",
        [clean_chat_id]
    )
    if res["success"] and res["results"]:
        msgs = list(reversed(res["results"]))
        _CHAT_HISTORIES[clean_chat_id] = [
            {
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "user_name": m.get("user_name", ""),
                "username": m.get("username", ""),
                "user_id": m.get("user_id", 0),
                "created_at": m.get("created_at", ""),
                "time": time.time()
            }
            for m in msgs
        ]
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
        fts_where_parts = []
        fts_params = []
        if clean_chat_id != 0:
            fts_where_parts.append("m.chat_id = ?")
            fts_params.append(clean_chat_id)
        if target_uid:
            fts_where_parts.append("m.user_id = ?")
            fts_params.append(target_uid)
        if msg_date:
            fts_where_parts.append("m.msg_date = ?")
            fts_params.append(str(msg_date))
        if msg_kind:
            fts_where_parts.append("m.msg_kind = ?")
            fts_params.append(str(msg_kind).lower())

        _fts_q = " ".join(f'"{w}"' for w in tokens[:6]) or f'"{clean_q}"'
        _fts_where = " AND ".join(fts_where_parts)
        _fts_where_sql = f"AND {_fts_where}" if _fts_where else ""
        _fts_sql = (
            "SELECT m.role, m.user_name, m.username, m.user_id, m.chat_title, m.chat_type, m.msg_kind, "
            "m.reply_to_msg_id, m.reply_to_user, m.reply_to_text, m.content, m.msg_date, m.msg_time, m.created_at "
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
        if clean_chat_id != 0:
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
               f"reply_to_user, reply_to_text, content, msg_date, msg_time, created_at FROM messages {where_sql} ORDER BY id DESC LIMIT ?")
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

async def resolve_target_identifier(identifier: str) -> tuple[Optional[int], Optional[str]]:
    """
    Advanced Identity Resolver: Resolves numeric ID, @username, or display name
    (even for users who have NO username) to (user_id, clean_username/display_name).
    """
    clean_id = str(identifier).strip()
    if clean_id.startswith("@"):
        uname = clean_id[1:].lower()
        uid = _USERNAME_TO_ID_MAP.get(uname)
        if not uid:
            res = await execute_d1_query("SELECT user_id FROM user_mappings WHERE username = ?", [uname])
            if res["success"] and res["results"]:
                uid = res["results"][0].get("user_id")
                if uid:
                    _USERNAME_TO_ID_MAP[uname] = uid
        return (uid, uname)
    elif clean_id.lstrip("-").isdigit():
        uid = int(clean_id)
        reverse_uname = None
        for u, i in _USERNAME_TO_ID_MAP.items():
            if i == uid:
                reverse_uname = u
                break
        if not reverse_uname:
            res = await execute_d1_query("SELECT username FROM user_mappings WHERE user_id = ?", [uid])
            if res["success"] and res["results"]:
                u = res["results"][0].get("username")
                if u:
                    reverse_uname = str(u).lower().lstrip("@")
                    _USERNAME_TO_ID_MAP[reverse_uname] = uid
        return (uid, reverse_uname)
    else:
        # Ultra-Powerful Identity Extraction for Users Without @username
        target_name = clean_id.lstrip("@").strip()
        norm_target = re.sub(r"[\s_\-\.]+", " ", target_name).lower()

        # Step 1: Direct lookup in hot _DISPLAY_NAME_TO_ID_MAP (0.001ms)
        if norm_target in _DISPLAY_NAME_TO_ID_MAP:
            rec = _DISPLAY_NAME_TO_ID_MAP[norm_target]
            return (rec["user_id"], rec["username"] or rec["display_name"])

        # Step 2: Partial & Substring matching in _DISPLAY_NAME_TO_ID_MAP
        for k_name, rec in _DISPLAY_NAME_TO_ID_MAP.items():
            if norm_target in k_name or k_name in norm_target:
                return (rec["user_id"], rec["username"] or rec["display_name"])

        # Step 3: Deep Scan in hot in-memory chat histories (_CHAT_HISTORIES)
        for cid, msgs in _CHAT_HISTORIES.items():
            for m in reversed(msgs):
                u_name = str(m.get("user_name", "")).strip()
                if u_name:
                    norm_u = re.sub(r"[\s_\-\.]+", " ", u_name).lower()
                    if norm_target in norm_u or norm_u in norm_target:
                        uid = m.get("user_id")
                        uname = m.get("username") or u_name
                        if uid and int(uid) != ADMIN_ID:
                            _DISPLAY_NAME_TO_ID_MAP[norm_u] = {
                                "user_id": int(uid),
                                "display_name": u_name,
                                "username": uname,
                                "chat_id": cid,
                                "chat_title": m.get("chat_title", ""),
                                "updated_at": ""
                            }
                            return (int(uid), uname)

        # Step 4: Search in banned_users table (Crucial for unban operations when user only exists in blacklist)
        b_sql = """
            SELECT user_id, username, first_name
            FROM banned_users
            WHERE (user_id IS NOT NULL AND user_id > 0 AND (username = ? OR username LIKE ? OR first_name = ? OR first_name LIKE ?))
               OR (username = ? OR username LIKE ? OR first_name = ? OR first_name LIKE ?)
            ORDER BY rowid DESC LIMIT 1
        """
        b_res = await execute_d1_query(b_sql, [target_name, f"%{target_name}%", target_name, f"%{target_name}%", target_name, f"%{target_name}%", target_name, f"%{target_name}%"])
        if b_res["success"] and b_res["results"]:
            row = b_res["results"][0]
            uid = row.get("user_id") or None
            uname = row.get("username") or row.get("first_name")
            return (int(uid) if uid and int(uid) > 0 else None, uname)

        # Step 5: Full Multi-Field Database Search in Cloudflare D1 (messages table)
        # Search by exact name, normalized name, wildcard, or Persian half-space variations
        sql = """
            SELECT user_id, user_name, username, chat_id, chat_title
            FROM messages
            WHERE user_id IS NOT NULL AND user_id > 0
              AND (user_name = ? OR user_name LIKE ? OR username = ? OR username LIKE ?)
            ORDER BY id DESC LIMIT 1
        """
        res = await execute_d1_query(sql, [target_name, f"%{target_name}%", target_name, f"%{target_name}%"])
        if res["success"] and res["results"]:
            row = res["results"][0]
            uid = row.get("user_id")
            uname = row.get("username") or row.get("user_name")
            if uid and int(uid) != ADMIN_ID:
                norm_d1 = re.sub(r"[\s_\-\.]+", " ", str(row.get("user_name", ""))).lower()
                _DISPLAY_NAME_TO_ID_MAP[norm_d1] = {
                    "user_id": int(uid),
                    "display_name": row.get("user_name", ""),
                    "username": uname,
                    "chat_id": row.get("chat_id"),
                    "chat_title": row.get("chat_title", ""),
                    "updated_at": ""
                }
                return (int(uid), uname)

    return (None, clean_id.lower())

async def ban_target_async(
    target: Union[str, int],
    reason: str = "تخلف از قوانین",
    first_name: str = "",
    banned_by: int = 0,
    source_chat_id: int = 0,
    source_chat_title: str = ""
) -> bool:
    """Bans a user and stores full identity + context in D1 (id, username, name, banner, source chat)."""
    target_str = str(target).strip()
    user_id, username = await resolve_target_identifier(target_str)

    if user_id == ADMIN_ID:
        return False

    clean_first = str(first_name or "")[:120]
    clean_by = int(banned_by or 0)
    clean_src = int(source_chat_id or 0)
    clean_src_title = str(source_chat_title or "")[:150]

    # Instantly block in RAM (Zero-latency drop takes effect in microseconds)
    if user_id:
        _BANNED_USERS.add(user_id)
        if user_id in _CHAT_HISTORIES:
            del _CHAT_HISTORIES[user_id]
        if username:
            _BANNED_USERNAMES.add(username.lower().lstrip("@"))
    elif username:
        clean_u = username.lower().lstrip("@")
        _BANNED_USERNAMES.add(clean_u)
        mapped_id = _USERNAME_TO_ID_MAP.get(clean_u)
        if mapped_id:
            _BANNED_USERS.add(mapped_id)
            if mapped_id in _CHAT_HISTORIES:
                del _CHAT_HISTORIES[mapped_id]

    # Asynchronously persist to Cloudflare D1
    if user_id:
        sql = "INSERT OR REPLACE INTO banned_users (user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title) VALUES (?, ?, ?, ?, ?, ?, ?)"
        res = await execute_d1_query(sql, [user_id, username or "", clean_first, reason, clean_by, clean_src, clean_src_title])
        return res.get("success", False)

    elif username:
        clean_u = username.lower().lstrip("@")
        found_uid = _USERNAME_TO_ID_MAP.get(clean_u, 0)
        if not found_uid:
            uid_res = await execute_d1_query("SELECT user_id FROM user_mappings WHERE username = ?", [clean_u])
            if uid_res["success"] and uid_res["results"]:
                found_uid = uid_res["results"][0].get("user_id", 0) or 0
                if found_uid:
                    _USERNAME_TO_ID_MAP[clean_u] = found_uid
                    _BANNED_USERS.add(found_uid)

        sql = "INSERT OR REPLACE INTO banned_users (user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title) VALUES (?, ?, ?, ?, ?, ?, ?)"
        res = await execute_d1_query(sql, [found_uid, clean_u, clean_first, reason, clean_by, clean_src, clean_src_title])
        return res.get("success", False)

    return False

async def unban_target_async(target: Union[str, int]) -> bool:
    target_str = str(target).strip()
    user_id, username = await resolve_target_identifier(target_str)

    # Immediately unban in RAM (Instant unblock)
    if user_id and user_id in _BANNED_USERS:
        _BANNED_USERS.discard(user_id)
    if username:
        clean_u = username.lower().lstrip("@")
        _BANNED_USERNAMES.discard(clean_u)
        mapped = _USERNAME_TO_ID_MAP.get(clean_u)
        if mapped and mapped in _BANNED_USERS:
            _BANNED_USERS.discard(mapped)
    
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
    res = await execute_d1_query("SELECT user_id, username, first_name, reason, banned_by, source_chat_id, source_chat_title, banned_at FROM banned_users ORDER BY banned_at DESC")
    if res["success"]:
        return res["results"]
    return [{"user_id": uid, "username": "", "first_name": "", "reason": "نامشخص", "banned_by": 0, "source_chat_id": 0, "source_chat_title": "", "banned_at": ""} for uid in _BANNED_USERS]

def get_banned_users() -> List[int]:
    return list(_BANNED_USERS)
