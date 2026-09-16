import ast
import math
import re
import colorsys
import statistics
import hashlib
import base64
import urllib.parse
import uuid
import json
import logging
from datetime import datetime
import pytz
import jdatetime
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger(__name__)

# ==========================================
# 1. Advanced Math & Expression Evaluator
# ==========================================

SAFE_MATH_ENVIRONMENT = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "lcm": getattr(math, "lcm", lambda *a: 0),
    "comb": math.comb,
    "perm": getattr(math, "perm", lambda n, k: 0),
    "degrees": math.degrees,
    "radians": math.radians,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "erf": math.erf,
    "gamma": math.gamma,
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
    "nan": math.nan
}

_ALLOWED_AST_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call,
    ast.Name, ast.Load, ast.Constant, ast.Add, ast.Sub,
    ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
    ast.FloorDiv
)

_DISALLOWED_AST_NODES = (
    ast.Attribute, ast.Subscript, ast.Lambda, ast.ListComp,
    ast.DictComp, ast.GeneratorExp, ast.Await, ast.Yield
)

@register_tool(
    name="calculate_math_expression",
    description="محاسبه دقیق انواع فرمول‌ها و عبارات پیچیده ریاضی، مثلثاتی، لگاریتمی، آماری و توان",
    category="math"
)
def calculate_math_expression(expression: str) -> str:
    """
    :param expression: عبارت ریاضی برای محاسبه (مثال: sqrt(144) + 2^10 یا sin(pi/6))
    """
    try:
        expr = (expression or "")[:200].strip().replace("^", "**").replace("×", "*").replace("÷", "/")
        if not expr:
            return "عبارت ریاضی خالی است."
        # Guard against nested exponentiation attack (e.g. 9**9**9**9) and giant exponents
        if expr.count("**") > 1 or any(int(part) > 1000 for part in re.findall(r"\*\*(\d+)", expr) if part.isdigit()):
            return "⚠️ توان درخواستی فراتر از سقف مجاز ایمنی محاسباتی است."
        # AST whitelist: only pure math, no Attribute/Subscript/calls outside SAFE env
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            return f"خطا در محاسبه عبارت ریاضی: {e}"
        for node in ast.walk(tree):
            if isinstance(node, _DISALLOWED_AST_NODES):
                return "⛔ عبارت مجاز نیست (دسترسی به اتریبیوت/ایندکس مسدود است)."
            if not isinstance(node, _ALLOWED_AST_NODES):
                # Allow operator nodes already covered; reject everything else
                if isinstance(node, (ast.operator, ast.unaryop)):
                    continue
                if isinstance(node, ast.Expr):
                    continue
                # ast.Module etc not in eval mode; be strict
                if type(node).__name__ in ("Expr", "Module"):
                    continue
                return f"⛔ عبارت مجاز نیست (گره {type(node).__name__} مسدود است)."
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_MATH_ENVIRONMENT:
                    return "⛔ تابع مجاز نیست."
                if len(node.args) > 4 or node.keywords:
                    return "⛔ تعداد آرگومان مجاز نیست."
            if isinstance(node, ast.Name) and node.id not in SAFE_MATH_ENVIRONMENT:
                return f"⛔ نام '{node.id}' مجاز نیست."
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                if abs(float(node.value)) > 1e12:
                    return "⚠️ عدد ورودی بیش از سقف مجاز است."
        # Extra DoS caps for heavy combinatorics
        m = re.search(r"(factorial|comb|perm|gamma)\s*\(\s*(\d+)", expr)
        if m and int(m.group(2)) > 1000:
            return "⚠️ ورودی فاکتوریل/ترکیبیات بیش از سقف ۱۰۰۰ است."
        result = eval(compile(tree, "<math>", "eval"), {"__builtins__": {}}, SAFE_MATH_ENVIRONMENT)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"🧮 *محاسبه ریاضی*:\n• *عبارت*: `{expression}`\n• *حاصل*: *{result:,}*" if isinstance(result, (int, float)) else f"🧮 *حاصل*: `{result}`"
    except Exception as e:
        return f"خطا در محاسبه عبارت ریاضی: {str(e)}"

# ==========================================
# 2. Statistics Calculator
# ==========================================

