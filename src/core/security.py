import ast
import logging
import os
import re
from typing import Set, List
from src.core import config as _config

logger = logging.getLogger(__name__)

# --- Secrets Sanitizer ---
def _build_secrets_list() -> List[str]:
    # Dynamic: read fresh from env/config every call so rotation works.
    # (No import-time static snapshot: those went stale after key rotation.)
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
    re.compile(r'ghp_[A-Za-z0-9]{20,}'),
    re.compile(r'gho_[A-Za-z0-9]{20,}'),
    re.compile(r'github_pat_[A-Za-z0-9_]{10,}'),
    re.compile(r'tvly-[A-Za-z0-9_\-]{8,}'),
    re.compile(r'art_live_[A-Za-z0-9]{8,}'),
    re.compile(r'e2b_[A-Za-z0-9]{16,}'),
]

def sanitize_output(text: str) -> str:
    if not text:
        return text
    sanitized = text
    for sec in _build_secrets_list():
        try:
            if sec and len(str(sec)) > 3 and str(sec) in sanitized:
                sanitized = sanitized.replace(str(sec), "[SECRET]")
        except Exception:
            continue
    for pat in _PATTERNS_EXTRA:
        try:
            sanitized = pat.sub("[SECRET]", sanitized)
        except Exception:
            continue
    return sanitized

# --- AST Python Security ---
FORBIDDEN_ATTRIBUTES: Set[str] = {
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__code__", "__closure__", "__builtins__", "__import__",
    "__dict__", "__module__", "__qualname__", "f_globals", "f_locals",
    "gi_frame", "gi_code", "cr_frame", "tb_frame", "f_builtins",
}

FORBIDDEN_CALLS: Set[str] = {
    "__import__", "eval", "exec", "compile", "open", "input",
    "breakpoint", "help", "exit", "quit",
    "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "dir", "memoryview", "import_module",
}

class SecurityASTValidator(ast.NodeVisitor):
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
        # Only real call expressions are dangerous; bare name mentions
        # (variables, f-string text, attribute bases) are harmless.
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
            self.violations.append(f"Function call '{func.id}' forbidden.")
        elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_CALLS:
            self.violations.append(f"Method/call '{func.attr}' forbidden.")
        self.generic_visit(node)

def validate_python_code(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax Error: {e}")
    validator = SecurityASTValidator()
    validator.visit(tree)
    if validator.violations:
        raise PermissionError("; ".join(validator.violations))
