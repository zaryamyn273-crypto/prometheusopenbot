import re
import html
from typing import List, Tuple

RE_CODE_BLOCK = re.compile(r'```([a-zA-Z0-9_-]*)\n?(.*?)```', re.DOTALL)
RE_INLINE_CODE = re.compile(r'`([^`\n]+)`')
RE_BOLD_DOUBLE = re.compile(r'\*\*(.+?)\*\*')
RE_BOLD_SINGLE = re.compile(r'(?<!\*)\*([^\*\n\s][^\*\n]*?[^\*\n\s]|[^\*\n\s])\*(?!\*)')
RE_ITALIC_UNDER = re.compile(r'(?<!\w)_([^_]+)_(?!\w)')
RE_STRIKE = re.compile(r'~~(.+?)~~')
RE_SPOILER = re.compile(r'\|\|(.+?)\|\|')
RE_LINK = re.compile(r'\[([^\]]+)\]\((https?://[^\s\)]+|tg://[^\s\)]+)\)')

# Telegram supported HTML tags (case-insensitive for safety)
VALID_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "tg-spoiler", "a", "code", "pre", "blockquote"}

def escape_html_chars(text: str) -> str:
    """Safely escapes raw HTML characters (&, <, >)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def strip_html_to_plain(html_text: str) -> str:
    """
    Strips all HTML tags and unescapes HTML entities.
    Used as an ultra-safe fallback when Telegram Bot API rejects formatted HTML.
    """
    if not html_text:
        return ""
    # Remove all HTML tags
    clean = re.sub(r'<[^>]+>', '', html_text)
    # Unescape HTML entities (&amp; -> &, &lt; -> <, etc.)
    return html.unescape(clean).strip()

def _format_markdown_tables(text: str) -> str:
    """
    Detects standard Markdown tables and renders them inside monospaced <pre> blocks
    so they appear neatly aligned on Telegram clients.
    """
    lines = text.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if line looks like a table row: starts/ends or contains multiple |
        if "|" in line and i + 1 < len(lines) and re.match(r'^\s*\|?\s*[-:]+[-| :]+\s*\|?\s*$', lines[i + 1]):
            # Start of a markdown table
            table_lines = [line]
            i += 1
            table_lines.append(lines[i])  # separator line
            i += 1
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1

            # Parse table rows into cells
            parsed_rows = []
            for t_line in table_lines:
                # skip separator row for data rows
                cells = [c.strip() for c in t_line.strip().strip("|").split("|")]
                parsed_rows.append(cells)

            if len(parsed_rows) >= 2:
                headers = parsed_rows[0]
                data_rows = parsed_rows[2:] if len(parsed_rows) > 2 else []

                # Calculate max width for each column
                num_cols = max(len(row) for row in parsed_rows)
                col_widths = [0] * num_cols
                for row in [headers] + data_rows:
                    for col_idx, cell in enumerate(row):
                        if col_idx < num_cols:
                            col_widths[col_idx] = max(col_widths[col_idx], len(cell))

                # Build monospaced representation
                formatted_table = []
                # Header row
                header_str = " | ".join(h.ljust(col_widths[idx]) for idx, h in enumerate(headers))
                formatted_table.append(header_str)
                # Separator
                sep_str = "-+-".join("-" * col_widths[idx] for idx in range(num_cols))
                formatted_table.append(sep_str)
                # Data rows
                for row in data_rows:
                    padded_cells = []
                    for col_idx in range(num_cols):
                        val = row[col_idx] if col_idx < len(row) else ""
                        padded_cells.append(val.ljust(col_widths[col_idx]))
                    formatted_table.append(" | ".join(padded_cells))

                result_lines.append(f"<pre>{escape_html_chars(chr(10).join(formatted_table))}</pre>")
                continue
        result_lines.append(line)
        i += 1
    return "\n".join(result_lines)

def balance_html_tags(html_text: str) -> str:
    """
    Validates and balances Telegram-compatible HTML tags.
    Ensures that any opened tag (<b>, <i>, <code>, <pre>, <blockquote>, etc.)
    has a matching closing tag in the correct nesting order.
    Eliminates Telegram 'Can't parse entities: can't find end tag' errors.
    """
    if not html_text:
        return ""

    # Tokenize tags
    tag_regex = re.compile(r'</?([a-zA-Z0-9_-]+)(?:\s+[^>]*)?>')
    open_stack: List[str] = []
    out = []
    last_idx = 0

    for m in tag_regex.finditer(html_text):
        out.append(html_text[last_idx:m.start()])
        full_tag = m.group(0)
        tag_name = m.group(1).lower()

        if tag_name not in VALID_TELEGRAM_TAGS:
            # Not a supported Telegram tag; escape or keep as raw text
            out.append(escape_html_chars(full_tag))
            last_idx = m.end()
            continue

        if full_tag.startswith("</"):
            # Closing tag
            if open_stack and open_stack[-1] == tag_name:
                open_stack.pop()
                out.append(full_tag)
            elif tag_name in open_stack:
                # Need to close intermediate tags to maintain nesting
                while open_stack and open_stack[-1] != tag_name:
                    unclosed = open_stack.pop()
                    out.append(f"</{unclosed}>")
                if open_stack and open_stack[-1] == tag_name:
                    open_stack.pop()
                    out.append(full_tag)
            else:
                # Stray closing tag with no matching open tag: drop it
                pass
        else:
            # Opening tag
            # If it's already an expandable blockquote, remember it as 'blockquote'
            open_stack.append(tag_name)
            out.append(full_tag)

        last_idx = m.end()

    out.append(html_text[last_idx:])

    # Close any remaining unclosed tags in reverse order
    while open_stack:
        unclosed = open_stack.pop()
        out.append(f"</{unclosed}>")

    return "".join(out)

def markdown_to_telegram_html(markdown_text: str, wrap_expandable_if_long: bool = False) -> str:
    """
    High-fidelity CommonMark & Telegram Markdown to Telegram HTML converter.
    Guarantees 100% compliant HTML, flawless tag balancing, and beautiful formatting
    for code blocks, lists, quotes, tables, bold, and italic text.
    """
    if not markdown_text:
        return ""

    text = markdown_text

    # 1. Protect code blocks (```lang ... ```)
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

    # 1b. Handle unclosed code block at end of text (e.g. streaming or cut-off)
    if "```" in text:
        unclosed_match = re.search(r'```([a-zA-Z0-9_-]*)\n?(.*)$', text, re.DOTALL)
        if unclosed_match:
            lang = unclosed_match.group(1).strip()
            code = unclosed_match.group(2)
            escaped_code = escape_html_chars(code)
            idx = len(code_blocks)
            if lang:
                code_blocks.append(f'<pre><code class="language-{lang}">{escaped_code}</code></pre>')
            else:
                code_blocks.append(f'<pre><code>{escaped_code}</code></pre>')
            text = text[:unclosed_match.start()] + f"TOKENCODEBLOCK{idx}TOKEN"

    # 2. Format markdown tables before escaping
    text = _format_markdown_tables(text)

    # 3. Protect inline code (`code`)
    inline_codes: List[str] = []
    def _inline_code_sub(match):
        code = match.group(1)
        escaped_code = escape_html_chars(code)
        idx = len(inline_codes)
        inline_codes.append(f'<code>{escaped_code}</code>')
        return f"TOKENINLINECODE{idx}TOKEN"

    text = RE_INLINE_CODE.sub(_inline_code_sub, text)

    # 4. Protect existing valid preformatted blocks (like from tables)
    preserved_pre: List[str] = []
    def _pre_sub(match):
        idx = len(preserved_pre)
        preserved_pre.append(match.group(0))
        return f"TOKENPREBLOCK{idx}TOKEN"

    text = re.sub(r'<pre>.*?</pre>', _pre_sub, text, flags=re.DOTALL)

    # 5. Escape all remaining raw HTML entities
    text = escape_html_chars(text)

    # 6. Spoilers & Strikethrough
    text = RE_SPOILER.sub(r'<tg-spoiler>\1</tg-spoiler>', text)
    text = RE_STRIKE.sub(r'<s>\1</s>', text)

    # 7. Bold & Italic (distinguish double vs single cleanly)
    # ***bold italic***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # **bold**
    text = RE_BOLD_DOUBLE.sub(r'<b>\1</b>', text)
    # *bold* or *italic* (non-bullet)
    text = RE_BOLD_SINGLE.sub(r'<b>\1</b>', text)
    # _italic_ (boundary protected)
    text = RE_ITALIC_UNDER.sub(r'<i>\1</i>', text)

    # 8. Links: [text](url)
    def _link_sub(m):
        link_text = m.group(1)
        link_url = m.group(2)
        # unescape HTML entities in url so Telegram parser accepts it
        clean_url = html.unescape(link_url).replace('"', '&quot;')
        return f'<a href="{clean_url}">{link_text}</a>'

    text = RE_LINK.sub(_link_sub, text)

    # 9. Line-by-line processing: Headers, Blockquotes, Bullet Lists
    lines = text.split("\n")
    formatted_lines = []
    in_quote_block = False
    quote_accumulator: List[str] = []

    def _flush_quote():
        nonlocal in_quote_block, quote_accumulator, formatted_lines
        if quote_accumulator:
            q_text = "\n".join(quote_accumulator)
            if len(q_text) > 350:
                formatted_lines.append(f'<blockquote expandable>{q_text}</blockquote>')
            else:
                formatted_lines.append(f'<blockquote>{q_text}</blockquote>')
            quote_accumulator = []
        in_quote_block = False

    for line in lines:
        s = line.strip()

        # Markdown Quotes (> text, &gt; text)
        if s.startswith("&gt; ") or s.startswith("&gt;&gt; ") or s.startswith("> "):
            in_quote_block = True
            if s.startswith("&gt;&gt; "):
                quote_accumulator.append(s[9:].strip())
            elif s.startswith("&gt; "):
                quote_accumulator.append(s[5:].strip())
            elif s.startswith("> "):
                quote_accumulator.append(s[2:].strip())
            continue
        elif in_quote_block:
            _flush_quote()

        # Headers (# Title, ## Title, ### Title, #### Title)
        if s.startswith("#### "):
            line = f"<b>{s[5:].strip()}</b>"
        elif s.startswith("### "):
            line = f"<b>{s[4:].strip()}</b>"
        elif s.startswith("## "):
            line = f"<b>{s[3:].strip()}</b>"
        elif s.startswith("# "):
            line = f"<b>{s[2:].strip()}</b>"
        # Bullet list formatting (- item, * item)
        elif re.match(r'^\s*[-*+]\s+(.*)$', line):
            m_bullet = re.match(r'^(\s*)[-*+]\s+(.*)$', line)
            if m_bullet:
                indent = m_bullet.group(1)
                content = m_bullet.group(2)
                line = f"{indent}• {content}"

        formatted_lines.append(line)

    if in_quote_block:
        _flush_quote()

    text = "\n".join(formatted_lines)

    # 10. Restore code blocks & inline code placeholders
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"TOKENCODEBLOCK{idx}TOKEN", block)

    for idx, code in enumerate(inline_codes):
        text = text.replace(f"TOKENINLINECODE{idx}TOKEN", code)

    for idx, pre_block in enumerate(preserved_pre):
        text = text.replace(f"TOKENPREBLOCK{idx}TOKEN", pre_block)

    # Clean leftover double bold / empty tags
    text = re.sub(r'<b>\s*<b>(.*?)</b>\s*</b>', r'<b>\1</b>', text)
    text = text.replace("<b></b>", "").replace("<i></i>", "").replace("<code></code>", "")

    # 11. Balance all HTML tags to prevent Telegram Bot API entity parse errors
    balanced_res = balance_html_tags(text.strip())

    if wrap_expandable_if_long and len(balanced_res) > 700 and "<blockquote" not in balanced_res and "<pre>" not in balanced_res:
        balanced_res = f"<blockquote expandable>{balanced_res}</blockquote>"

    return balanced_res

def split_telegram_html(html_text: str, max_chunk_len: int = 3800) -> List[str]:
    """
    Splits Telegram HTML into chunks within the 4096 character limit,
    while safely closing and re-opening any active formatting tags across chunk boundaries.
    """
    if not html_text:
        return []
    if len(html_text) <= max_chunk_len:
        return [html_text]

    chunks: List[str] = []
    lines = html_text.split("\n")
    current_chunk = ""
    active_tags: List[str] = []

    tag_regex = re.compile(r'</?([a-zA-Z0-9_-]+)(?:\s+[^>]*)?>')

    for line in lines:
        test_chunk = (current_chunk + "\n" + line) if current_chunk else line

        if len(test_chunk) > max_chunk_len:
            if current_chunk:
                # Close all currently active tags at the end of this chunk
                closed_chunk = balance_html_tags(current_chunk)
                chunks.append(closed_chunk)

                # Determine which tags were open so we can reopen them
                open_stack: List[Tuple[str, str]] = []
                for m in tag_regex.finditer(current_chunk):
                    tag_str = m.group(0)
                    t_name = m.group(1).lower()
                    if t_name not in VALID_TELEGRAM_TAGS:
                        continue
                    if tag_str.startswith("</"):
                        if open_stack and open_stack[-1][0] == t_name:
                            open_stack.pop()
                    else:
                        open_stack.append((t_name, tag_str))

                # Re-open with full tag attributes in the next chunk
                reopen_prefix = "".join(full_tag for _, full_tag in open_stack)
                current_chunk = reopen_prefix + line if reopen_prefix else line
            else:
                # Single line is huge (e.g. huge data blob)
                while len(line) > max_chunk_len:
                    part = line[:max_chunk_len]
                    chunks.append(balance_html_tags(part))
                    line = line[max_chunk_len:]
                current_chunk = line
        else:
            current_chunk = test_chunk

    if current_chunk.strip():
        chunks.append(balance_html_tags(current_chunk))

    return chunks
