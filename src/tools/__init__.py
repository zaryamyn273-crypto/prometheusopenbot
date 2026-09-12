"""Lazy tool package: NOTHING heavy is imported at startup.

Importing every tool module eagerly (httpx pools, bs4, PIL, psutil, …) wastes
RAM/time on Railway and pulls full power for trivial turns. Tool modules are
imported on demand instead:

- ``from src.tools import financial`` (or any module below) still works —
  :func:`__getattr__` imports the real submodule on first use.
- Direct imports (``from src.tools.system import ban_user_tool``,
  ``from src.tools.admin.group_manager import …``) always worked and keep working.
- The registry (``src.tools.registry``) auto-loads owner modules when a tool
  is looked up, executed, or schema-filtered — see ``ensure_tool`` /
  ``ensure_categories`` / ``ensure_all`` there.
"""
import importlib

from src.tools.registry import (
    register_tool,
    get_all_tool_definitions,
    get_tools_by_category,
    execute_registered_tool,
    REGISTRY
)

# Attribute name -> submodule path (mirrors the old eager imports).
_LAZY_ATTRS = {
    "financial": "src.tools.financial",
    "web_network": "src.tools.web_network",
    "scientific": "src.tools.scientific",
    "media": "src.tools.media",
    "system": "src.tools.system",
    "github": "src.tools.github",
    "files": "src.tools.files",
    "database_tools": "src.tools.database",
    "dev": "src.tools.dev",
    "internal": "src.tools.internal",
    # Convenient direct exposure of tool modules
    "file_reader": "src.tools.files",
}


def __getattr__(name: str):
    path = _LAZY_ATTRS.get(name)
    if path is None:
        raise AttributeError(f"module 'src.tools' has no attribute {name!r}")
    return importlib.import_module(path)


__all__ = [
    "register_tool",
    "get_all_tool_definitions",
    "get_tools_by_category",
    "execute_registered_tool",
    "REGISTRY",
    "financial",
    "web_network",
    "scientific",
    "media",
    "system",
    "github",
    "files",
    "file_reader",
    "database_tools",
    "dev",
    "internal"
]