@register_tool(
    name="statistics_summary",
    description="محاسبه شاخص‌های آماری مجموعه‌ای از اعداد شامل میانگین، میانه، مد، واریانس، انحراف معیار، کمینه و بیشینه",
    category="math"
)
def statistics_summary(numbers: Any) -> str:
    """
    :param numbers: لیست اعداد جداشده با ویرگول یا لیست پایتونی (مثال: 12, 15, 18, 20, 22 یا [12, 15, 20])
    """
    try:
        if isinstance(numbers, (list, tuple)):
            nums = [float(x) for x in numbers]
        else:
            raw = str(numbers).strip().lstrip("[").rstrip("]")
            nums = [float(x.strip()) for x in raw.replace("،", ",").replace(" ", ",").split(",") if x.strip()]
        if not nums:
            return "هیچ عددی وارد نشده است."

        mean_val = statistics.mean(nums)
        median_val = statistics.median(nums)
        try:
            mode_val = statistics.mode(nums)
            mode_txt = f"{mode_val:,.4f}"
        except statistics.StatisticsError:
            mode_txt = "بدون مد یکتا"
        stdev_val = statistics.stdev(nums) if len(nums) > 1 else 0.0
        variance_val = statistics.variance(nums) if len(nums) > 1 else 0.0
        min_val = min(nums)
        max_val = max(nums)
        sum_val = sum(nums)
        sorted_nums = sorted(nums)
        q_txt = ""
        if len(nums) >= 4:
            qs = statistics.quantiles(sorted_nums, n=4)
            q_txt = f"\n• *چارک‌ها (Q1/Q2/Q3)*: `{qs[0]:,.2f}` / `{qs[1]:,.2f}` / `{qs[2]:,.2f}`"

        return (
            f"📊 *تحلیل و شاخص‌های آماری ({len(nums)} عدد)*:\n\n"
            f"• *مجموع*: *{sum_val:,.2f}*\n"
            f"• *میانگین (Mean)*: *{mean_val:,.4f}*\n"
            f"• *میانه (Median)*: *{median_val:,.4f}*\n"
            f"• *مد (Mode)*: *{mode_txt}*\n"
            f"• *انحراف معیار (StDev)*: *{stdev_val:,.4f}*\n"
            f"• *واریانس*: *{variance_val:,.4f}*" + q_txt + f"\n"
            f"• *کمترین (Min)*: `{min_val}` | *بیشترین (Max)*: `{max_val}`"
        )
    except Exception as e:
        return f"خطا در تحلیل آماری: {str(e)}"

# ==========================================
# 3. Cryptographic Hashes & Encoders
# ==========================================

@register_tool(
    name="generate_hash_digest",
    description="تولید انواع کدهای هش رمزنگاری شامل SHA256, SHA512, MD5, SHA1 و Keccak برای هر متن یا کلید",
    category="security"
)
def generate_hash_digest(text: str, algorithm: str = "sha256") -> str:
    """
    :param text: متن ورودی برای هش کردن
    :param algorithm: الگوریتم هش (sha256, sha512, md5, sha1, sha3_256)
    """
    try:
        data = text.encode("utf-8")
        algo = algorithm.lower().strip()
        if algo == "md5":
            h = hashlib.md5(data).hexdigest()
        elif algo == "sha1":
            h = hashlib.sha1(data).hexdigest()
        elif algo == "sha512":
            h = hashlib.sha512(data).hexdigest()
        elif algo == "sha3_256":
            h = hashlib.sha3_256(data).hexdigest()
        else:
            algo = "sha256"
            h = hashlib.sha256(data).hexdigest()

        return (
            f"🔐 *خروجی هش رمزنگاری ({algo.upper()})*:\n\n"
            f"• *متن ورودی*: `{text}`\n"
            f"• *هش هگزادسیمال*:\n`{h}`"
        )
    except Exception as e:
        return f"خطا در تولید هش: {str(e)}"

@register_tool(
    name="base64_encode_decode",
    description="کدگذاری و کدگشایی متن بر مبنای استاندارد Base64",
    category="security"
)
def base64_encode_decode(text: str, mode: str = "encode") -> str:
    """
    :param text: متن ورودی
    :param mode: حالت 'encode' برای کدگذاری یا 'decode' برای کدگشایی
    """
    try:
        if mode.lower() == "decode":
            clean = re.sub(r"\s+", "", text.strip())
            clean += "=" * (-len(clean) % 4)
            decoded = base64.b64decode(clean.encode("utf-8")).decode("utf-8", errors="replace")
            return f"🔓 *متن دیکودشده Base64*:\n\n`{decoded}`"
        else:
            encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
            return f"🔒 *متن اینکودشده Base64*:\n\n`{encoded}`"
    except Exception as e:
        return f"خطا در عملیات Base64: {str(e)}"

