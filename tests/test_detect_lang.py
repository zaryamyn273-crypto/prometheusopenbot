"""Offline tests for message-text language detection (world users)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.i18n import detect_lang, lang_name


def check(text, expected):
    got = detect_lang(text)
    assert got == expected, f"{text!r}: got {got}, want {expected}"


def main():
    check("سلام پرومته چطوری؟", "fa")
    check("ربات دلار چنده؟", "fa")
    check("تو کی هستی", "fa")
    check("حالت خوبه", "fa")
    check("داستان بنویس", "fa")
    check("خسته نباشی", "fa")
    check("ساعت سه بیا", "fa")
    check("این متن رو خلاصه کن", "fa")
    check("Hello Prometheus, how are you?", "en")
    check("leave group test", "en")
    check("Привет, как дела?", "ru")
    check("Привіт, як справи?", "uk")
    check("Hola, ¿cómo estás?", "es")
    check("Bonjour, comment ça va?", "fr")
    check("Hallo, wie geht es dir?", "de")
    check("Ciao, come stai?", "it")
    check("Merhaba, nasılsın?", "tr")
    check("مرحبا، کیف حالک؟", "ar")
    check("كيف حالك اليوم", "ar")
    check("هل يمكنك مساعدتي", "ar")
    check("شکرا جزیلا لک", "ar")
    check("こんにちは元気ですか", "ja")
    check("안녕하세요", "ko")
    check("你好吗", "zh")
    check("12345 😀👍", "und")
    check("", "und")
    check("   ", "und")
    assert lang_name(detect_lang("Hola")) == "Spanish"
    assert lang_name(detect_lang("سلام")) == "Persian (Farsi)"
    print("== test_detect_lang DONE ==")


if __name__ == "__main__":
    main()
