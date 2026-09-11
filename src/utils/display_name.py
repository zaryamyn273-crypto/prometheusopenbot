"""Fast username -> Persian display-name resolver.

Rules (all local, zero network, sub-millisecond):
- Strip digits, underscores and separators from the @username.
- Match the remaining latin core against a Persian-name dictionary
  (transliterations + common shortenings: parham, mmd/reza, alex, ...).
- If the core is shorter than 3 letters, has no vowel, is a random-looking
  string (high consonant run, no known token), or matches nothing:
  return '' so the bot addresses nobody by name instead of guessing wrong.
"""
import re
from functools import lru_cache

_LATIN_TO_FA = {
    # --- Common Persian names ---
    "parham": "پرهام", "arham": "پرهام", "arman": "آرمان", "aria": "آریا",
    "aryan": "آرین", "arin": "آرین", "artin": "آرتین", "radin": "رادین",
    "sam": "سام", "saman": "سامان", "sami": "سامی", "sorena": "سورنا",
    "soheil": "سهیل", "soheyl": "سهیل", "koroush": "کوروش", "kourosh": "کوروش",
    "dariush": "داریوش", "daria": "دریا", "dorsa": "درسا",
    "sara": "سارا", "sarah": "سارا", "sarina": "سارینا", "sarin": "سارین",
    "sahar": "سحر", "saba": "صبا", "sette": "ستاره", "setareh": "ستاره",
    "mahsa": "مهسا", "mahla": "مهلا", "melina": "ملینا", "melika": "ملیکا",
    "mitra": "میترا", "mina": "مینا", "maryam": "مریم", "maria": "ماریا",
    "mohammad": "محمد", "mohamad": "محمد", "mmd": "محمد", "mamad": "محمد",
    "mehdi": "مهدی", "mahdi": "مهدی", "mehrab": "مهراب", "mehran": "مهران",
    "mehrad": "مهراد", "milad": "میلاد", "mojtaba": "مجتبی",
    "ali": "علی", "alireza": "علیرضا", "amir": "امیر", "amirali": "امیرعلی",
    "amirreza": "امیررضا", "amirsam": "امیرسام", "hossein": "حسین",
    "hosein": "حسین", "hassan": "حسن", "hasan": "حسن", "reza": "رضا",
    "hamed": "حامد", "hamid": "حمید", "hadi": "هادی", "hessam": "حسام",
    "hesam": "حسام", "farhad": "فرهاد", "farzad": "فرزاد", "faraz": "فراز",
    "farbod": "فربد", "behnam": "بهنام", "behzad": "بهزاد", "babak": "بابک",
    "borna": "برنا", "bardia": "بردیا", "pedram": "پدرام", "pejman": "پژمان",
    "payam": "پیام", "pouya": "پویا", "pouria": "پوریا", "kimia": "کیمیا",
    "kian": "کیان", "kiana": "کیانا", "kosar": "کوثر", "kajal": "کژال",
    "nima": "نیما", "navid": "نوید", "nasrin": "نسرین", "narges": "نرگس",
    "negin": "نگین", "negar": "نگار", "niloofar": "نیلوفر", "niloufar": "نیلوفر",
    "taraneh": "ترانه", "tara": "تارا", "tina": "تینا", "taha": "طاها",
    "yasaman": "یاسمن", "yasin": "یاسین", "yasi": "یاسی", "yalda": "یلدا",
    "zahra": "زهرا", "zeynab": "زینب", "zeinab": "زینب", "ayda": "آیدا",
    "anahita": "آناهیتا", "atena": "آتنا", "ava": "آوا", "baran": "باران",
    "bahar": "بهار", "bahram": "بهرام", "shayan": "شایان", "shahin": "شاهین",
    "shervin": "شروین", "shaqayeq": "شقایق", "shaghayegh": "شقایق",
    "erfan": "عرفان", "elnaz": "الناز", "elham": "الهام", "donya": "دنیا",
    "roya": "رویا", "roxana": "رکسانا", "raha": "رها", "ramin": "رامین",
    "sina": "سینا", "sepehr": "سپهر", "siavash": "سیاوش", "omid": "امید",
    "fatemeh": "فاطمه", "fateme": "فاطمه", "atefeh": "عاطفه",
    "ghazal": "غزل", "goli": "گلی", "golnar": "گلنار", "laleh": "لاله",
    "leila": "لیلا", "leyla": "لیلا", "maral": "مارال",
    "mani": "مانی", "masoud": "مسعود", "masood": "مسعود", "majid": "مجید",
    "morteza": "مرتضی", "mostafa": "مصطفی", "naser": "ناصر", "nader": "نادر",
    "ehsan": "احسان", "iman": "ایمان", "kazem": "کاظم",
    "karim": "کریم", "kamran": "کامران", "kaveh": "کاوه", "keyvan": "کیوان",
    "lashkar": "لشکر", "mahan": "ماهان", "mahyar": "مهیار", "mobin": "مبین",
    "nikan": "نیکان", "parsa": "پارسا", "radman": "رادمان",
    "rouzbeh": "روزبه", "saeed": "سعید", "said": "سعید", "saleh": "صالح",
    "sajad": "سجاد", "sajjad": "سجاد", "vahid": "وحید", "yousef": "یوسف",
    "yousof": "یوسف", "ziba": "زیبا",
    # --- Common international names ---
    "alex": "الکس", "alexander": "الکساندر", "mike": "مایک", "michael": "مایکل",
    "david": "دیوید", "daniel": "دنیل", "john": "جان", "james": "جیمز",
    "emma": "اما", "olivia": "اولیویا", "sophia": "سوفیا", "anna": "آنا",
    "max": "مکس", "leo": "لئو", "nina": "نینا", "lisa": "لیزا",
    "chris": "کریس", "tom": "تام", "jack": "جک", "lucas": "لوکاس",
    "mia": "میا", "zoe": "زوئی", "lena": "لنا", "julia": "جولیا",
}

