"""
Core Security Module: Multi-Layer Secret Sanitization and AST Code Sandboxing.

1. sanitize_output: Scrubs known API keys, environment secrets, Telegram bot tokens,
   Bearer headers, and high-entropy key patterns before delivering output to users.
2. validate_python_code: AST-based static code analysis preventing execution of
   dangerous calls, dynamic imports, reflection, and sandbox-escape attribute traversals.
"""

import ast
import logging
import os
import re
from typing import Set, List
from src.core import config as _config

logger = logging.getLogger(__name__)

# --- Secrets Sanitizer ---
def _build_secrets_list() -> List[str]:
    """Dynamically read secrets fresh from configuration and environment."""
    vals = [
        getattr(_config, "TELEGRAM_BOT_TOKEN", ""),
        getattr(_config, "ROUTER_API_KEY", ""),
        getattr(_config, "ALLRATESTODAY_API_KEY", ""),
        getattr(_config, "GITHUB_TOKEN", ""),
        getattr(_config, "CLOUDFLARE_API_TOKEN", ""),
        getattr(_config, "CLOUDFLARE_ACCOUNT_ID", ""),
        getattr(_config, "CLOUDFLARE_D1_ID", ""),
        getattr(_config, "CLOUDFLARE_KV_ID", ""),
        os.getenv("TAVILY_API_KEY", ""),
        os.getenv("TAVILY_API_KEYS", ""),
        os.getenv("SPOTIFY_CLIENT_ID", ""),
        os.getenv("SPOTIFY_CLIENT_SECRET", ""),
        os.getenv("E2B_API_KEY", ""),
        getattr(_config, "E2B_API_KEY", ""),
        os.getenv("RAILWAY_TOKEN", ""),
        os.getenv("RAILWAY_API_TOKEN", ""),
        getattr(_config, "RAILWAY_TOKEN", ""),
        getattr(_config, "get_railway_token", lambda: "")(),
        getattr(_config, "get_github_token", lambda: "")(),
        getattr(_config, "get_e2b_api_key", lambda: "")(),
        os.getenv("API_KEY_SECRET", ""),
    ]
    out = []
    seen = set()
    for v in vals:
        if not v:
            continue
        for part in str(v).split(","):
            part = part.strip()
            if len(part) > 3 and part not in seen:
                seen.add(part)
                out.append(part)
    return out


_PATTERNS_EXTRA = [
    # Telegram Bot Token (e.g. 1234567890:AAFakeToken...)
    re.compile(r'\b\d{8,11}:[A-Za-z0-9_-]{34,38}\b'),
    # OpenAI / 9Router / Gemini / DeepSeek API Keys
    re.compile(r'\bsk-[A-Za-z0-9_-]{16,}\b'),
    # GitHub Personal Access Tokens
    re.compile(r'\bghp_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgho_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{10,}\b'),
    # Tavily Search API Keys
    re.compile(r'\btvly-[A-Za-z0-9_\-]{8,}\b'),
    # AllRatesToday API Keys
    re.compile(r'\bart_live_[A-Za-z0-9]{8,}\b'),
    # E2B Sandbox API Keys
    re.compile(r'\be2b_[A-Za-z0-9]{16,}\b'),
    # Bearer Authentication Headers
    re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{20,}', re.IGNORECASE),
    # Key-Value credential declarations (api_key = "...")
    re.compile(r'(?:api[-_]?key|auth_token|client_secret)\s*[:=]\s*["\']?[A-Za-z0-9_\-\.]{12,}["\']?', re.IGNORECASE),
]


