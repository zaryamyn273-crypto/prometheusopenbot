import inspect
import functools
import importlib
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Global registry of all executable tools
REGISTRY: Dict[str, Dict[str, Any]] = {}

# Microsecond Idempotent Tool Result Cache
_IDEMPOTENT_TOOL_TTLS: Dict[str, float] = {
    "calculate_math_expression": 3600.0,
    "convert_units": 3600.0,
    "generate_hash_digest": 3600.0,
    "base64_encode_decode": 3600.0,
    "url_encode_decode": 3600.0,
    "color_converter_tool": 3600.0,
    "statistics_summary": 3600.0,
    "generate_qr_code_tool": 1800.0,
    "generate_barcode_tool": 1800.0,
    "resolve_dns": 180.0,
    "check_ssl_certificate": 300.0,
}
_IDEMPOTENT_CACHE_MAX_SIZE = 2048
_IDEMPOTENT_CACHE: Dict[str, Tuple[float, Any]] = {}
_IDEMPOTENT_LOCK = threading.Lock()

def _get_cached_tool_result(cache_key: str) -> Optional[Any]:
    with _IDEMPOTENT_LOCK:
        entry = _IDEMPOTENT_CACHE.get(cache_key)
        if entry is None:
            return None
        exp_time, val = entry
        if time.time() < exp_time:
            return val
        _IDEMPOTENT_CACHE.pop(cache_key, None)
        return None

def _set_cached_tool_result(cache_key: str, val: Any, ttl: float) -> None:
    now = time.time()
    with _IDEMPOTENT_LOCK:
        if len(_IDEMPOTENT_CACHE) >= _IDEMPOTENT_CACHE_MAX_SIZE:
            # Prune expired entries first
            expired = [k for k, (exp, _) in _IDEMPOTENT_CACHE.items() if now >= exp]
            for k in expired:
                _IDEMPOTENT_CACHE.pop(k, None)
            # If still at capacity, evict oldest 20%
            if len(_IDEMPOTENT_CACHE) >= _IDEMPOTENT_CACHE_MAX_SIZE:
                evict_count = _IDEMPOTENT_CACHE_MAX_SIZE // 5
                for k in list(_IDEMPOTENT_CACHE.keys())[:evict_count]:
                    _IDEMPOTENT_CACHE.pop(k, None)
        _IDEMPOTENT_CACHE[cache_key] = (now + ttl, val)

# =========================================================================
# Lazy tool loading: tool modules are imported ONLY when actually needed.
# Importing every module at startup (httpx pools, bs4, PIL, psutil, jdatetime…)
# wastes RAM/time on Railway and pulls full power for trivial turns.
# Keyword-category -> tool modules serving it. A category may map to several
# modules (e.g. admin tools live in system + group_manager + database).
# =========================================================================

_CATEGORY_MODULES: Dict[str, List[str]] = {
    "financial": ["src.tools.financial"],
    "crypto": ["src.tools.financial"],
    "weather": ["src.tools.web_network"],
    "search": ["src.tools.web_network"],
    "ecommerce": ["src.tools.web_network"],
    "network": ["src.tools.web_network"],
    "media": ["src.tools.media"],
    "security": ["src.tools.scientific"],
    "scientific": ["src.tools.scientific"],
    "math": ["src.tools.scientific"],
    "time": ["src.tools.scientific"],
    "github": ["src.tools.github"],
    "admin": ["src.tools.system", "src.tools.admin.group_manager", "src.tools.database"],
    "scheduler": ["src.tools.system"],
    "files": ["src.tools.files"],
    "database": ["src.tools.database"],
    "dev": ["src.tools.dev", "src.tools.system"],
    "internal": ["src.tools.internal"],
}

# Ordered unique module list (stable order => deterministic fallback behavior).
_MODULE_PATHS: List[str] = []
for _paths in _CATEGORY_MODULES.values():
    for _p in _paths:
        if _p not in _MODULE_PATHS:
            _MODULE_PATHS.append(_p)

_LOADED_MODULES: set = set()
_LOAD_LOCK = threading.Lock()


def ensure_module(path: str) -> bool:
    """Import one tool module (idempotent, thread-safe). Returns True if loaded."""
    with _LOAD_LOCK:
        if path in _LOADED_MODULES:
            return True
    try:
        importlib.import_module(path)
    except Exception as e:
        logger.warning(f"Lazy tool module failed to load ({path}): {e}")
        return False
    with _LOAD_LOCK:
        _LOADED_MODULES.add(path)
    return True


def ensure_category(cat: str) -> bool:
    """Ensure every module serving a keyword-category is loaded."""
    ok = True
    for path in _CATEGORY_MODULES.get(cat, []):
        ok = ensure_module(path) and ok
    return ok


def ensure_categories(cats) -> None:
    for cat in cats or []:
        ensure_category(cat)


def ensure_tool(name: str) -> bool:
    """Ensure the module owning tool `name` is loaded (bounded scan, cached)."""
    if name in REGISTRY:
        return True
    with _LOAD_LOCK:
        unloaded = [p for p in _MODULE_PATHS if p not in _LOADED_MODULES]
    if not unloaded:
        return name in REGISTRY or _find_tool_fuzzy(name) is not None
    for path in unloaded:
        ensure_module(path)
        if name in REGISTRY or _find_tool_fuzzy(name) is not None:
            return True
    return name in REGISTRY


def ensure_all() -> None:
    """Load every tool module (tests, stall-escalation, full-cabinet turns)."""
    for path in _MODULE_PATHS:
        ensure_module(path)


def loaded_modules() -> List[str]:
    """Loaded tool-module paths (introspection/testing)."""
    with _LOAD_LOCK:
        return sorted(_LOADED_MODULES)

def _python_type_to_json_type(py_type: Any) -> str:
    """Map Python type annotations to JSON Schema primitive types."""
    if py_type in (int,):
        return "integer"
    elif py_type in (float,):
        return "number"
    elif py_type in (bool,):
        return "boolean"
    elif py_type in (list, List):
        return "array"
    elif py_type in (dict, Dict):
        return "object"
    return "string"

def register_tool(
    name: str,
    description: str,
    category: str = "general"
):
    """
    Decorator to register a tool function into the global registry.
    Automatically generates OpenAPI/OpenAI-compliant JSON function schemas.
    """
    def decorator(func: Callable):
        sig = inspect.signature(func)
        doc = inspect.getdoc(func) or ""

        param_docs: Dict[str, str] = {}
        for line in doc.splitlines():
            line = line.strip()
            if line.startswith(":param "):
                parts = line[7:].split(":", 1)
                if len(parts) == 2:
                    param_docs[parts[0].strip()] = parts[1].strip()

        properties: Dict[str, Any] = {}
        required_params: List[str] = []

        for p_name, param in sig.parameters.items():
            if p_name in ("caller_id", "is_private_chat", "chat_id", "is_admin"):
                continue

            param_type = _python_type_to_json_type(param.annotation)
            param_desc = param_docs.get(p_name, f"پارامتر {p_name}")

            properties[p_name] = {
                "type": param_type,
                "description": param_desc
            }

            if param.default is inspect.Parameter.empty and not str(param.annotation).startswith("typing.Optional"):
                required_params.append(p_name)

        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required_params
                }
            }
        }

        REGISTRY[name] = {
            "func": func,
            "name": name,
            "description": description,
            "category": category,
            "schema": schema,
            "is_async": inspect.iscoroutinefunction(func),
            "signature": sig
        }

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

