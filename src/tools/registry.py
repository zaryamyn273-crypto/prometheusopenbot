import inspect
import functools
import importlib
import logging
import re
import threading
from typing import Callable, Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Global registry of all executable tools
REGISTRY: Dict[str, Dict[str, Any]] = {}

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
    "network": ["src.tools.web_network"],
    "media": ["src.tools.media"],
    "security": ["src.tools.scientific"],
    "scientific": ["src.tools.scientific"],
    "math": ["src.tools.scientific"],
    "time": ["src.tools.scientific"],
    "github": ["src.tools.github"],
    "admin": ["src.tools.system", "src.tools.admin.group_manager", "src.tools.database"],
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
    for path in _MODULE_PATHS:
        with _LOAD_LOCK:
            if path in _LOADED_MODULES:
                continue
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

CATEGORY_KEYWORDS = {
    "financial": [
        "دلار", "تتر", "بیتکوین", "بیت کوین", "ارز", "طلا", "سکه", "یورو", "پوند", "درهم", "لیر",
        "کریپتو", "اتریوم", "forex", "crypto", "btc", "eth", "usdt", "nobitex", "binance", "سرمایه", "نرخ طلا", "نرخ ارز", "صرافی"
    ],
    "crypto": [
        "بیتکوین", "بیت کوین", "کریپتو", "اتریوم", "btc", "eth", "usdt", "nobitex", "binance", "رمزارز", "تون", "داج", "سولانا"
    ],
    "weather": [
        "هوا", "آب و هوا", "دما", "باران", "برف", "ابری", "weather", "forecast", "پیش بینی", "درجه"
    ],
    "search": [
        "سرچ", "جستجو", "گوگل", "خبر", "اخبار", "search", "news", "پیدا کن", "مقاله", "تحقیق",
        "دیجیکالا", "دیجی کالا", "دیجی", "digikala", "خرید", "کالا", "اجناس", "گوشی", "موبایل", "لپتاپ", "لپ تاپ",
        "توییتر", "توییت", "twitter", "tweet", "اکس", "x.com", "توییت ها", "هشتگ", "پست های توییتر",
        "tavily", "تاویلی", "وب", "اینترنت", "اطلاعات روز", "تازه‌ترین", "تازه ترین", "جدیدترین"
    ],
    "network": [
        "ip", "dns", "ssl", "whois", "ping", "دامنه", "هاست", "پورت", "سایت", "لینک", "اینترنت", "وب"
    ],
    "media": [
        "آهنگ", "اهنگ", "موزیک", "ترانه", "خواننده", "دانلود", "ویس", "صدا", "وویس", "تلگراف", "telegraph",
        "بارکد", "qr", "lyrics", "متن شعر", "شعر", "صوت", "پادکست", "مقاله", "کیوآر", "متن آهنگ",
        "لیریکس", "تایم دار", "lrc", "synced lyrics", "متن ترانه"
    ],
    "security": [
        "امنیت", "هش", "hash", "رمزنگاری", "base64", "uuid",
        "شناسه یکتا", "یو یو آی دی", "انکد", "دیکد", "url encode"
    ],
    "scientific": [
        "آمار", "میانگین", "انحراف معیار", "تبدیل واحد", "متر", "کیلو", "فارنهایت", "رنگ", "rgb", "hex",
        "کیلومتر", "مایل", "سانتی", "کلوین", "json", "جی سان", "واحد", "پالت", "مکمل"
    ],
    "github": [
        "گیت هاب", "github", "ریپازیتوری", "مخزن", "repo", "سورس", "کدباز", "اوپن سورس",
        "کامیت", "commit", "ایسیو", "issue", "ریلیز", "release", "نسخه", "ترند", "trending",
        "پروفایل", "کاربر گیت", "مشارکت", "contributor", "ستاره", "فورک", "نمونه کد"
    ],
    "admin": [
        "بن", "آنبن", "مسدود", "لیست سیاه", "قانون ابدی", "دستور دائمی", "حافظه دائمی", "وضعیت سرور", "تله متری", "لینک گروه", "لینک گروه‌ها", "لینک گروهها", "سکوت", "میوت", "لغو سکوت", "رفع سکوت", "آنمیوت", "لیست سکوت", "mutelist",
        "رم", "cpu", "گروه", "گروه‌ها", "گروهها", "گروهم", "گروهام", "گروه هام", "گروه های من", "گروه های فعال", "لیست گروه", "لیست گروه‌ها", "لیست گروهها", "لفت", "خروج از گروه", "bangroup", "groups", "my groups", "list groups", "show groups", "group list",
        "کانال", "کانال‌ها", "کانالها", "کانال های من", "channels", "public channels", "چت ها", "چت‌ها", "chats",
        "سرور", "سرورت", "هست", "حال", "سیستم", "سخت افزار", "حافظه", "آیدی", "شناسه", "user id", "userid", "getid",
    ],
    "files": [
        "فایل", "پی دی اف", "پی‌دی‌اف", "pdf", "اکسل", "excel", "xlsx", "word", "ورد", "docx", "csv", "json", "کد پایتون",
        "دانلود فایل", "بساز برام", "ساخت فایل", "فایل متنی", "txt", "داکیومنت", "سند", "پی دی اف ساز"
    ],
    "math": [
        "حساب", "ریاضی", "محاسبه", "فرمول", "ضرب", "تقسیم", "جمع", "منها", "توان", "جذر", "درصد",
        "فاکتوریل", "لگاریتم", "سینوس", "کسینوس", "میانگین", "آمار", "factorial"
    ],
    "time": [
        "ساعت", "تاریخ", "تقویم", "امروز چندمه", "ساعت چنده", "time", "date"
    ],
    "database": [
        "سوابق", "پیام های قبلی", "تاریخچه", "قبلا", "دیروز", "چت", "دیتابیس", "ذخیره در دیتابیس", "کانفیگ",
        "یادداشت", "داده", "d1", "kv", "کلودفلر", "ذخیره رکورد", "بازیابی رکورد", "حذف رکورد", "لیست رکوردها"
    ],
    "dev": [
        "اجرای کد", "پایتون", "کد پایتون", "برنامه", "اسکریپت", "run python",
        "ردیت", "reddit", "استک", "استک اورفلو", "stackoverflow", "باگ", "ارور", "error", "bug",
        "exception", "ایشو", "issue", "کدنویسی", "برنامه نویسی", "توسعه دهنده", "حل مشکل", "سایت تخصصی",
        "stack", "مخزن", "repo", "کامپایل", "دیباگ", "debug", "crash", "کرش",
        "e2b", "سندباکس ابری", "سندباکس", "sandbox", "کلاد", "کد ابری",
        "جاوااسکریپت", "javascript", "pip install", "نصب پکیج",
    ],
    "github_legacy_placeholder": []
}

