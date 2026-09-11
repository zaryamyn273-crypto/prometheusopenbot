from src.tools.registry import (
    register_tool,
    get_all_tool_definitions,
    get_tools_by_category,
    execute_registered_tool,
    REGISTRY
)

# Import all category submodules to automatically register their tools
from src.tools import financial
from src.tools import web_network
from src.tools import scientific
from src.tools import media
from src.tools import system
from src.tools import github
from src.tools import files
from src.tools import database as database_tools
from src.tools.admin import group_manager
from src.tools import dev
from src.tools import internal

# Convenient direct exposure of tool modules
file_reader = files

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