def get_all_tool_definitions(include_internal: bool = False) -> List[Dict[str, Any]]:
    """Return list of all tool schemas formatted for OpenAI tool calling."""
    ensure_all()
    if include_internal:
        return [t["schema"] for t in REGISTRY.values()]
    return [t["schema"] for t in REGISTRY.values() if t.get("category") != "internal"]

# =========================================================================
# Intelligent Tool Selector (Pre-filter tools based on query intent)
# Reduces payload tokens from ~4000 to <1200, boosting AI generation speed 3x
# =========================================================================

# Precompiled Category Keyword Regex Index for high-throughput zero-latency tool matching
# Precompiled Category Keyword Regex Index for high-throughput zero-latency tool matching
CATEGORY_KEYWORDS = {
    "financial": [
        "دلار", "تتر", "بیتکوین", "بیت کوین", "ارز", "طلا", "سکه", "یورو", "پوند", "درهم", "لیر",
        "کریپتو", "اتریوم", "forex", "crypto", "btc", "eth", "usdt", "nobitex", "binance", "سرمایه", "نرخ طلا", "نرخ ارز", "صرافی",
        "نقره", "نفت", "برنت", "حباب سکه", "ارزش ذاتی", "silver", "oil", "brent", "commodities", "کالاهای اساسی"
    ],
    "crypto": [
        "بیتکوین", "بیت کوین", "کریپتو", "اتریوم", "btc", "eth", "usdt", "nobitex", "binance", "رمزارز", "تون", "داج", "سولانا"
    ],
    "weather": [
        "هوا", "آب و هوا", "آب‌وهوا", "دما", "باران", "برف", "ابری", "weather", "forecast", "پیش بینی", "درجه"
    ],
    "search": [
        "سرچ", "جستجو", "گوگل", "خبر", "اخبار", "search", "news", "پیدا کن", "مقاله", "تحقیق",
        "توییتر", "توییت", "twitter", "tweet", "اکس", "x.com", "توییت ها", "هشتگ", "پست های توییتر",
        "tavily", "تاویلی", "وب", "اینترنت", "اطلاعات روز", "تازه‌ترین", "تازه ترین", "جدیدترین"
    ],
    "ecommerce": [
        "خرید", "دیجیکالا", "دیجی کالا", "دیجی‌کالا", "دیجی", "digikala", "فروشگاه", "فروشگاه اینترنتی",
        "قیمت کالا", "آمازون", "amazon", "ای بی", "ای‌بی", "ebay", "ترب", "torob",
        "خرید آنلاین", "خرید اینترنتی", "خرید کالا", "قیمت دیجیکالا", "قیمت آمازون",
        "قیمت ای بی", "خرید خارجی", "محصولات خارجی", "چند میفروشن", "از کجا بخرم", "قیمت محصول"
    ],
    "network": [
        "ip", "dns", "ssl", "whois", "ping", "دامنه", "هاست", "پورت", "سایت", "لینک", "اینترنت", "وب",
        "osint", "اوسینت", "ردپای دیجیتال", "اطلاعات شخص", "هویت", "استعلام شخص", "پرونده شخص", "کی‌بیس", "keybase"
    ],
    "media": [
        "آهنگ", "اهنگ", "موزیک", "ترانه", "خواننده", "دانلود آهنگ", "دانلود موزیک", "ویس", "وویس", "تلگراف", "telegraph",
        "بارکد", "qr", "lyrics", "متن ترانه", "صوت", "پادکست", "کیوآر", "متن آهنگ",
        "لیریکس", "تایم دار", "lrc", "synced lyrics", "بارکد میله‌ای", "qrcode", "barcode",
        "خط خورده", "آسیب دیده", "مخدوش", "پاره شده", "بازسازی بارکد", "ساخت بارکد", "تولید بارکد", "ean13", "code128",
        "تولید عکس", "ساخت عکس", "ساخت تصویر", "تولید تصویر", "عکس بکش", "تصویر بکش", "نقاشی بکش", "generate image", "draw", "paint", "dall-e", "flux", "طراحی عکس"
    ],
    "security": [
        "هش", "hash", "رمزنگاری", "base64", "uuid",
        "شناسه یکتا", "یو یو آی دی", "انکد", "دیکد", "url encode"
    ],
    "scientific": [
        "آمار", "میانگین", "انحراف معیار", "تبدیل واحد", "متر", "کیلو", "فارنهایت", "رنگ", "rgb", "hex",
        "کیلومتر", "مایل", "سانتی", "کلوین", "json", "جی سان", "واحد", "پالت", "مکمل"
    ],
    "github": [
        "گیت هاب", "github", "ریپازیتوری", "مخزن", "repo", "ریپو", "سورس", "کدباز", "اوپن سورس",
        "کامیت", "commit", "ایسیو", "issue", "ریلیز", "release", "ترند", "trending",
        "پروفایل", "کاربر گیت", "مشارکت", "contributor", "pkgbuild", "پکیج بیلد", "cmake", "سی میک", "cmakelists", "ساخت ریپو", "ساخت مخزن", "کامیت فایل", "نوشتن فایل"
    ],
    "admin": [
        "بن", "آنبن", "مسدود", "لیست سیاه", "قانون ابدی", "دستور دائمی", "حافظه دائمی", "وضعیت سرور", "تله متری", "لینک گروه", "سکوت", "میوت", "لغو سکوت", "رفع سکوت", "آنمیوت", "لیست سکوت", "mutelist", "سایلنت", "ساکت", "دهنتو ببند", "حرف نزن", "بیدار شو", "بیدارشو", "بلند شو", "silence", "unsilence", "shutup", "quiet", "بخواب",
        "ram", "cpu", "گروه", "گروه‌ها", "گروهها", "گروهم", "گروهام", "گروه هام", "گروه های من", "گروه های فعال", "لیست گروه", "لیست گروه‌ها", "لفت", "خروج از گروه", "bangroup", "groups", "my groups", "list groups", "show groups", "group list",
        "کانال", "کانال‌ها", "کانالها", "کانال های من", "channels", "public channels", "چت ها", "چت‌ها", "chats",
        "سرور", "سرورت", "سیستم", "سخت افزار", "حافظه سرور", "آیدی", "شناسه", "user id", "userid", "getid",
        "حذف پیام", "پاک کن", "پیام هات رو پاک کن", "پیام‌هات رو پاک کن", "پیام هاتو پاک کن", "purge", "clean", "حذف پیام‌ها", "حذف دسته‌جمعی", "پاکسازی پیام",
        "ریلوی", "railway", "ری‌دیپلوی", "redeploy", "وضعیت ریلوی", "سرور ریلوی", "متغیرهای ریلوی"
    ],
    "files": [
        "فایل", "پی دی اف", "پی‌دی‌اف", "pdf", "اکسل", "excel", "xlsx", "word", "فایل ورد", "docx", "csv", "فایل متنی", "txt", "داکیومنت", "سند", "پی دی اف ساز"
    ],
    "math": [
        "حساب", "ریاضی", "محاسبه", "فرمول", "ضرب", "تقسیم", "جمع", "منها", "توان", "جذر", "درصد",
        "فاکتوریل", "لگاریتم", "سینوس", "کسینوس", "میانگین", "آمار", "factorial"
    ],
    "time": [
        "ساعت", "تاریخ", "تقویم", "امروز چندمه", "ساعت چنده", "time", "date"
    ],
    "scheduler": [
        "یادآوری", "یادم بنداز", "زمانبندی", "زمان‌بندی", "کرون", "کرون‌جاب", "کرون جاب", "cron", "cronjob", "remind", "reminder", "schedule", "scheduler",
        "تسک", "هر روز ساعت", "دقیقه دیگه", "ساعت بعد", "تسک زمان‌بندی‌شده", "لیست یادآوری", "لغو یادآوری",
        "فردا ساعت", "پس فردا ساعت", "ساعت دیگه", "پیام زمان‌بندی", "پیام زمانبندی", "پیام زمان‌بندی‌شده",
        "پیام زمانبندی شده", "تنظیم پیام", "ارسال پیام", "بفرست به گروه", "بفرست تو گروه", "فرستادن پیام",
        "تسک گروه", "زمانبندی گروه", "تایم زون", "منطقه زمانی", "timezone", "tz",
        "هر روز", "روزانه", "daily", "every"
    ],
    "database": [
        "سوابق", "پیام های قبلی", "پیام‌های قبلی", "تاریخچه", "چت", "دیتابیس", "ذخیره در دیتابیس", "کانفیگ",
        "یادداشت", "d1", "kv", "کلودفلر", "ذخیره رکورد", "بازیابی رکورد", "حذف رکورد", "لیست رکوردها",
        "خلاصه", "خلاصه کن", "خلاصه چت", "خلاصه گروه", "خلاصه‌سازی", "خلاصه سازی", "جمع بندی", "جمع‌بندی",
        "خلاصه پیام", "۵۰ پیام", "۱۰۰ پیام", "۵۰ تا پیام", "۱۰۰ تا پیام", "پنجاه پیام", "صد پیام", "summary", "summarize"
    ],
    "dev": [
        "اجرای کد", "کد را اجرا کن", "کد رو اجرا کن", "کد را تست کن", "کد رو تست کن", "run code", "run python", "execute code",
        "سندباکس", "سندباکس ابری", "sandbox", "e2b", "کد ابری",
        "ردیت", "reddit", "ساب ردیت", "ساب‌ردیت",
        "استک اورفلو", "استک‌اورفلو", "stackoverflow",
        "ایشوهای گیت‌هاب", "github issues"
    ]
}