def deduplicate_repeated_text(text: str) -> str:
    """Eliminates LLM stutter/loop repetitions, doubled sentences, or identical consecutive halves."""
    if not text or not isinstance(text, str) or len(text) < 10:
        return text
    t = text.strip()

    # Never tamper with markdown code blocks
    if "```" in t:
        return text

    # 1. Exact halving (e.g. "در خدمتم. درخواستت رو مستقیم مطرح کن.در خدمتم. درخواستت رو مستقیم مطرح کن.")
    n = len(t)
    if n >= 12 and n % 2 == 0:
        half = n // 2
        if t[:half] == t[half:]:
            return deduplicate_repeated_text(t[:half])

    # 2. Exact chunk repetition: (chunk)(chunk)+ or (chunk)\s+(chunk)+
    m = re.match(r"^(.{8,}?)(?:[\s\n]*)\1+$", t, re.DOTALL)
    if m:
        return deduplicate_repeated_text(m.group(1))

    # 3. Sentence-level consecutive duplicate removal (e.g. "A. A. B.")
    parts = re.split(r"([.!?؟\n]+)", t)
    if len(parts) >= 4:
        deduped = []
        i = 0
        while i < len(parts):
            chunk = parts[i]
            delim = parts[i + 1] if i + 1 < len(parts) else ""
            unit = (chunk + delim).strip()

            next_chunk = parts[i + 2] if i + 2 < len(parts) else ""
            next_delim = parts[i + 3] if i + 3 < len(parts) else ""
            next_unit = (next_chunk + next_delim).strip()

            if unit and unit == next_unit and len(unit) >= 8:
                deduped.append(chunk + delim)
                i += 4  # skip duplicated unit
            else:
                deduped.append(chunk + delim)
                i += 2
        res = "".join(deduped).strip()
        if res != t:
            return deduplicate_repeated_text(res)

    return text


def sanitize_output(text: str) -> str:
    """Scrub all sensitive keys, tokens, credentials, and stutter loops from outgoing text."""
    if not text:
        return text
    sanitized = deduplicate_repeated_text(text)

    # Exact match from active configuration
    for sec in _build_secrets_list():
        try:
            if sec and len(str(sec)) > 3 and str(sec) in sanitized:
                sanitized = sanitized.replace(str(sec), "[SECRET]")
        except Exception:
            continue

    # Structural regex patterns for leaked formats
    for pat in _PATTERNS_EXTRA:
        try:
            sanitized = pat.sub("[SECRET]", sanitized)
        except Exception:
            continue

    return sanitized


# --- AST Python Security ---
FORBIDDEN_ATTRIBUTES: Set[str] = {
    "__class__", "__bases__", "__subclasses__", "__globals__", "__mro__",
    "__code__", "__closure__", "__builtins__", "__import__", "__reduce__",
    "__reduce_ex__", "__loader__", "__spec__", "__package__",
    "__dict__", "__module__", "__qualname__", "f_globals", "f_locals",
    "gi_frame", "gi_code", "cr_frame", "tb_frame", "f_builtins",
}

FORBIDDEN_CALLS: Set[str] = {
    "__import__", "eval", "exec", "compile", "open", "input",
    "breakpoint", "help", "exit", "quit",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "dir", "memoryview", "import_module", "system", "popen", "spawn",
    "execv", "execve",
}


class SecurityASTValidator(ast.NodeVisitor):
    """AST visitor that detects and blocks unauthorized operations and sandbox escapes."""
    def __init__(self):
        self.violations = []

    def visit_Import(self, node):
        self.violations.append(f"Import restricted: {[a.name for a in node.names]}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        self.violations.append(f"ImportFrom restricted: {node.module}")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in FORBIDDEN_ATTRIBUTES:
            self.violations.append(f"Attribute '{node.attr}' forbidden.")
        # Block __builtins__ access via attribute chain
        if isinstance(node.value, ast.Name) and node.value.id == "__builtins__":
            self.violations.append("Access to __builtins__ forbidden.")
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
            self.violations.append(f"Function call '{func.id}' forbidden.")
        elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALLS:
            self.violations.append(f"Method/call '{func.attr}' forbidden.")
        self.generic_visit(node)


def validate_python_code(code: str) -> None:
    """Validate python code using AST; raises ValueError on syntax error or PermissionError on violation."""
    if not code or len(code) > 20000:
        raise ValueError("Code too large or empty.")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax Error: {e}")
    validator = SecurityASTValidator()
    validator.visit(tree)
    if validator.violations:
        raise PermissionError("; ".join(validator.violations))
