from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import time

from .telemetry import StageTimer


@dataclass
class TurnContext:
    """
    Unified Execution Context for a Prometheus Message Turn.
    Flows through the pipeline stages, preserving telemetry, identities,
    sanitized inputs, tool outputs, and egress payloads.
    """
    # Telegram primitives
    update: Any
    message: Any
    user: Any
    chat: Any

    # Derived identities
    chat_id: int
    user_id: int
    user_name: str = ""
    username: str = ""
    chat_title: str = ""
    is_admin: bool = False
    is_private_chat: bool = False
    has_reply_context: bool = False
    replied_message: Optional[Any] = None

    # Text & Media inputs
    raw_text: str = ""
    clean_text: str = ""
    image_bytes: Optional[bytes] = None
    media_action: Optional[Dict[str, Any]] = None

    # Language resolution
    detected_lang: str = "fa"
    client_lang: str = "fa"
    target_lang: str = "fa"

    # Execution decisions
    is_fast_path: bool = False
    is_halted: bool = False
    halt_reason: str = ""
    bypass_reasoning: bool = False

    # Outputs
    response_text: str = ""
    extra_action: Optional[Dict[str, Any]] = None

    # Telemetry
    timer: StageTimer = field(default_factory=StageTimer)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def halt(self, reason: str = "", reply_text: str = ""):
        """Halt the pipeline immediately (e.g. rate-limit, ban, silent group filter)."""
        self.is_halted = True
        self.halt_reason = reason
        if reply_text:
            self.response_text = reply_text

    def set_fast_reply(self, reply_text: str, extra_action: Optional[Dict[str, Any]] = None):
        """Register a sub-millisecond fast-path reply and mark turn as resolved."""
        self.is_fast_path = True
        self.response_text = reply_text
        self.extra_action = extra_action