_CATEGORY_PATTERNS: Dict[str, re.Pattern] = {}

def _build_category_index() -> Dict[str, re.Pattern]:
    patterns = {}
    for cat, kws in CATEGORY_KEYWORDS.items():
        if not kws:
            continue
        # Sort longest keywords first to prevent short prefixes shadowing longer phrases
        sorted_kws = sorted(kws, key=len, reverse=True)
        escaped = [re.escape(k) for k in sorted_kws]
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)
        patterns[cat] = pattern
    return patterns

_CATEGORY_PATTERNS = _build_category_index()

_SMART_FILTER_CACHE: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
_SMART_FILTER_LOCK = threading.Lock()
_SMART_FILTER_MAX = 512


def _cache_smart_tools(key: str, schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    with _SMART_FILTER_LOCK:
        _SMART_FILTER_CACHE[key] = schemas
        _SMART_FILTER_CACHE.move_to_end(key)
        if len(_SMART_FILTER_CACHE) > _SMART_FILTER_MAX:
            _SMART_FILTER_CACHE.popitem(last=False)
    return schemas

_COMPILED_SHORT_KW: Dict[str, Any] = {}


def _kw_hit_compiled(kw: str, prompt_lower: str) -> bool:
    pat = _COMPILED_SHORT_KW.get(kw)
    if pat is None:
        pat = re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)", re.IGNORECASE)
        _COMPILED_SHORT_KW[kw] = pat
    return pat.search(prompt_lower) is not None


