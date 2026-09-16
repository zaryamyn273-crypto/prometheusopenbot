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
    check("Hello Prometheus, how are you?", "fa")
    check("leave group test", "fa")
    check("Привет, как дела?", "fa")
    check("Привіт, як справи?", "fa")
    check("Hola, ¿cómo estás?", "fa")
    check("Bonjour, comment ça va?", "fa")
    check("Hallo, wie geht es dir?", "fa")
    check("Ciao, come stai?", "fa")
    check("Merhaba, nasılsın?", "fa")
    check("مرحبا، کیف حالک؟", "fa")
    check("12345 😀👍", "fa")
    check("", "fa")
    check("   ", "fa")
    assert lang_name(detect_lang("Hola")) == "Persian (Farsi)"
    assert lang_name(detect_lang("سلام")) == "Persian (Farsi)"
    print("== test_detect_lang DONE ==")


if __name__ == "__main__":
    main()
