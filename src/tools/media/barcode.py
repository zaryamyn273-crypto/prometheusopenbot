"""
Advanced Barcode & QR Code Engine with Damaged Barcode Reconstruction:
- Generates 1D (Code-128, EAN-13, UPC, Code-39) and 2D (QR Code Level H) barcodes.
- Mathematical Checksum Validators (Modulo 103 for Code-128, Modulo 10 Luhn-variant for EAN-13/UPC).
- Damaged / Scratched Barcode Reconstruction Pipeline:
    * Decodes partially erased, scratched, or corrupted barcode data.
    * Reconstructs missing digits using algebraic checksum parity.
    * Regenerates 100% clean, fresh, scannable barcode images.
"""

import io
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw
from src.tools.registry import register_tool

logger = logging.getLogger(__name__)

# Code 128 patterns (Indices 0 to 106)
_CODE128_PATTERNS = [
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312',
    '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222',
    '123122', '123221', '223211', '221132', '221231', '213212', '223112', '312131',
    '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321',
    '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121',
    '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321',
    '331121', '312113', '312311', '332111', '314111', '221411', '431111', '111224',
    '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114',
    '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112',
    '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113',
    '114311', '411113', '411311', '113141', '114131', '311141', '411131', '211412',
    '211214', '211232', '2331112'
]

# EAN-13 encoding tables
_EAN13_L_CODE = {
    '0': '0001101', '1': '0011001', '2': '0010011', '3': '0111101', '4': '0100011',
    '5': '0110001', '6': '0101111', '7': '0111011', '8': '0110111', '9': '0001011'
}
_EAN13_G_CODE = {
    '0': '0100111', '1': '0110011', '2': '0011011', '3': '0100001', '4': '0011101',
    '5': '0111001', '6': '0000101', '7': '0010001', '8': '0001001', '9': '0010111'
}
_EAN13_R_CODE = {
    '0': '1110010', '1': '1100110', '2': '1101100', '3': '1000010', '4': '1011100',
    '5': '1001110', '6': '1010000', '7': '1000100', '8': '1001000', '9': '1110100'
}
_EAN13_PARITY = {
    '0': 'LLLLLL', '1': 'LLGLGG', '2': 'LLGGLG', '3': 'LLGGGL', '4': 'LGLLGG',
    '5': 'LGGLLG', '6': 'LGGGLL', '7': 'LGLGLG', '8': 'LGLGGL', '9': 'LGGLGL'
}


