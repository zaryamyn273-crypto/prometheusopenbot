from src.ui import admin_panel
from src.ui.admin_panel import (
    get_start_keyboard,
    get_admin_panel_keyboard,
    get_admin_groups_keyboard,
    get_admin_banned_keyboard,
    get_admin_memory_keyboard,
    get_tools_keyboard,
    get_network_tools_keyboard,
    get_weather_quick_keyboard,
    get_banned_users_text_async,
    get_memory_text_async,
    get_system_status_text_async,
    get_connected_groups_text_async,
    get_recent_d1_messages_text_async
)

# Backwards compatibility wrappers
def get_system_status_text() -> str:
    from src.tools import system
    return system.admin_system_diagnostics()

def get_memory_text() -> str:
    from src.core import database
    mems = database.get_all_admin_memories()
    if not mems:
        return "🧠 *حافظه دائمی سیستم*:\n\nهیچ دستور دائمی ثبت نشده است."
    return "🧠 *قوانین و دستورات دائمی فعال*:\n\n" + "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems))

def get_banned_users_text() -> str:
    from src.core import database
    banned = database.get_banned_users()
    if not banned:
        return "🚫 *کاربران مسدود*: هیچ کاربری در لیست سیاه وجود ندارد."
    return f"🚫 *لیست سیاه ({len(banned)} کاربر)*:\n\n" + "\n".join(f"• `{uid}`" for uid in banned)

__all__ = [
    "admin_panel",
    "get_start_keyboard",
    "get_admin_panel_keyboard",
    "get_admin_groups_keyboard",
    "get_admin_banned_keyboard",
    "get_admin_memory_keyboard",
    "get_tools_keyboard",
    "get_network_tools_keyboard",
    "get_weather_quick_keyboard",
    "get_banned_users_text_async",
    "get_memory_text_async",
    "get_system_status_text_async",
    "get_connected_groups_text_async",
    "get_recent_d1_messages_text_async",
    "get_system_status_text",
    "get_memory_text",
    "get_banned_users_text"
]