@register_tool(
    name="url_encode_decode",
    description="کدگذاری (URL Encode) و کدگشایی (URL Decode) پیوندها و پارامترهای وب",
    category="security"
)
def url_encode_decode(text: str, mode: str = "encode") -> str:
    """
    :param text: متن یا آدرس اینترنتی
    :param mode: حالت 'encode' یا 'decode'
    """
    try:
        if mode.lower() == "decode":
            return f"🌐 *متن رمزگشایی‌شده URL*:\n`{urllib.parse.unquote(text)}`"
        return f"🌐 *متن کدگذاری‌شده URL*:\n`{urllib.parse.quote(text)}`"
    except Exception as e:
        return f"خطا در URL encode/decode: {str(e)}"

@register_tool(
    name="generate_uuid",
    description="تولید شناسه‌های یکتا و تصادفی جهانی بر اساس استاندارد UUID v4",
    category="security"
)
def generate_uuid(count: int = 1) -> str:
    """
    :param count: تعداد شناسه‌های مورد نیاز (۱ تا ۱۰)
    """
    c = max(1, min(10, count))
    uuids = [str(uuid.uuid4()) for _ in range(c)]
    return "🆔 *شناسه‌های اختصاصی UUID v4*:\n\n" + "\n".join(f"• `{u}`" for u in uuids)

# ==========================================
# 4. Engineering Unit Converter
# ==========================================

UNIT_CONVERSIONS = {
    # Temperature
    ("c", "f"): lambda x: (x * 9/5) + 32,
    ("f", "c"): lambda x: (x - 32) * 5/9,
    ("c", "k"): lambda x: x + 273.15,
    ("k", "c"): lambda x: x - 273.15,
    # Length
    ("km", "mi"): lambda x: x * 0.621371,
    ("mi", "km"): lambda x: x / 0.621371,
    ("m", "ft"): lambda x: x * 3.28084,
    ("ft", "m"): lambda x: x / 3.28084,
    ("cm", "in"): lambda x: x / 2.54,
    ("in", "cm"): lambda x: x * 2.54,
    # Weight
    ("kg", "lb"): lambda x: x * 2.20462,
    ("lb", "kg"): lambda x: x / 2.20462,
    ("g", "oz"): lambda x: x / 28.3495,
    ("oz", "g"): lambda x: x * 28.3495,
    # Digital Storage
    ("gb", "mb"): lambda x: x * 1024,
    ("mb", "gb"): lambda x: x / 1024,
    ("tb", "gb"): lambda x: x * 1024,
    ("gb", "tb"): lambda x: x / 1024,
    ("mb", "kb"): lambda x: x * 1024,
    ("kb", "mb"): lambda x: x / 1024,
    ("gb", "kb"): lambda x: x * 1024 * 1024,
    # Time
    ("min", "sec"): lambda x: x * 60,
    ("sec", "min"): lambda x: x / 60,
    ("h", "min"): lambda x: x * 60,
    ("min", "h"): lambda x: x / 60,
    ("h", "sec"): lambda x: x * 3600,
    ("sec", "h"): lambda x: x / 3600,
    ("day", "h"): lambda x: x * 24,
    ("h", "day"): lambda x: x / 24,
    # Speed
    ("kmh", "ms"): lambda x: x / 3.6,
    ("ms", "kmh"): lambda x: x * 3.6,
    ("kmh", "mph"): lambda x: x / 1.60934,
    ("mph", "kmh"): lambda x: x * 1.60934,
}

@register_tool(
    name="convert_units",
    description="تبدیل حرفه‌ای انواع واحدهای مهندسی، دما (سانتی‌گراد، فارنهایت، کلوین)، طول، وزن و حافظه دیجیتال",
    category="scientific"
)
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """
    :param value: مقدار عددی
    :param from_unit: واحد مبدا (مانند c, f, k, km, mi, m, ft, cm, in, kg, lb, gb, mb, tb)
    :param to_unit: واحد مقصد
    """
    _ALIASES = {
        "celsius": "c", "centigrade": "c", "fahrenheit": "f", "kelvin": "k",
        "kilometer": "km", "mile": "mi", "meter": "m", "foot": "ft", "feet": "ft",
        "inch": "in", "centimeter": "cm", "kilogram": "kg", "pound": "lb", "gram": "g",
        "ounce": "oz", "gigabyte": "gb", "megabyte": "mb", "terabyte": "tb", "kilobyte": "kb",
        "minute": "min", "second": "sec", "hour": "h"
    }
    u_from = _ALIASES.get(from_unit.lower().strip(), from_unit.lower().strip())
    u_to = _ALIASES.get(to_unit.lower().strip(), to_unit.lower().strip())

    key = (u_from, u_to)
    if key in UNIT_CONVERSIONS:
        res = UNIT_CONVERSIONS[key](float(value))
        return f"📏 *تبدیل واحد مهندسی*:\n• *مقدار اولیه*: `{value}` {u_from.upper()}\n• *مقدار معادل*: *{res:,.4f}* {u_to.upper()}"
    return f"تبدیل از {from_unit} به {to_unit} پشتیبانی نمی‌شود."

