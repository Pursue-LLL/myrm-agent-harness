"""Wire protocol identifiers for LLM HTTP transports.

Framework-level SSOT. Harness selects completion vs responses vs anthropic messages
at the HTTP boundary; vendor-specific routing lives in the business server layer.
"""

from typing import Literal

WireProtocol = Literal["chat_completions", "responses", "anthropic_messages"]

DEFAULT_WIRE_PROTOCOL: WireProtocol = "chat_completions"

RESPONSES_WIRE: WireProtocol = "responses"

ANTHROPIC_MESSAGES_WIRE: WireProtocol = "anthropic_messages"

__all__ = [
    "ANTHROPIC_MESSAGES_WIRE",
    "DEFAULT_WIRE_PROTOCOL",
    "RESPONSES_WIRE",
    "WireProtocol",
]
