import ast
import logging
import time
from typing import Set, List
from src.core.config import (
    TELEGRAM_BOT_TOKEN,
    ROUTER_API_KEY,
    TINYFISH_API_KEY,
    ALLRATESTODAY_API_KEY,
    GITHUB_TOKEN,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_ACCOUNT_ID,
    ADMIN_ID,
)

logger = logging.getLogger(__name__)

# --- Token-Bucket Rate Limiter ---
class TokenBucketRateLimiter:
    def __init__(self, rate: float = 5.0, capacity: float = 10.0):
        self.rate = rate
        self.capacity = capacity
        self.buckets = {}

    def allow(self, user_id: int) -> bool:
        if user_id == ADMIN_ID:
            return True
        now = time.time()
        tokens, last_time = self.buckets.get(user_id, (self.capacity, now))
        elapsed = now - last_time
        tokens = min(self.capacity, tokens + elapsed * self.rate)
        if tokens >= 1.0:
            self.buckets[user_id] = (tokens - 1.0, now)
            return True
        self.buckets[user_id] = (tokens, now)
        # Opportunistic cleanup: prevent unbounded bucket growth (DoS-safe)
        if len(self.buckets) > 5000:
            cutoff = now - 600.0
            stale = [k for k, (_, t) in self.buckets.items() if t < cutoff]
            for k in stale:
                del self.buckets[k]
        return False

rate_limiter = TokenBucketRateLimiter(rate=5.0, capacity=10.0)

# --- Secrets Sanitizer ---
SECRETS_TO_SANITIZE: List[str] = [
    TELEGRAM_BOT_TOKEN,
    ROUTER_API_KEY,
    TINYFISH_API_KEY,
    ALLRATESTODAY_API_KEY,
    GITHUB_TOKEN,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_ACCOUNT_ID,
]

def sanitize_output(text: str) -> str:
    sanitized = text
    for sec in SECRETS_TO_SANITIZE:
        if sec and len(str(sec)) > 3:
            sanitized = sanitized.replace(str(sec), "[\u0645\u062d\u0631\u0645\u0627\u0646\u0647]")
    return sanitized

# --- AST Python Security ---
FORBIDDEN_ATTRIBUTES: Set[str] = {
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__code__", "__closure__", "__builtins__", "__import__",
    "__dict__", "__module__", "__qualname__", "f_globals", "f_locals"
}

FORBIDDEN_CALLS: Set[str] = {
    "__import__", "eval", "exec", "compile", "open", "input",
    "breakpoint", "help", "exit", "quit"
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
        self.generic_visit(node)

    def visit_Call(self, node):
        # Only real call expressions are dangerous; bare name mentions
        # (variables, f-string text, attribute bases) are harmless.
        func = node.func
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
            self.violations.append(f"Function call '{func.id}' forbidden.")
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