# ==========================================
# 5. Official Date & Time Engine
# ==========================================

@register_tool(
    name="get_current_datetime_info",
    description="استعلام زمان رسمی، تقویم دقیق شمسی، میلادی، قمری، منطقه زمانی و روزهای باقی‌مانده سال",
    category="time"
)
def get_current_datetime_info(timezone: str = "Asia/Tehran") -> str:
    """
    :param timezone: منطقه زمانی (پیش‌فرض: Asia/Tehran)
    """
    try:
        tz = pytz.timezone(timezone)
    except Exception:
        tz = pytz.timezone("Asia/Tehran")

    now = datetime.now(tz)
    j_now = jdatetime.datetime.fromgregorian(datetime=now)

    persian_weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یک‌شنبه"]
    weekday_fa = persian_weekdays[now.weekday()]

    return (
        f"⏰ *تقویم و زمان رسمی ({timezone})*:\n\n"
        f"• *ساعت دقیق*: *{now.strftime('%H:%M:%S')}*\n"
        f"• *روز*: *{weekday_fa}*\n"
        f"• *تاریخ هجری شمسی*: *{j_now.strftime('%Y/%m/%d')}* ({j_now.strftime('%d %B %Y')})\n"
        f"• *تاریخ میلادی (Gregorian)*: *{now.strftime('%Y-%m-%d')}*\n"
        f"• *منطقه زمانی*: `{timezone}` ({now.strftime('%z')})"
    )

# ==========================================
# 6. JSON Formatter & Validator
# ==========================================

@register_tool(
    name="json_formatter_validator",
    description="اعتبارسنجی ساختار JSON، زیباسازی و مرتب‌سازی داده‌های ساختاریافته",
    category="scientific"
)
def json_formatter_validator(json_text: str) -> str:
    """
    :param json_text: متن حاوی ساختار JSON
    """
    try:
        parsed = json.loads(json_text)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        return f"📋 *ساختار معتبر JSON (فرمت‌شده)*:\n\n```json\n{pretty}\n```"
    except Exception as e:
        return f"❌ ساختار JSON نامعتبر است: {str(e)}"

# ==========================================
# 7. Color Converter & Palette Inspector
# ==========================================

@register_tool(
    name="color_converter_tool",
    description="تبدیل کدهای رنگ بین استانداردهای HEX, RGB, HSL و محاسبه رنگ مکمل",
    category="scientific"
)
def color_converter_tool(color_code: str) -> str:
    """
    :param color_code: کد رنگ به صورت HEX (مانند #FF5733) یا RGB (مانند rgb(255, 87, 51))
    """
    c = color_code.strip()
    try:
        if c.startswith("#"):
            hex_str = c.lstrip("#")
            if len(hex_str) == 3:
                hex_str = "".join(x*2 for x in hex_str)
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
        elif "rgb" in c.lower():
            nums = [int(x.strip()) for x in c.lower().replace("rgb", "").replace("(", "").replace(")", "").split(",")][:3]
            r, g, b = nums[0], nums[1], nums[2]
            hex_str = f"{r:02x}{g:02x}{b:02x}"
        else:
            return "فرمت رنگ نامعتبر است. از کدهای HEX مانند #3498DB استفاده کنید."

        # Complementary color + HSL
        comp_r, comp_g, comp_b = 255 - r, 255 - g, 255 - b
        comp_hex = f"#{comp_r:02X}{comp_g:02X}{comp_b:02X}"
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)

        return (
            f"🎨 *مشخصات و تبدیل کد رنگ*:\n\n"
            f"• *کد هگز (HEX)*: `#{hex_str.upper()}`\n"
            f"• *کد RGB*: `rgb({r}, {g}, {b})`\n"
            f"• *کد HSL*: `hsl({h * 360:.0f}, {s * 100:.0f}%, {l * 100:.0f}%)*\n"
            f"• *رنگ مکمل (Complementary)*: `{comp_hex}`"
        )
    except Exception as e:
        return f"خطا در پردازش رنگ: {str(e)}"