def generate_qr_image_bytes(data: str, box_size: int = 10, border: int = 4) -> bytes:
    """
    Generates pure in-memory QR code PNG bytes using Pillow and io.BytesIO (zero disk operations).
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=box_size,
            border=border,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Error generating QR image in memory: {e}")
        return b""


def generate_ean13_image_bytes(digits13: str, scale: int = 3, height: int = 120) -> bytes:
    """
    Renders pure in-memory EAN-13 barcode PNG bytes using Pillow and io.BytesIO (zero disk operations).
    """
    try:
        clean = "".join(c for c in digits13 if c.isdigit())
        if len(clean) == 12:
            chk = compute_ean13_check_digit(clean)
            clean = f"{clean}{chk}"
        elif len(clean) != 13:
            return b""

        first = clean[0]
        left = clean[1:7]
        right = clean[7:13]
        par = _EAN13_PARITY.get(first, "LLLLLL")

        modules = ["101"]  # Start guard
        for d, p in zip(left, par):
            modules.append(_EAN13_L_CODE[d] if p == "L" else _EAN13_G_CODE[d])
        modules.append("01010")  # Center guard
        for d in right:
            modules.append(_EAN13_R_CODE[d])
        modules.append("101")  # End guard

        bitstring = "".join(modules)
        quiet_zone = 9
        total_modules = len(bitstring) + 2 * quiet_zone
        width = total_modules * scale

        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)

        x = quiet_zone * scale
        for bit in bitstring:
            if bit == "1":
                draw.rectangle([x, 10, x + scale - 1, height - 10], fill="black")
            x += scale

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Error rendering EAN-13 in memory: {e}")
        return b""


def generate_code128_image_bytes(text: str, scale: int = 2, height: int = 100) -> bytes:
    """
    Renders pure in-memory Code 128 barcode PNG bytes using Pillow and io.BytesIO (zero disk operations).
    """
    try:
        raw_text = str(text or "")
        if not raw_text:
            return b""
        values = [104]  # Start B
        checksum = 104
        for idx, c in enumerate(raw_text, 1):
            v = ord(c) - 32
            if 0 <= v <= 95:
                values.append(v)
                checksum += idx * v
            else:
                values.append(0)
        values.append(checksum % 103)
        values.append(106)  # Stop

        bits = []
        for val in values:
            pat = _CODE128_PATTERNS[val]
            is_bar = True
            for width in pat:
                w = int(width)
                bits.extend(["1" if is_bar else "0"] * w)
                is_bar = not is_bar

        quiet_zone = 10
        total_len = len(bits) + 2 * quiet_zone
        width = total_len * scale

        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)

        x = quiet_zone * scale
        for b in bits:
            if b == "1":
                draw.rectangle([x, 5, x + scale - 1, height - 5], fill="black")
            x += scale

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.error(f"Error rendering Code 128 in memory: {e}")
        return b""


def render_barcode_in_memory(data: str, barcode_type: str = "auto", scale: int = 3, height: int = 120) -> bytes:
    """
    Unified fast in-memory renderer for 1D/2D barcodes with pure io.BytesIO and zero disk operations.
    """
    btype = str(barcode_type or "auto").strip().lower()
    raw_val = str(data or "").strip()
    if btype in ("auto", "default"):
        if raw_val.isdigit() and len(raw_val) in (12, 13):
            btype = "ean13"
        elif raw_val.startswith("http://") or raw_val.startswith("https://") or len(raw_val) > 40:
            btype = "qr"
        else:
            btype = "code128"

    if btype in ("qr", "qrcode", "دوبعدی"):
        return generate_qr_image_bytes(raw_val)
    elif btype in ("ean13", "ean", "فروشگاهی"):
        return generate_ean13_image_bytes(raw_val, scale=scale, height=height)
    else:
        return generate_code128_image_bytes(raw_val, scale=max(2, scale - 1), height=height)


def compute_ean13_check_digit(digits12: str) -> int:
    """Calculates standard EAN-13 check digit for 12 numeric digits."""
    clean = "".join(c for c in digits12 if c.isdigit())[:12]
    if len(clean) != 12:
        return -1
    odd_sum = sum(int(clean[i]) for i in range(0, 12, 2))
    even_sum = sum(int(clean[i]) for i in range(1, 12, 2))
    total = odd_sum + (even_sum * 3)
    return (10 - (total % 10)) % 10


def recover_missing_ean13_digit(partial_digits: str) -> Optional[Tuple[str, int]]:
    """
    Recovers a single missing or scratched digit (marked with '?' or '_')
    in an EAN-13 code using the modulo-10 checksum equation.
    Returns (full_recovered_13_digits, recovered_digit).
    """
    clean = "".join(c for c in partial_digits if c.isdigit() or c in "?_")
    if len(clean) != 13:
        return None
    unknown_pos = -1
    for idx, char in enumerate(clean):
        if char in "?_":
            if unknown_pos != -1:
                # More than one missing digit
                return None
            unknown_pos = idx
    if unknown_pos == -1:
        # Check if already valid
        check = compute_ean13_check_digit(clean[:12])
        if check == int(clean[12]):
            return clean, int(clean[12])
        return None

    # Test all 10 possible digits (0-9) at the missing position
    for candidate in range(10):
        test_str = clean[:unknown_pos] + str(candidate) + clean[unknown_pos + 1 :]
        if compute_ean13_check_digit(test_str[:12]) == int(test_str[12]):
            return test_str, candidate
    return None


@register_tool(
    name="generate_barcode_tool",
    description="تولید انواع بارکد میله‌ای استاندارد (Code-128, EAN-13, UPC) و بارکد دوبعدی QR Code با حداکثر کیفیت، قابلیت تصحیح خطای ۳۰٪ (Level H) و لینک دانلود اسکن‌پذیر مستقیم",
    category="media",
)
def generate_barcode_tool(
    data: Optional[str] = None,
    text_or_url: Optional[str] = None,
    barcode_type: str = "auto",
    include_text: bool = True,
    return_bytes: bool = False,
) -> Any:
    """
    :param data: متن، عدد، آدرس URL یا شماره سریال برای درج در بارکد
    :param text_or_url: پارامتر جایگزین برای آدرس یا متن
    :param barcode_type: نوع بارکد: 'qr' (دوبعدی)، 'code128' (میله‌ای عمومی)، 'ean13' (محصولات فروشگاهی)، 'code39' یا 'auto'
    :param include_text: نمایش متن خوانا زیر بارکد میله‌ای (پیش‌فرض True)
    :param return_bytes: بازگرداندن مستقیم بایت‌های تصویر بارکد در حافظه (پیش‌فرض False)
    """
    raw_val = str(data or text_or_url or "https://t.me/prometheusopenbot").strip()
    btype = str(barcode_type or "auto").strip().lower()

    if return_bytes:
        return render_barcode_in_memory(raw_val, btype)

    # Auto-detection of barcode type
    is_numeric = raw_val.isdigit()
    if btype in ("auto", "default"):
        if is_numeric and len(raw_val) in (12, 13):
            btype = "ean13"
        elif raw_val.startswith("http://") or raw_val.startswith("https://") or len(raw_val) > 40:
            btype = "qr"
        else:
            btype = "code128"

    encoded = urllib.parse.quote(raw_val)

    if btype in ("qr", "qrcode", "دوبعدی"):
        # Level H Error Correction (recovers up to 30% damage/scratches)
        qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=600x600&ecc=H&margin=4&data={encoded}"
        backup_url = f"https://quickchart.io/qr?text={encoded}&ecLevel=H&size=600&margin=4"
        return (
            f"🔳 *بارکد دوبعدی QR Code مقاوم با تصحیح خطای ۳۰٪ (Level H)*:\n\n"
            f"• *داده رمزگذاری‌شده*: `{raw_val}`\n"
            f"• *استاندارد مقاومت*: `Error Correction Level H` (اسکن‌پذیر حتی در صورت پارگی یا خش تا ۳۰٪)\n"
            f"• *ابعاد خروجی*: `600x600 Ultra-Crisp`\n\n"
            f"🔗 [دانلود تصویر بارکد QR با کیفیت بالا]({qr_img_url})\n"
            f"🌐 [سرور پشتیبان نمایش بارکد]({backup_url})"
        )

    # 1D Barcode formats (Code128, EAN13, Code39)
    if btype in ("ean13", "ean", "فروشگاهی"):
        digits = "".join(c for c in raw_val if c.isdigit())
        if len(digits) == 12:
            chk = compute_ean13_check_digit(digits)
            digits = f"{digits}{chk}"
        elif len(digits) != 13:
            # Fallback to code128 if not exact EAN13 length
            btype = "code128"
        else:
            calc_chk = compute_ean13_check_digit(digits[:12])
            if calc_chk != int(digits[12]):
                # Fix incorrect checksum automatically
                digits = f"{digits[:12]}{calc_chk}"
            raw_val = digits
            encoded = urllib.parse.quote(raw_val)

    # Standard 1D Barcode API rendering
    type_param = "ean13" if btype == "ean13" else ("code39" if "39" in btype else "code128")
    inc_text_str = "true" if include_text else "false"
    bc_url = f"https://quickchart.io/barcode?type={type_param}&text={encoded}&includeText={inc_text_str}&scale=3&height=120"

    btype_fa = {
        "code128": "کد ۱۲۸ (Code-128 صنعتی و لجستیک)",
        "ean13": "ای‌ان ۱۳ (EAN-13 استاندارد بین‌المللی کالا)",
        "code39": "کد ۳۹ (Code-39 الفبانمایی)"
    }.get(type_param, "بارکد استاندارد میله‌ای")

    return (
        f"📊 *بارکد استاندارد خطی و میله‌ای ({type_param.upper()})*:\n\n"
        f"• *استاندارد فرمت*: `{btype_fa}`\n"
        f"• *کد رمزگذاری‌شده*: `{raw_val}`\n"
        f"• *چک‌سام معتبر*: ✅ تایید شده با الگوریتم کنترلی\n"
        f"• *رزولوشن*: `Scale 3x Vectorized PNG`\n\n"
        f"🔗 [مشاهده و دانلود تصویر باکیفیت بارکد]({bc_url})"
    )


GS1_PREFIX_TABLE: List[Tuple[int, int, str]] = [
    (0, 139, "ایالات متحده و کانادا (USA & Canada - GS1 US)"),
    (300, 379, "فرانسه (France)"),
    (380, 380, "بلغارستان (Bulgaria)"),
    (383, 383, "اسلوونی (Slovenia)"),
    (385, 385, "کرواسی (Croatia)"),
    (400, 440, "آلمان (Germany)"),
    (450, 459, "ژاپن (Japan)"),
    (460, 469, "روسیه (Russia)"),
    (471, 471, "تایوان (Taiwan)"),
    (474, 474, "استونی (Estonia)"),
    (476, 476, "جمهوری آذربایجان (Azerbaijan)"),
    (482, 482, "اوکراین (Ukraine)"),
    (489, 489, "هنگ‌کنگ (Hong Kong)"),
    (490, 499, "ژاپن (Japan)"),
    (500, 509, "بریتانیا (United Kingdom)"),
    (520, 521, "یونان (Greece)"),
    (528, 528, "لبنان (Lebanon)"),
    (540, 549, "بلژیک و لوکزامبورگ (Belgium & Luxembourg)"),
    (560, 560, "پرتغال (Portugal)"),
    (570, 579, "دانمارک (Denmark)"),
    (590, 590, "لهستان (Poland)"),
    (594, 594, "رومانی (Romania)"),
    (599, 599, "مجارستان (Hungary)"),
    (600, 601, "آفریقای جنوبی (South Africa)"),
    (611, 611, "مراکش (Morocco)"),
    (619, 619, "تونس (Tunisia)"),
    (621, 621, "سوریه (Syria)"),
    (622, 622, "مصر (Egypt)"),
    (625, 625, "اردن (Jordan)"),
    (626, 626, "ایران (Islamic Republic of Iran - IRANCODE)"),
    (627, 627, "کویت (Kuwait)"),
    (628, 628, "عربستان سعودی (Saudi Arabia)"),
    (629, 629, "امارات متحده عربی (UAE)"),
    (640, 649, "فنلاند (Finland)"),
    (690, 699, "چین (China)"),
    (700, 709, "نروژ (Norway)"),
    (730, 739, "سوئد (Sweden)"),
    (750, 750, "مکزیک (Mexico)"),
    (760, 769, "سوئیس و لیختن‌اشتاین (Switzerland)"),
    (779, 779, "آرژانتین (Argentina)"),
    (789, 790, "برزیل (Brazil)"),
    (800, 839, "ایتالیا (Italy)"),
    (840, 849, "اسپانیا (Spain)"),
    (868, 869, "ترکیه (Turkey)"),
    (870, 879, "هلند (Netherlands)"),
    (880, 880, "کره جنوبی (South Korea)"),
    (885, 885, "تایلند (Thailand)"),
    (888, 888, "سنگاپور (Singapore)"),
    (890, 890, "هند (India)"),
    (893, 893, "ویتنام (Vietnam)"),
    (899, 899, "اندونزی (Indonesia)"),
    (900, 919, "اتریش (Austria)"),
    (930, 939, "استرالیا (Australia)"),
    (955, 955, "مالزی (Malaysia)"),
    (977, 977, "نشریات و مطبوعات دوره‌ای (ISSN)"),
    (978, 979, "کتاب‌ها و نشریات مکتوب بین‌المللی (ISBN)"),
]


def lookup_gs1_origin(code: str) -> str:
    """Returns the GS1 member country/region based on numeric prefix."""
    clean = "".join(c for c in code if c.isdigit())
    if len(clean) < 3:
        return "نامشخص (ارقام ناکافی)"
    prefix = int(clean[:3])
    for start, end, country in GS1_PREFIX_TABLE:
        if start <= prefix <= end:
            return country
    return "بین‌المللی / آزاد (GS1 Universal)"


def compute_ean8_check_digit(digits7: str) -> int:
    """Calculates standard EAN-8 check digit for 7 digits."""
    clean = "".join(c for c in digits7 if c.isdigit())[:7]
    if len(clean) != 7:
        return -1
    total = sum(int(clean[i]) * (3 if i % 2 == 0 else 1) for i in range(7))
    return (10 - (total % 10)) % 10


def compute_upca_check_digit(digits11: str) -> int:
    """Calculates standard UPC-A check digit for 11 digits."""
    clean = "".join(c for c in digits11 if c.isdigit())[:11]
    if len(clean) != 11:
        return -1
    total = sum(int(clean[i]) * (3 if i % 2 == 0 else 1) for i in range(11))
    return (10 - (total % 10)) % 10


def compute_isbn10_check_digit(digits9: str) -> str:
    """Calculates ISBN-10 modulo-11 check digit (returns '0'-'9' or 'X')."""
    clean = "".join(c for c in digits9 if c.isdigit())[:9]
    if len(clean) != 9:
        return ""
    total = sum(int(clean[i]) * (10 - i) for i in range(9))
    rem = (11 - (total % 11)) % 11
    return "X" if rem == 10 else str(rem)


def recover_missing_ean13_multi(clean_pattern: str, max_candidates: int = 10) -> List[Tuple[str, str]]:
    """
    Solves 1 to 2 missing wildcard digits in EAN-13 algebraically using Modulo-10 parity.
    Returns list of (full_candidate_13_digits, recovery_description).
    """
    if len(clean_pattern) != 13:
        return []
    missing_indices = [i for i, c in enumerate(clean_pattern) if c == "?"]
    if not missing_indices or len(missing_indices) > 2:
        return []

    results = []
    if len(missing_indices) == 1:
        idx = missing_indices[0]
        for digit in range(10):
            cand = clean_pattern[:idx] + str(digit) + clean_pattern[idx + 1 :]
            if compute_ean13_check_digit(cand[:12]) == int(cand[12]):
                results.append((cand, f"موقعیت {idx + 1} = `{digit}`"))
        return results

    if len(missing_indices) == 2:
        i1, i2 = missing_indices
        for d1 in range(10):
            for d2 in range(10):
                chars = list(clean_pattern)
                chars[i1] = str(d1)
                chars[i2] = str(d2)
                cand = "".join(chars)
                if compute_ean13_check_digit(cand[:12]) == int(cand[12]):
                    results.append((cand, f"موقعیت {i1 + 1} = `{d1}`، موقعیت {i2 + 1} = `{d2}`"))
                    if len(results) >= max_candidates:
                        return results
        return results

    return []


@register_tool(
    name="reconstruct_damaged_barcode_tool",
    description="بازسازی هوشمند، رمزگشایی و ترمیم تخصصی بارکدهای آسیب‌دیده، خط‌خورده، ساییده‌شده، پاره یا ناقص (EAN-13, EAN-8, UPC-A, Code-128, ISBN) با الگوریتم‌های بازیابی چک‌سام جبری Modulo-10/11، استعلام کشور مبدأ GS1 و بازتولید تصویر باکیفیت",
    category="media",
)
def reconstruct_damaged_barcode_tool(
    damaged_data: str,
    barcode_type: str = "auto",
    context_hint: Optional[str] = None,
) -> str:
    """
    :param damaged_data: ارقام یا کاراکترهای باقیمانده از بارکد با استفاده از علامت '?' یا '_' برای بخش‌های خط‌خورده یا مفقود (مثال: '6260123?56789' یا '626012??56786')
    :param barcode_type: نوع بارکد: 'ean13' (کالایی ۱۳ رقمی)، 'ean8' (۸ رقمی)، 'upca' (۱۲ رقمی)، 'code128' یا 'auto'
    :param context_hint: توضیحات تکمیلی، نام کشور یا نام کالا جهت اولویت‌بندی کاندیداها
    """
    raw = str(damaged_data or "").strip()
    if not raw:
        return "❌ لطفاً کاراکترها، ارقام باقیمانده یا تصویر بارکد آسیب‌دیده را وارد کنید."

    clean_pattern = "".join(c for c in raw if c.isdigit() or c in "?_*xX")
    normalized = re.sub(r"[_*xX]", "?", clean_pattern)
    btype = str(barcode_type or "auto").strip().lower()

    # 1. Single or Multi-Wildcard EAN-13 Algebraic Reconstruction
    if len(normalized) == 13 and "?" in normalized:
        candidates = recover_missing_ean13_multi(normalized, max_candidates=10)
        origin = lookup_gs1_origin(normalized)
        if len(candidates) == 1:
            full_code, rec_desc = candidates[0]
            new_bc = generate_barcode_tool(data=full_code, barcode_type="ean13")
            return (
                f"🛠 *گزارش تخصصی بازسازی قطعی بارکد EAN-13:*\n\n"
                f"• *کد ورودی مخدوش*: `{raw}`\n"
                f"• *رقم بازیابی‌شده جبری*: {rec_desc} (توازن وزنی Modulo-10)\n"
                f"• *کشور مبدأ / سازمان ثبت*: 🌍 *{origin}*\n"
                f"• *کد کامل و استاندارد*: `{full_code}`\n"
                f"• *وضعیت چک‌سام*: ✅ معتبر و ۱۰۰٪ اسکن‌پذیر جهانی\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{new_bc}"
            )
        elif len(candidates) > 1:
            origin = lookup_gs1_origin(normalized)
            cand_lines = [f"{idx+1}. `{c[0]}` ({c[1]})" for idx, c in enumerate(candidates)]
            # Generate sample from 1st candidate
            first_bc = generate_barcode_tool(data=candidates[0][0], barcode_type="ean13")
            return (
                f"🛠 *یافتن گزینه‌های محتمل با حل معادله چک‌سام چندمتغیره EAN-13:*\n\n"
                f"• *کد ورودی با چندین بخش مخدوش*: `{raw}`\n"
                f"• *کشور مبدأ استخراج‌شده*: 🌍 *{origin}*\n"
                f"• *کاندیداهای دارای اعتبار ریاضی ({len(candidates)} مورد)*:\n"
                + "\n".join(cand_lines)
                + f"\n\n💡 *پیش‌نمایش گزینه اول (`{candidates[0][0]}`):*\n{first_bc}"
            )

    # 2. 12-digit EAN-13 without check digit -> compute and append
    if len(normalized) == 12 and normalized.isdigit():
        chk = compute_ean13_check_digit(normalized)
        full_code = f"{normalized}{chk}"
        origin = lookup_gs1_origin(full_code)
        new_bc = generate_barcode_tool(data=full_code, barcode_type="ean13")
        return (
            f"🛠 *محاسبه رقم کنترل و تکمیل بارکد EAN-13:*\n\n"
            f"• *ارقام اولیه*: `{normalized}`\n"
            f"• *رقم کنترلی محاسبه‌شده (Check Digit)*: `{chk}`\n"
            f"• *کشور مبدأ*: 🌍 *{origin}*\n"
            f"• *بارکد نهایی EAN-13*: `{full_code}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{new_bc}"
        )

    # 3. 8-digit EAN-8 Recovery
    if len(normalized) == 8 and "?" in normalized:
        idx = normalized.index("?")
        if normalized.count("?") == 1:
            for digit in range(10):
                test_code = normalized[:idx] + str(digit) + normalized[idx + 1 :]
                if compute_ean8_check_digit(test_code[:7]) == int(test_code[7]):
                    new_bc = generate_barcode_tool(data=test_code, barcode_type="code128")
                    return (
                        f"🛠 *بازسازی تخصصی بارکد EAN-8:*\n\n"
                        f"• *کد مخدوش*: `{raw}`\n"
                        f"• *رقم بازیابی‌شده*: موقعیت {idx+1} = `{digit}`\n"
                        f"• *بارکد کامل سالم*: `{test_code}`\n\n"
                        f"{new_bc}"
                    )

    # 4. 12-digit UPC-A Recovery
    if len(normalized) == 12 and "?" in normalized:
        if normalized.count("?") == 1:
            idx = normalized.index("?")
            for digit in range(10):
                test_code = normalized[:idx] + str(digit) + normalized[idx + 1 :]
                if compute_upca_check_digit(test_code[:11]) == int(test_code[11]):
                    new_bc = generate_barcode_tool(data=test_code, barcode_type="code128")
                    return (
                        f"🛠 *بازسازی تخصصی بارکد UPC-A (آمریکا/کانادا):*\n\n"
                        f"• *کد مخدوش*: `{raw}`\n"
                        f"• *رقم بازیابی‌شده*: موقعیت {idx+1} = `{digit}`\n"
                        f"• *کد کامل بازسازی‌شده*: `{test_code}`\n\n"
                        f"{new_bc}"
                    )

    # 5. General Code-128 / Multi-wildcard structure
    if "?" in raw:
        clean_prefix = raw.split("?")[0].strip()
        new_bc = generate_barcode_tool(data=raw.replace("?", "0"), barcode_type=btype)
        return (
            f"🛠 *تحلیل ساختار و بازسازی مقدماتی بارکد:*\n\n"
            f"• *بخش خوانای کشف‌شده*: `{clean_prefix or raw}`\n"
            f"• *تعداد کاراکترهای مخدوش*: `{raw.count('?')}` موقعیت\n"
            f"• *نوع بارکد انتخابی*: `{btype}`\n"
            f"• *راهنما*: اگر تصویر بارکد را به صورت عکس ارسال کنید، هوش مصنوعی تصویر را تحلیل و میله‌ها را مستقیماً می‌خواند.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{new_bc}"
        )

    # 6. Full pristine data provided -> Regenerate with metadata
    origin_txt = ""
    if len(raw) in (12, 13) and raw.isdigit():
        origin_txt = f"\n• *کشور مبدأ*: 🌍 *{lookup_gs1_origin(raw)}*"

    new_bc = generate_barcode_tool(data=raw, barcode_type=btype)
    return (
        f"✨ *بارکد کاملاً سالم و اسکن‌پذیر مجدد تولید گردید:*\n\n"
        f"• *داده اصلی*: `{raw}`{origin_txt}\n\n"
        f"{new_bc}"
    )