_SMART_FILTER_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_SMART_FILTER_ORDER: List[str] = []

_COMPILED_SHORT_KW: Dict[str, Any] = {}


def _kw_hit_compiled(kw: str, prompt_lower: str) -> bool:
    if re.match(r"^[a-z]{1,4}$", kw):
        pat = _COMPILED_SHORT_KW.get(kw)
        if pat is None:
            pat = re.compile(rf"(?<![a-z]){re.escape(kw)}(?![a-z])")
            _COMPILED_SHORT_KW[kw] = pat
        return pat.search(prompt_lower) is not None
    return kw in prompt_lower


def get_smart_tools_for_prompt(prompt: str, is_admin: bool = False) -> List[Dict[str, Any]]:
    """
    Intelligently selects the most relevant tool schemas based on prompt intent.
    Always includes universally useful tools while filtering out unrelated heavy categories.
    When is_admin is False, admin-only categories/tools are strictly excluded from the schema.
    Results are memoized (500-entry FIFO) so repeated intents cost ~0ms.
    """
    cache_key = f"{'adm:' if is_admin else 'usr:'}{(prompt or '')[:160].lower().strip()}"
    cached = _SMART_FILTER_CACHE.get(cache_key)
    if cached is not None:
        return cached
    prompt_lower = (prompt or "").lower()

    def _kw_hit(kw: str) -> bool:
        # Short Latin tokens (ip, dns, ssl, qr, ...) need word boundaries,
        # otherwise 'github' would trigger 'ip' and 'crypto' would trigger 'qr'.
        return _kw_hit_compiled(kw, prompt_lower)

    # Identify relevant categories (internal tools are system-only, never matched)
    relevant_categories = set()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if cat == "internal":
            continue
        for kw in kws:
            if _kw_hit_compiled(kw, prompt_lower):
                relevant_categories.add(cat)
                break
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
        "؟", "?", "کیه", "چیه", "کجاست", "کجاست؟", "چرا", "چطور", "چگونه",
        "کجا", "کی", "آیا", "کدوم", "کدام", "چند", "چه", "who", "what",
        "when", "where", "why", "how", "which", "is ", "are ",
    ]
    _looks_question = any(_qm in prompt_lower for _qm in _question_markers)
    if _looks_question and "search" not in relevant_categories:
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
        "media": ["بذار", "پخش", "بفرست", "بده", "پلی", "play", "پخش کن"],
        "financial": ["بخرم", "بفروشم", "سرمایه", "سود", "گرون", "ارزون", "تحلیل بازار"],
        "search": ["جدیدترین", "آخرین", "تازه", "خبر", "اطلاعات", "درباره", "کیه", "چیه"],
        "files": ["بساز", "درست کن", "آماده کن", "اکسل", "جدول", "لیست", "گزارش"],
        "admin": ["چطوره", "خوبه", "سالمه", "وضعیت"],
        "time": ["امروز", "فردا", "دیروز", "الان", "فعلا", "کی"],
        "database": ["یادداشت", "یادم", "ذخیره", "بنویس", "ثبت"],
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
                    "media": ["آهنگ", "موزیک", "ترانه", "خواننده", "شعر", "صدا", "ویس", "صوت", "شاد", "غمگین", "پادکست", "مقاله", "تلگراف", "qr", "کیوآر", "بارکد", "hello", "song", "music", "audio", "mp3"],
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
    }
    for cat in list(relevant_categories):
        relevant_categories.update(_coactivate.get(cat, set()))

    # --- Multi-request bundle: several intents at once -> send the full set ---
    _intent_hits = len(relevant_categories - {"time"})
    _complex = _intent_hits >= 4 or len(prompt_lower) > 200

    # Core bundle that are fast & frequently used (live in scientific).
    core_names = {
        "get_current_datetime_info", "calculate_math_expression"
    }
    # The schemas below are read from REGISTRY, so their owner modules must be
    # loaded first — but ONLY those modules (this is what keeps lazy loading lazy).
    # scientific is near-free (stdlib + pytz/jdatetime, already pulled by database).
    ensure_categories(relevant_categories)
    ensure_category("scientific")

    # Pure casual conversation / greeting detector: zero tool overhead = ultra fast sub-second turn
    pure_conversational = [
        "سلام", "درود", "خوبی", "چطوری", "چه خبر", "خسته نباشی", "ممنون", "مرسی",
        "تشکر", "دمت گرم", "فدات", "قربانت", "سلامت باشی", "صبح بخیر", "شب بخیر",
        "hi", "hello", "hey", "thanks", "thank you"
    ]
    is_pure_chat = any(w in prompt_lower for w in pure_conversational) and len(prompt_lower) < 60

    # If no specific category matched:
    if not relevant_categories:
        if is_pure_chat:
            _SMART_FILTER_CACHE[cache_key] = []
            return []  # No tools needed for pure greetings/chat: instant response!
        # For generic questions, provide only web_search & clock without clutter
        ensure_categories({"search"})  # web_search/tavily live here
        core_names.update({"tavily_search", "web_search", "get_current_datetime_info"})
        out = [t["schema"] for name, t in REGISTRY.items() if name in core_names]
        _SMART_FILTER_CACHE[cache_key] = out
        return out

    if _complex:
        # Complex prompt: give the model the whole cabinet, it decides.
        ensure_all()
        out = [t["schema"] for t in REGISTRY.values() if t.get("category") != "internal" and (is_admin or t.get("category") != "admin")]
        _SMART_FILTER_CACHE[cache_key] = out
        return out

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

    for name, t in REGISTRY.items():
        cat = t.get("category", "")
        if cat == "internal":
            continue
        if cat == "admin" and not is_admin:
            continue
        if exclude_extract_id and name == "extract_user_id_tool":
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

    _SMART_FILTER_CACHE[cache_key] = selected_schemas
    _SMART_FILTER_ORDER.append(cache_key)
    if len(_SMART_FILTER_ORDER) > 500:
        oldest = _SMART_FILTER_ORDER.pop(0)
        _SMART_FILTER_CACHE.pop(oldest, None)
    return selected_schemas

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
    "digikala_search": ["web_search", "bot_fallback_search"],
    "download_music_track": ["get_song_lyrics", "bot_music_fallback"],
    "get_song_lyrics": ["bot_lyrics_fallback", "bot_fallback_search"],
    "transcribe_audio_tool": ["bot_fallback_search"],
    "check_website_status": ["quick_http_inspect_tool", "resolve_dns"],
    "resolve_dns": ["get_ip_info", "quick_http_inspect_tool"],
    "get_ip_info": ["resolve_dns", "quick_http_inspect_tool"],
    "check_ssl_certificate": ["check_website_status", "quick_http_inspect_tool"],
    "publish_telegraph_article": ["create_and_upload_file", "bot_file_fallback_publish"],
    "create_and_upload_file": ["publish_telegraph_article", "bot_file_fallback_publish"],
    "generate_qr_code_tool": ["bot_qr_fallback"],
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
    is_private_chat: bool = False
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
            call_kwargs["caller_id"] = caller_id
        elif p_name == "is_private_chat":
            call_kwargs["is_private_chat"] = is_private_chat
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

    try:
        if tool_meta["is_async"]:
            primary_out = await func(**call_kwargs)
        else:
            primary_out = func(**call_kwargs)
    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        primary_out = f"خطا در اجرای ابزار {name}: {str(e)}"

    if not _looks_like_failure(primary_out):
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