_VOWELS = set("aeiouy")

_NOISE_TOKENS = {
    "official", "real", "iran", "tehran", "persian", "farsi", "girl", "boy",
    "love", "king", "queen", "dark", "light", "night", "day", "star",
    "gaming", "gamer", "music", "art", "photo", "pic", "shop", "store",
    "bot", "channel", "group", "admin", "test", "new", "old", "best",
    "top", "pro", "vip", "hd", "tv", "fm", "online", "ir",
}


@lru_cache(maxsize=2048)
def username_to_persian_name(username: str) -> str:
    """Returns a Persian first name for a meaningful username, else ''."""
    raw = (username or "").strip().lstrip("@").lower()
    if not raw:
        return ""
    # Split camelCase and separators into tokens
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", (username or "").strip().lstrip("@"))
    tokens = [t.lower() for t in re.split(r"[^a-zA-Z]+", spaced) if t]
    if not tokens:
        return ""
    # Any token can carry the name (Parham_Official -> parham)
    for tok in sorted(tokens, key=len, reverse=True):
        if len(tok) >= 3 and tok in _LATIN_TO_FA:
            return _LATIN_TO_FA[tok]
    core = max(tokens, key=len)
    if len(core) < 3:
        return ""
    # Strip common trailing noise then retry
    for noise in ("official", "real", "irani", "persian", "farsi"):
        if core.endswith(noise) and len(core) - len(noise) >= 3:
            trimmed = core[: -len(noise)]
            if trimmed in _LATIN_TO_FA:
                return _LATIN_TO_FA[trimmed]
    # Prefix hit for shortened handles (parham271 -> parham)
    for known, fa in _LATIN_TO_FA.items():
        if len(known) >= 4 and core.startswith(known) and len(core) - len(known) <= 4:
            rest = core[len(known):]
            if not rest or rest.isdigit():
                return fa
    # Gibberish guard: no vowel, heavy consonant run, or pure noise
    if core in _NOISE_TOKENS:
        return ""
    if not any(c in _VOWELS for c in core):
        return ""
    if re.search(r"[^aeiouy]{5,}", core):
        return ""
    if re.search(r"(.)\1{3,}", core):
        return ""
    return ""
