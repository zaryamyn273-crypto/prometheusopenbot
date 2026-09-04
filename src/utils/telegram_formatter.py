import re
from typing import List

RE_CODE_BLOCK = re.compile(r'```([a-zA-Z0-9_-]*)\n?(.*?)```', re.DOTALL)
RE_INLINE_CODE = re.compile(r'`([^`\n]+)`')
RE_BOLD_DOUBLE = re.compile(r'\*\*(.+?)\*\*')
RE_BOLD_SINGLE = re.compile(r'(?<!\*)\*([^\*\n]+)\*(?!\*)')
RE_ITALIC_UNDER = re.compile(r'(?<!\w)_([^_]+)_(?!\w)')
RE_STRIKE = re.compile(r'~~(.+?)~~')
RE_SPOILER = re.compile(r'\|\|(.+?)\|\|')
RE_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)')

def escape_html_chars(text: str) -> str:
    """Safely escapes raw HTML characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def markdown_to_telegram_html(markdown_text: str, wrap_expandable_if_long: bool = True) -> str:
    """
    Robust Markdown to Telegram HTML converter.
    Guarantees well-formed HTML tags and wraps lengthy responses inside
    Telegram's native Expandable Blockquote (<blockquote expandable>) when appropriate.
    """
    if not markdown_text:
        return ""

    text = markdown_text

    # 1. Protect code blocks
    code_blocks: List[str] = []
    def _code_block_sub(match):
        lang = match.group(1).strip()
        code = match.group(2)
        escaped_code = escape_html_chars(code)
        idx = len(code_blocks)
        if lang:
            code_blocks.append(f'<pre><code class="language-{lang}">{escaped_code}</code></pre>')
        else:
            code_blocks.append(f'<pre><code>{escaped_code}</code></pre>')
        return f"TOKENCODEBLOCK{idx}TOKEN"

    text = RE_CODE_BLOCK.sub(_code_block_sub, text)

    # 2. Protect inline code
    inline_codes: List[str] = []
    def _inline_code_sub(match):
        code = match.group(1)
        escaped_code = escape_html_chars(code)
        idx = len(inline_codes)
        inline_codes.append(f'<code>{escaped_code}</code>')
        return f"TOKENINLINECODE{idx}TOKEN"

    text = RE_INLINE_CODE.sub(_inline_code_sub, text)

    # 3. Escape all remaining HTML entities in text body
    text = escape_html_chars(text)

    # 4. Spoilers & Strikethrough
    text = RE_SPOILER.sub(r'<tg-spoiler>\1</tg-spoiler>', text)
    text = RE_STRIKE.sub(r'<s>\1</s>', text)

    # 5. Bold, Italic & Links
    text = RE_BOLD_DOUBLE.sub(r'<b>\1</b>', text)
    text = RE_BOLD_SINGLE.sub(r'<b>\1</b>', text)
    text = RE_ITALIC_UNDER.sub(r'<i>\1</i>', text)
    text = RE_LINK.sub(r'<a href="\2">\1</a>', text)

    # 6. Headers
    lines = text.split("\n")
    formatted_lines = []
    for line in lines:
        s = line.strip()
        if s.startswith("### "):
            line = f"<b>{s[4:].strip()}</b>"
        elif s.startswith("## "):
            line = f"<b>{s[3:].strip()}</b>"
        elif s.startswith("# "):
            line = f"<b>{s[2:].strip()}</b>"
        formatted_lines.append(line)
    text = "\n".join(formatted_lines)

    # 7. Restore code blocks & inline code placeholders
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"TOKENCODEBLOCK{idx}TOKEN", block)

    for idx, code in enumerate(inline_codes):
        text = text.replace(f"TOKENINLINECODE{idx}TOKEN", code)

    # Clean leftover double bold / empty tags
    text = re.sub(r'<b>\s*<b>(.*?)</b>\s*</b>', r'<b>\1</b>', text)
    text = text.replace("<b></b>", "").replace("<i></i>", "")

    clean_res = text.strip()

    # Wrap in expandable blockquote if text is long (> 650 chars) and doesn't already contain blockquotes
    if wrap_expandable_if_long and len(clean_res) > 650 and "<blockquote" not in clean_res and "<pre>" not in clean_res:
        clean_res = f"<blockquote expandable>{clean_res}</blockquote>"

    return clean_res