def get_smart_tools_for_prompt(prompt: str, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    Intelligently selects the most relevant tool schemas based on prompt intent.
    Always includes universally useful tools while filtering out unrelated heavy categories.
    When is_admin is False, admin-only categories/tools are strictly excluded from the schema.
    Results are memoized (512-entry LRU) so repeated intents cost ~0ms.
    """
    cache_key = f"{'adm:' if is_admin else 'usr:'}{(prompt or '')[:160].lower().strip()}"
    with _SMART_FILTER_LOCK:
        cached = _SMART_FILTER_CACHE.get(cache_key)
        if cached is not None:
            _SMART_FILTER_CACHE.move_to_end(cache_key)
            return cached
    prompt_lower = (prompt or "").lower()

    # 1. Pure casual conversation / greeting detector: zero tool overhead = ultra fast sub-second turn
    pure_conversational = [
        "سلام", "درود", "خوبی", "چطوری", "چه خبر", "خسته نباشی", "ممنون", "مرسی",
        "تشکر", "دمت گرم", "فدات", "قربانت", "سلامت باشی", "صبح بخیر", "شب بخیر",
        "hi", "hello", "hey", "thanks", "thank you"
    ]
    is_pure_chat = any(w in prompt_lower for w in pure_conversational) and len(prompt_lower) < 60
    if is_pure_chat:
        return _cache_smart_tools(cache_key, [])

    # 2. Pure knowledge / conceptual definition detector: zero tool overhead = instant sub-second AI response
    _def_phrases = [
        "چیست", "چیه", "تعریف", "توضیح بده", "توضیح بدید", "توضیح دهید", "توضیح بفرمایید",
        "معنی", "مفهوم", "یعنی چه", "یعنی چی", "منظور از",
        "چگونه کار میکند", "چگونه کار می کند", "چگونه کار میکنه", "چگونه کار می کنه",
        "چطور کار میکند", "چطور کار می کند", "چطور کار میکنه", "چطور کار می کنه",
        "طرز کار", "نحوه کار", "فرق ", "تفاوت ", "مقایسه ",
        "how does", "what is", "meaning of", "definition of", "explain "
    ]
    _has_def = any(w in prompt_lower for w in _def_phrases) or (
        re.search(r"\b(?:فرق|تفاوت)\b", prompt_lower) is not None and any(w in prompt_lower for w in ("با", "و", "between", "and"))
    )
    _is_concept_definition = (
        _has_def
        and not any(w in prompt_lower for w in [
            "امروز", "الان", "لحظه ای", "لحظه‌ای", "زنده", "قیمت", "چنده", "ساعت", "تاریخ", "تقویم",
            "جدید", "آخرین", "اخبار", "سرچ کن", "جستجو کن", "لینک", "سایت", "دیجیکالا", "خرید",
            "فروشگاه", "آمازون", "ای بی", "ebay", "amazon", "ترب", "torob", "latest", "today", "now",
            "هوا", "آب و هوا", "آهنگ", "موزیک", "پلی", "play", "عکس", "تصویر", "بکش", "طراحی",
            "بن ", "آنبن", "میوت", "سایلنت"
        ])
        and len(prompt_lower) < 400
    )
    if _is_concept_definition:
        return _cache_smart_tools(cache_key, [])

    # 3. Pure code generation, algorithm, or programming syntax detector: zero tool overhead = instant sub-second AI response
    _code_request_markers = [
        "کد بنویس", "تابع بنویس", "اسکریپت بنویس", "برنامه بنویس", "کد پایتون", "کد جاوا",
        "الگوریتم", "مرتب سازی", "مرتب‌سازی", "سورت", "چطوری بنویسم", "چطور بنویسم",
        "چگونه بنویسم", "نحوه نوشتن", "روش نوشتن", "پیاده سازی", "پیاده‌سازی", "کدشو بده", "کدش رو بده",
        "write code", "write a python", "write a function", "write script", "implement ", "how to write"
    ]
    _prog_lang_tokens = ["پایتون", "python", "جاوااسکریپت", "javascript", "ts", "typescript", "c++", "cpp", "c#", "golang", "php", "sql", "css", "html", "bash"]
    _prog_concepts = ["چطور", "چگونه", "چطوری", "نحوه", "روش", "how to", "how do", "کد", "تابع", "لیست", "دیکشنری", "آرایه", "حلقه", "فانکشن", "ارور", "خطا", "بنویس", "تایپ", "کلاس"]
    _is_programming_query = any(lang in prompt_lower for lang in _prog_lang_tokens) and any(w in prompt_lower for w in _prog_concepts)
    _has_code_intent = any(w in prompt_lower for w in _code_request_markers) or _is_programming_query

    _is_explicit_exec_or_search = any(w in prompt_lower for w in [
        "اجرا کن", "اجرای کد", "تست کن", "run code", "run python", "execute", "سندباکس", "sandbox", "e2b",
        "استک اورفلو", "stackoverflow", "ردیت", "reddit", "گیت هاب", "github",
        "امروز", "الان", "زنده", "قیمت", "چنده", "اخبار", "سرچ کن", "جستجو کن", "لینک", "سایت", "دانلود موزیک", "دانلود آهنگ", "عکس بکش", "تصویر بکش", "بن "
    ])
    if _has_code_intent and not _is_explicit_exec_or_search and len(prompt_lower) < 600:
        return _cache_smart_tools(cache_key, [])

    # Identify relevant categories using precompiled category word-boundary regex index
    relevant_categories = set()
    for cat, pat in _CATEGORY_PATTERNS.items():
        if cat == "internal":
            continue
        if pat.search(prompt_lower):
            relevant_categories.add(cat)
    relevant_categories.discard("internal")

    # --- Claim-verify auto-attach: factual statements with recency/version
    # signals are VERIFY-BEFORE-ANSWER prompts. A bare statement like
    # "X is the latest model" must trigger web_search just like a question,
    # otherwise the model confirms stale facts from memory. Runs BEFORE the
    # question-marker gate so statements without ?/question words still match.
    _recency_signals = [
        "latest", "newest", "recent", "update", "version", "release",
        "pro", "flash", "ultra", "plus", "max",
    ]
    _fa_recency = [
        "\u0622\u062e\u0631\u06cc\u0646", "\u062c\u062f\u06cc\u062f\u062a\u0631\u06cc\u0646",
        "\u062c\u062f\u06cc\u062f", "\u062a\u0627\u0632\u0647", "\u0646\u0633\u0644",
        "\u0645\u062f\u0644", "\u0646\u0633\u062e\u0647", "\u067e\u0631\u0686\u0645\u062f\u0627\u0631",
        "\u067e\u06cc\u0634\u0631\u0641\u062a\u0647", "\u0645\u0639\u0631\u0641\u06cc",
    ]
    _pl = prompt_lower
    _has_version_token = (
        any(_m in _pl for _m in _recency_signals)
        or any(_w in _pl for _w in _fa_recency)
    )
    if _has_version_token and "search" not in relevant_categories:
        relevant_categories.add("search")

    # --- Search auto-attach: question-shaped prompts ALWAYS get web_search ---
    # (who/what/when/where/why/how, ؟/?, کی/کجا/چرا/چطور/آیا/کدوم/چند …).
    # The model then answers from live results instead of guessing.
    _question_markers = [
        "؟", "?", "کیه", "کجاست", "کجاست؟", "چرا", "چطور", "چگونه",
        "کجا", "کی", "آیا", "کدوم", "کدام", "چند", "چه", "who", "what",
        "when", "where", "why", "how", "which", "is ", "are ",
    ]
    _looks_question = any(_qm in prompt_lower for _qm in _question_markers)
    if _looks_question and "search" not in relevant_categories and not _has_def and not _has_code_intent:
        # …unless it's pure chatter or a deterministic fast-path query.
        _no_search_words = ["سلام", "خوبی", "چطوری", "ممنون", "مرسی", "باشه", "اوکی"]
        if not any(_w in prompt_lower for _w in _no_search_words):
            relevant_categories.add("search")

    # --- Price Disambiguation Protocol (Commodities/Goods vs Financial Exchanges) ---
    price_words = ["قیمت", "نرخ", "چنده", "چند است", "چقدره", "قیمتش", "ارزش", "تابلو"]
    has_price_query = any(pw in prompt_lower for pw in price_words)
    if has_price_query:
        fin_anchors = [
            "دلار", "ارز", "طلا", "سکه", "یورو", "پوند", "درهم", "لیر", "یوان", "فرانک",
            "بیتکوین", "بیت کوین", "بیت", "تتر", "اتریوم", "اتر", "کریپتو", "رمزارز",
            "forex", "crypto", "btc", "eth", "usdt", "sol", "ton", "doge", "not", "xrp",
            "trx", "ada", "bnb", "pepe", "shib", "avax", "link", "sui", "near", "dot",
            "pol", "matic", "kas", "arb", "apt", "fet", "rndr", "دوج", "نات", "ریپل",
            "ترون", "کاردانو", "بایننس", "پپه", "شیبا", "سولانا", "تون کوین", "آوالانچ",
            "نیر", "پولکادات", "فانتوم", "آبشده", "مثقال", "انس", "امامی", "بهار آزادی",
            "نیم سکه", "ربع سکه", "سکه گرمی"
        ]
        has_fin = any(fa in prompt_lower for fa in fin_anchors)
        commodity_anchors = ["گوشی", "موبایل", "آیفون", "سامسونگ", "ماشین", "خودرو", "پراید", "بنزین", "سهام", "آهن", "لپتاپ", "کنسول", "ps5", "خرید"]
        has_commodity = any(ca in prompt_lower for ca in commodity_anchors)
        if has_fin:
            relevant_categories.add("financial")
        if has_commodity or not has_fin:
            # Query is asking for commodity/car/phone/goods/services price -> web_search is required!
            relevant_categories.add("search")

    # --- Implicit intent detectors (no exact keyword needed) ---
    _implicit = {
        "weather": ["بیرون", "بارون", "برف", "سرد", "گرم", "آفتاب", "چتر", "لباس بپوشم"],
        "media": ["بذار", "پخش", "بفرست", "بده", "پلی", "play", "پخش کن", "بکش", "طراحی", "draw", "paint"],
        "financial": ["بخرم", "بفروشم", "سرمایه", "سود", "گرون", "ارزون", "تحلیل بازار"],
        "search": ["جدیدترین", "آخرین", "تازه", "خبر", "اطلاعات", "درباره", "کیه"],
        "files": ["بساز", "درست کن", "آماده کن", "اکسل", "جدول", "لیست", "گزارش"],
        "admin": ["چطوره", "خوبه", "سالمه", "وضعیت"],
        "time": ["امروز", "فردا", "دیروز", "الان", "فعلا", "کی"],
        "database": ["یادداشت", "یادم", "ذخیره", "بنویس", "ثبت"],
        "scheduler": ["یادآوری", "یادم", "کرون", "تسک", "زمانبندی", "زمان‌بندی", "remind", "schedule", "cron", "تنظیم کن"],
    }
    for cat, hints in _implicit.items():
        if any(h in prompt_lower for h in hints):
            # media/file/admin hints are noisy alone: need a second signal
            if cat in ("media", "files", "admin", "time", "search"):
                # Latin song/music requests ("play hello adele") carry no Persian anchor —
                # the bare verbs play/پلی + send-verbs are themselves music intent.
                _bare_music_verbs = ("play", "پلی")
                if cat == "media" and any(v in prompt_lower for v in _bare_music_verbs):
                    relevant_categories.add(cat)
                    continue
                anchor = {
                    "media": ["آهنگ", "موزیک", "ترانه", "خواننده", "شعر", "صدا", "ویس", "صوت", "شاد", "غمگین", "پادکست", "مقاله", "تلگراف", "qr", "کیوآر", "بارکد", "hello", "song", "music", "audio", "mp3", "عکس", "تصویر", "تصویرسازی", "نقاشی", "طراحی", "image", "photo", "picture", "draw", "paint", "dall-e", "flux"],
                    "files": ["فایل", "اکسل", "ورد", "pdf", "پی دی اف", "پی‌دی‌اف", "csv", "json", "متن", "سند", "هزینه", "جدول"],
                    "admin": ["سرور", "سرورت", "سیستم", "ربات", "خودت"],
                    "time": ["ساعت", "تاریخ", "امروز", "فردا", "دیروز", "جلسه", "قرار"],
                    "search": ["اخبار", "خبر", "تکنولوژی", "فناوری", "جهان", "ایران", "جدید"],
                }[cat]
                if any(a in prompt_lower for a in anchor):
                    relevant_categories.add(cat)
            else:
                relevant_categories.add(cat)

    # --- Co-activation: tools that answer together ---
    _coactivate = {
        "financial": {"time"},        # prices pair with official clock/date
        "weather": {"time"},
        "search": {"time"},
        "admin": {"time"},
        "github": {"search"},
        "security": {"network"},
        "database": {"time"},
        "scheduler": {"time"},
    }
    for cat in list(relevant_categories):
        relevant_categories.update(_coactivate.get(cat, set()))

    # --- Multi-request bundle: several intents at once -> send the full set ---
    _intent_hits = len(relevant_categories - {"time"})
    _complex = _intent_hits >= 4

    # Core bundle that are fast & frequently used (live in scientific).
    core_names = {
        "get_current_datetime_info", "calculate_math_expression"
    }
    # The schemas below are read from REGISTRY, so their owner modules must be
    # loaded first — but ONLY those modules (this is what keeps lazy loading lazy).
    # scientific is near-free (stdlib + pytz/jdatetime, already pulled by database).
    ensure_categories(relevant_categories)
    ensure_category("scientific")

    # If no specific category matched:
    if not relevant_categories:
        # For generic questions, provide only web_search & clock without clutter
        ensure_categories({"search"})
        core_names.update({"tavily_search", "web_search", "get_current_datetime_info"})
        out = [t["schema"] for name, t in REGISTRY.items() if name in core_names]
        return _cache_smart_tools(cache_key, out)

    selected_schemas = []
    selected_names = set()

    # Strict Ban vs Unban Isolation Filter directly in registry:
    unban_keywords = ["آنبن", "آن بن", "انبن", "unban", "از بن دربیار", "از مسدودی", "رفع مسدودیت", "آزادش کن", "آزاد کن"]
    is_unban_intent = any(uk in prompt_lower for uk in unban_keywords)

    ban_keywords = ["بنش کن", "مسدودش کن", "مسدود", "اخراج", "ban", "بن "]
    # Note: avoid matching "بن" inside "آنبن"
    is_ban_intent = not is_unban_intent and (
        any(bk in prompt_lower for bk in ban_keywords) or
        (re.search(r"(?<![آا])بن\b", prompt_lower) is not None)
    )

    wants_id_explicitly = any(ik in prompt_lower for ik in ["آیدی چنده", "شناسه چنده", "آیدی عددی", "آیدیش چنده", "استعلام آیدی", "getid", "آیدیش رو بده"])
    exclude_extract_id = is_ban_intent and not wants_id_explicitly

    # Guaranteed inclusion and highest priority (#1 position) for AI image generation:
    _img_intent_hints = (
        "بکش", "draw", "paint", "تولید عکس", "تولید تصویر", "ساخت عکس", "ساخت تصویر",
        "عکس بساز", "تصویر بساز", "عکس بکش", "تصویر بکش", "نقاشی بکش",
        "generate image", "create image", "dall-e", "flux", "text-to-image", "text to image"
    )
    _non_img_intent = ("کد", "اسکریپت", "پایتون", "الگوریتم", "چیست", "چیه", "کیست", "قیمت", "چنده", "دانلود")
    if any(_ih in prompt_lower for _ih in _img_intent_hints) and not any(_nw in prompt_lower for _nw in _non_img_intent):
        ensure_module("src.tools.media")
        if "generate_ai_image" in REGISTRY and "generate_ai_image" not in selected_names:
            selected_schemas.append(REGISTRY["generate_ai_image"]["schema"])
            selected_names.add("generate_ai_image")

    # Guaranteed priority inclusion for admin moderation (ban, unban, mute)
    if is_admin:
        if is_ban_intent:
            ensure_module("src.tools.system")
            if "ban_user_tool" in REGISTRY and "ban_user_tool" not in selected_names:
                selected_schemas.append(REGISTRY["ban_user_tool"]["schema"])
                selected_names.add("ban_user_tool")
        if is_unban_intent:
            ensure_module("src.tools.system")
            if "unban_user_tool" in REGISTRY and "unban_user_tool" not in selected_names:
                selected_schemas.append(REGISTRY["unban_user_tool"]["schema"])
                selected_names.add("unban_user_tool")
        _is_mute = any(k in prompt_lower for k in ("میوت", "سکوت", "ساکت", "سایلنت", "mute"))
        if _is_mute:
            ensure_module("src.tools.system")
            if "mute_user_tool" in REGISTRY and "mute_user_tool" not in selected_names:
                selected_schemas.append(REGISTRY["mute_user_tool"]["schema"])
                selected_names.add("mute_user_tool")

    for name, t in REGISTRY.items():
        cat = t.get("category", "")
        if cat == "internal":
            continue
        if cat == "admin" and not is_admin:
            continue
        if exclude_extract_id and name == "extract_user_id_tool":
            continue

        # Slim Search Cabinet: keep prompt lean and eliminate LLM hesitation.
        # web_search and fetch_webpage_content handle 99% of queries.
        if cat == "search":
            if name in ("deep_search_and_read",) and not any(k in prompt_lower for k in ("تحقیق عمیق", "مطالعه صفحات", "deep search", "deep research")):
                continue
            if name in ("twitter_search",) and not any(k in prompt_lower for k in ("توییتر", "توییت", "twitter", "x.com", "پست توییتر")):
                continue
            if name in ("tavily_search", "live_news"):
                # web_search already handles live news and multi-engine/Tavily search natively
                continue

        # Slim GitHub Cabinet: attach only relevant GitHub sub-tools instead of the full suite
        if cat == "github":
            is_create_repo = any(k in prompt_lower for k in ("ساخت مخزن", "مخزن جدید", "ریپو جدید", "create repo", "create repository", "ریپوزیتوری بساز"))
            is_pkg_build = any(k in prompt_lower for k in ("pkgbuild", "arch", "aur", "پکیج آرچ", "cmake", "cmakelists"))
            is_code_read = any(k in prompt_lower for k in ("کد", "فایل", "file", "tree", "پوشه", "شاخه", "برنچ", "read_file", "سورس"))
            if is_create_repo:
                if name not in ("github_create_repository", "github_create_or_update_file"):
                    continue
            elif is_pkg_build:
                if name not in ("github_generate_pkgbuild", "github_generate_cmake", "github_create_or_update_file"):
                    continue
            elif is_code_read:
                if name not in ("github_read_file", "github_list_tree", "github_search_code"):
                    continue
            else:
                if name not in ("github_search_repositories", "github_repo_info", "github_read_readme"):
                    continue

        # Slim Media Cabinet: attach only relevant media sub-tools based on intent
        if cat == "media":
            _is_music = any(k in prompt_lower for k in ("آهنگ", "اهنگ", "موزیک", "ترانه", "خواننده", "دانلود آهنگ", "دانلود موزیک", "لیریکس", "متن ترانه", "متن آهنگ", "song", "music", "track", "پلی", "play"))
            _is_barcode = any(k in prompt_lower for k in ("بارکد", "qr", "کیوآر", "barcode", "qrcode", "ean13", "code128", "مخدوش"))
            _is_voice = any(k in prompt_lower for k in ("ویس", "وویس", "صوت", "تبدیل ویس", "transcribe", "صدا"))
            _is_telegraph = any(k in prompt_lower for k in ("تلگراف", "telegraph", "مقاله"))
            if _is_music:
                if name not in ("download_music_track", "get_song_lyrics"):
                    continue
            elif _is_barcode:
                if name not in ("generate_barcode_tool", "generate_qr_code_tool", "reconstruct_damaged_barcode_tool"):
                    continue
            elif _is_voice:
                if name not in ("transcribe_audio_tool",):
                    continue
            elif _is_telegraph:
                if name not in ("publish_telegraph_article",):
                    continue
            else:
                if name not in ("download_music_track", "generate_qr_code_tool"):
                    continue

        # Slim Admin Cabinet: prevent code execution or railway redeploy tools from polluting general moderation requests
        if cat == "admin":
            if name in ("e2b_run_code", "e2b_run_command", "e2b_status", "execute_python_code"):
                if not any(k in prompt_lower for k in ("اجرا", "run", "سندباکس", "sandbox", "e2b", "execute", "کد")):
                    continue
            if name in ("railway_status_tool", "railway_redeploy_tool"):
                if not any(k in prompt_lower for k in ("ریلوی", "railway", "ری‌دیپلوی", "redeploy")):
                    continue
            if name in ("purge_chat_messages_tool",):
                if not any(k in prompt_lower for k in ("پاک", "حذف پیام", "purge", "clean")):
                    continue

        if cat in relevant_categories or name in core_names:
            if name not in selected_names:
                selected_schemas.append(t["schema"])
                selected_names.add(name)

    # Guaranteed inclusion for admin group and identity governance:
    if is_admin:
        _admin_group_hints = ("گروه", "group", "کانال", "channel", "چت", "chat")
        if any(_gh in prompt_lower for _gh in _admin_group_hints):
            ensure_module("src.tools.admin.group_manager")
            for _gt in ("list_joined_groups_tool", "list_public_channels_tool", "leave_group_by_admin_tool", "ban_group_by_name_or_id_tool"):
                if _gt in REGISTRY and _gt not in selected_names:
                    selected_schemas.append(REGISTRY[_gt]["schema"])
                    selected_names.add(_gt)

        _admin_id_hints = ("آیدی", "شناسه", "user id", "userid", "getid", "هویت", "استخراج آیدی", "مشخصات")
        if any(_ih in prompt_lower for _ih in _admin_id_hints) and not exclude_extract_id:
            ensure_module("src.tools.system")
            if "extract_user_id_tool" in REGISTRY and "extract_user_id_tool" not in selected_names:
                selected_schemas.append(REGISTRY["extract_user_id_tool"]["schema"])
                selected_names.add("extract_user_id_tool")

    # Strict Ecommerce Isolation: never attach heavy ecommerce shopping tools (digikala, amazon, ebay)
    # unless prompt explicitly mentions buying, shopping, or specific store names.
    _ecommerce_stores = {"digikala_search", "amazon_search", "ebay_search"}
    _has_ecom_intent = any(w in prompt_lower for w in [
        "خرید", "فروشگاه", "دیجیکالا", "دیجی کالا", "آمازون", "ای بی", "ای‌بی", "ebay", "amazon", "digikala", "چند میفروشن", "از کجا بخرم", "قیمت محصول"
    ])
    if not _has_ecom_intent:
        selected_schemas = [s for s in selected_schemas if (s.get("function", {}) or {}).get("name") not in _ecommerce_stores]
    else:
        ensure_category("web_network")
        for store_t in ("digikala_search", "amazon_search", "ebay_search"):
            if store_t in REGISTRY and store_t not in selected_names:
                selected_schemas.append(REGISTRY[store_t]["schema"])
                selected_names.add(store_t)

    # Dynamic Tool Budget (Prefill TTFT Latency Optimization):
    # Cap total tools passed to LLM to 8 (or 10 for complex multi-intent) to keep prompt prefill under 1,200 tokens
    max_tool_cap = 10 if _complex else 8
    if len(selected_schemas) > max_tool_cap:
        selected_schemas = selected_schemas[:max_tool_cap]

    return _cache_smart_tools(cache_key, selected_schemas)

def get_tools_by_category(category: str) -> List[Dict[str, Any]]:
    """Return all tools belonging to a specific category."""
    ensure_all()
    return [t for t in REGISTRY.values() if t["category"] == category]

def _find_tool_fuzzy(name: str) -> Optional[Dict[str, Any]]:
    """Finds a tool even if name has slight prefix/suffix deviations."""
    if name in REGISTRY:
        return REGISTRY[name]
    clean_name = name.lower().replace("-", "_").strip()
    if clean_name in REGISTRY:
        return REGISTRY[clean_name]
    for k, v in REGISTRY.items():
        if k.lower() == clean_name or k.lower().endswith(clean_name) or clean_name.endswith(k.lower()):
            return v
    return None

FAILURE_MARKERS = (
    "یافت نشد", "اختلال", "در دسترس نیست", "موجود نیست",
    "موفق نشد", "در دسترس قرار نگرفت", "خطا در اجرا",
)

TOOL_FALLBACKS: Dict[str, List[str]] = {
    # Internal bot_* tools exist in the registry (category=internal) and are
    # valid fallback targets — execute_registered_tool resolves them directly.
    "get_price": ["get_crypto_overview", "bot_fallback_search"],
    "get_crypto_overview": ["get_price", "bot_fallback_search"],
    "get_gold_and_coin_price": ["get_fiat_overview", "bot_fallback_search"],
    "get_fiat_overview": ["get_gold_and_coin_price", "bot_fallback_search"],
    "get_global_forex_rates": ["get_fiat_overview", "bot_fallback_search"],
    "get_weather": ["live_news", "bot_fallback_search"],
    "web_search": ["deep_search_and_read", "bot_fallback_search"],
    "deep_search_and_read": ["web_search", "bot_fallback_search"],
    "live_news": ["web_search", "bot_news_fallback"],
    "fetch_webpage_content": ["web_search", "quick_http_inspect_tool"],
    "twitter_search": ["web_search", "live_news"],
    "reddit_search": ["web_search", "bot_fallback_search"],
    "stackoverflow_search": ["web_search", "github_issues_search"],
    "github_issues_search": ["stackoverflow_search", "web_search"],
    "github_search_repositories": ["github_repo_info", "bot_fallback_search"],
    "digikala_search": ["amazon_search", "ebay_search", "web_search"],
    "amazon_search": ["ebay_search", "digikala_search", "web_search"],
    "ebay_search": ["amazon_search", "digikala_search", "web_search"],
    "get_commodities_price": ["get_gold_and_coin_price", "web_search"],
    "download_music_track": ["get_song_lyrics", "bot_music_fallback"],
    "get_song_lyrics": ["bot_lyrics_fallback", "bot_fallback_search"],
    "transcribe_audio_tool": ["bot_fallback_search"],
    "check_website_status": ["quick_http_inspect_tool", "resolve_dns"],
    "resolve_dns": ["get_ip_info", "quick_http_inspect_tool"],
    "get_ip_info": ["resolve_dns", "quick_http_inspect_tool"],
    "check_ssl_certificate": ["check_website_status", "quick_http_inspect_tool"],
    "publish_telegraph_article": ["create_and_upload_file", "bot_file_fallback_publish"],
    "create_and_upload_file": ["publish_telegraph_article", "bot_file_fallback_publish"],
    "generate_barcode_tool": ["generate_qr_code_tool", "bot_qr_fallback"],
    "reconstruct_damaged_barcode_tool": ["generate_barcode_tool", "generate_qr_code_tool"],
    "generate_qr_code_tool": ["generate_barcode_tool", "bot_qr_fallback"],
    "search_conversation_history": ["cloudflare_d1_search_records", "cloudflare_d1_list_records"],
    "cloudflare_d1_search_records": ["cloudflare_d1_list_records", "search_conversation_history"],
    "cloudflare_kv_retrieve": ["cloudflare_d1_retrieve_record"],
    "cloudflare_d1_retrieve_record": ["cloudflare_kv_retrieve", "cloudflare_d1_list_records"],
    "mute_user_tool": ["ban_user_tool"],
    "unmute_user_tool": ["unban_user_tool"],
    # Tavily is optional: when no key exists it auto-falls back to free web_search.
    "tavily_search": ["web_search", "deep_search_and_read"],
}


def _looks_like_failure(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, dict):
        return result.get("type") == "error"
    if not isinstance(result, str):
        return False
    s = result.strip()
    if not s:
        return True
    if s.startswith("ابزار ") and "یافت نشد" in s:
        return True
    return any(m in s for m in FAILURE_MARKERS)


def _first_queryish(args: Dict[str, Any]) -> str:
    for key in ("query", "topic", "song_title", "city", "symbol", "domain", "target", "text_or_url", "key", "title", "url", "q",
               "repo", "filepath", "file_path", "filename", "content", "branch", "path"):
        v = args.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for v in args.values():
        if isinstance(v, str) and len(v.strip()) >= 2 and not v.strip().startswith("{"):
            return v.strip()
    return ""


def _map_args_for_fallback(primary_name: str, primary_args: Dict[str, Any], fallback_name: str) -> Dict[str, Any]:
    q = _first_queryish(primary_args)
    mapped: Dict[str, Any] = {}
    if "query" in (primary_args or {}):
        mapped["query"] = primary_args.get("query")
    if q:
        mapped.update({
            "query": q, "topic": q, "song_title": q, "city": q,
            "symbol": q.split()[0].upper(), "domain": q.split()[0],
            "target": q.split()[0], "text_or_url": q, "key": q,
            "title": q, "url": q, "q": q, "name": q, "tool_name": q,
        })
    for passthrough in ("title", "content", "max_results", "max_chars", "category", "limit", "format",
                          "repo", "filepath", "file_path", "filename", "branch", "path", "caption"):
        if passthrough in primary_args:
            mapped[passthrough] = primary_args[passthrough]
    return mapped


async def execute_registered_tool(
    name: str,
    args: Dict[str, Any],
    caller_id: int = 0,
    is_private_chat: bool = False,
    chat_id: int = 0,
    is_admin: bool = False
) -> Any:
    """
    Execute a registered tool by name with resilient type-coercion, robust argument mapping,
    and structured error handling.
    """
    tool_meta = _find_tool_fuzzy(name)
    if tool_meta is None:
        # Lazy loading: the owner module may simply not be imported yet.
        ensure_tool(name)
        tool_meta = _find_tool_fuzzy(name)
    if not tool_meta:
        logger.warning(f"Tool not found in registry: {name}")
        return f"ابزار {name} یافت نشد."

    func = tool_meta["func"]
    sig: inspect.Signature = tool_meta["signature"]

    call_kwargs: Dict[str, Any] = {}
    args_lower = {k.lower(): v for k, v in (args or {}).items()}
    coerce_error: Optional[str] = None

    for p_name, param in sig.parameters.items():
        if p_name == "caller_id":
            call_kwargs["caller_id"] = caller_id or args.get("caller_id", 0)
        elif p_name == "is_private_chat":
            call_kwargs["is_private_chat"] = is_private_chat
        elif p_name == "chat_id":
            call_kwargs["chat_id"] = chat_id or args.get("chat_id", 0)
        elif p_name == "is_admin":
            call_kwargs["is_admin"] = is_admin or args.get("is_admin", False)
        else:
            raw_val = None
            if p_name in args:
                raw_val = args[p_name]
            elif p_name.lower() in args_lower:
                raw_val = args_lower[p_name.lower()]
            elif len(sig.parameters) == 1 and args:
                raw_val = list(args.values())[0]

            if raw_val is not None:
                p_anno = param.annotation
                try:
                    if p_anno is int:
                        if isinstance(raw_val, bool):
                            call_kwargs[p_name] = int(raw_val)
                        elif isinstance(raw_val, (int, float)):
                            call_kwargs[p_name] = int(raw_val)
                        elif isinstance(raw_val, str):
                            s = raw_val.strip()
                            # Strict: reject mixed junk like "12abc34" instead of silently mangling it.
                            if re.fullmatch(r"-?\d+", s):
                                call_kwargs[p_name] = int(s)
                            else:
                                raise ValueError(f"عدد نامعتبر برای {p_name}: {raw_val!r}")
                        else:
                            call_kwargs[p_name] = int(raw_val)
                    elif p_anno is float:
                        if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
                            call_kwargs[p_name] = float(raw_val)
                        elif isinstance(raw_val, str):
                            s = raw_val.strip()
                            if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
                                call_kwargs[p_name] = float(s)
                            else:
                                raise ValueError(f"عدد نامعتبر برای {p_name}: {raw_val!r}")
                        else:
                            call_kwargs[p_name] = float(raw_val)
                    elif p_anno is bool:
                        if isinstance(raw_val, str):
                            call_kwargs[p_name] = raw_val.lower() in ["true", "1", "yes", "on", "بله", "صحیح"]
                        else:
                            call_kwargs[p_name] = bool(raw_val)
                    elif p_anno is str:
                        call_kwargs[p_name] = str(raw_val).strip()
                    else:
                        call_kwargs[p_name] = raw_val
                except ValueError as ve:
                    # Validation error: fail fast with a clean message instead of
                    # passing garbage into the tool (which raised ugly TypeErrors).
                    coerce_error = f"❌ ورودی نامعتبر برای ابزار `{name}`: {ve}"
                    break
                except Exception:
                    call_kwargs[p_name] = raw_val
            elif param.default is not inspect.Parameter.empty:
                call_kwargs[p_name] = param.default

    if coerce_error:
        return coerce_error

    # --- Idempotent Tool Cache Lookup (<0.01ms) ---
    cache_ttl = _IDEMPOTENT_TOOL_TTLS.get(name)
    cache_key = None
    if cache_ttl is not None:
        try:
            cache_key = f"{name}:{json.dumps(call_kwargs, sort_keys=True, default=str)}"
            now_ts = time.time()
            if cache_key in _IDEMPOTENT_CACHE:
                exp_ts, cached_res = _IDEMPOTENT_CACHE[cache_key]
                if now_ts < exp_ts:
                    return cached_res
        except Exception:
            cache_key = None

    try:
        if tool_meta["is_async"]:
            primary_out = await func(**call_kwargs)
        else:
            primary_out = await asyncio.to_thread(func, **call_kwargs)
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        primary_out = f"خطا در اجرای ابزار {name}: {str(e)}"

    if not _looks_like_failure(primary_out):
        if cache_ttl is not None and cache_key is not None:
            _IDEMPOTENT_CACHE[cache_key] = (time.time() + cache_ttl, primary_out)
            if len(_IDEMPOTENT_CACHE) > 1000:
                _now = time.time()
                for _k in list(_IDEMPOTENT_CACHE.keys())[:200]:
                    if _IDEMPOTENT_CACHE.get(_k, (0, None))[0] <= _now:
                        _IDEMPOTENT_CACHE.pop(_k, None)
        return primary_out

    # --- Automatic resilient fallback: try 1-2 backup tools with mapped args ---
    for fallback_name in TOOL_FALLBACKS.get(name, [])[:2]:
        try:
            fb_meta = REGISTRY.get(fallback_name)
            if fb_meta is None:
                # Fallback target may live in a not-yet-loaded module.
                ensure_tool(fallback_name)
                fb_meta = REGISTRY.get(fallback_name)
            if not fb_meta:
                continue
            fb_kwargs: Dict[str, Any] = {}
            mapped = _map_args_for_fallback(name, dict(call_kwargs), fallback_name)
            for p_name, param in fb_meta["signature"].parameters.items():
                if p_name == "caller_id":
                    fb_kwargs["caller_id"] = caller_id
                elif p_name == "is_private_chat":
                    fb_kwargs["is_private_chat"] = is_private_chat
                elif p_name in mapped:
                    fb_kwargs[p_name] = mapped[p_name]
                elif param.default is not inspect.Parameter.empty:
                    fb_kwargs[p_name] = param.default
            fb_func = fb_meta["func"]
            if fb_meta["is_async"]:
                fb_out = await fb_func(**fb_kwargs)
            else:
                fb_out = fb_func(**fb_kwargs)
            if not _looks_like_failure(fb_out):
                logger.info(f"Tool {name} failed; auto-recovered via fallback {fallback_name}.")
                if isinstance(fb_out, str):
                    return f"🔄 *(بازیابی خودکار از ابزار جایگزین `{fallback_name}`)*\n\n{fb_out}"
                return fb_out
        except Exception as fe:
            logger.debug(f"Fallback {fallback_name} for {name} failed: {fe}")
            continue

    return primary_out
