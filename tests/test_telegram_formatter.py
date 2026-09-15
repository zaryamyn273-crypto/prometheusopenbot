import pytest
from src.utils.telegram_formatter import (
    markdown_to_telegram_html,
    balance_html_tags,
    strip_html_to_plain,
    split_telegram_html
)

def test_markdown_formatting_basics():
    raw = "**متن بولد** و *کلمه دوم* و _متن ایتالیک_ و ~~خط خورده~~ و ||اسپویلر||"
    html = markdown_to_telegram_html(raw)
    assert "<b>متن بولد</b>" in html
    assert "<b>کلمه دوم</b>" in html
    assert "<i>متن ایتالیک</i>" in html
    assert "<s>خط خورده</s>" in html
    assert "<tg-spoiler>اسپویلر</tg-spoiler>" in html

def test_code_blocks_and_inline():
    raw = "این یک `inline_code()` است و زیرین کد بلاک:\n```python\ndef test():\n    return 42 > 10 && True\n```"
    html = markdown_to_telegram_html(raw)
    assert "<code>inline_code()</code>" in html
    assert '<pre><code class="language-python">' in html
    assert "42 &gt; 10 &amp;&amp; True" in html  # correctly escaped inside code block

def test_markdown_quotes():
    raw = "مقدمه:\n> این یک نقل‌قول تست است\n> ادامه نقل‌قول\nپایان"
    html = markdown_to_telegram_html(raw)
    assert "<blockquote>این یک نقل‌قول تست است<br/>ادامه نقل‌قول</blockquote>" in html
    assert "مقدمه:" in html
    assert "پایان" in html

def test_markdown_bullets():
    raw = "- مورد اول\n- مورد دوم\n* مورد سوم"
    html = markdown_to_telegram_html(raw)
    assert "• مورد اول" in html
    assert "• مورد دوم" in html
    assert "• مورد سوم" in html

def test_markdown_tables():
    raw = "| نام ارز | قیمت (تومان) |\n|---|---|\n| تتر | ۱۰۰,۰۰۰ |\n| بیت‌کوین | ۸,۰۰۰,۰۰۰,۰۰۰ |"
    html = markdown_to_telegram_html(raw)
    assert "<pre>" in html
    assert "نام ارز" in html
    assert "تتر" in html

def test_tag_balancing():
    unbalanced = "<b>سلام <i>جهان <code>کد"
    balanced = balance_html_tags(unbalanced)
    assert balanced == "<b>سلام <i>جهان <code>کد</code></i></b>"

    stray_closing = "سلام</b> جهان</i>"
    balanced_stray = balance_html_tags(stray_closing)
    assert balanced_stray == "سلام جهان"

def test_strip_html_to_plain():
    html_input = "<b>متن مهم</b> &amp; <code>print('hello &lt; world')</code>"
    plain = strip_html_to_plain(html_input)
    assert plain == "متن مهم & print('hello < world')"

def test_split_telegram_html():
    long_content = "<b>" + ("سلام " * 1000) + "</b>"
    chunks = split_telegram_html(long_content, max_chunk_len=1000)
    assert len(chunks) > 1
    for ch in chunks:
        # Every chunk must have properly balanced tags
        assert ch.count("<b>") == ch.count("</b>")
