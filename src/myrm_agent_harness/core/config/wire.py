"""Wire protocol identifiers for LLM HTTP transports.

[INPUT]
- typing::Literal (POS: Python 类型标注标准库)

[OUTPUT]
- WireProtocol: Literal union of "chat_completions" | "responses" | "anthropic_messages"
- DEFAULT_WIRE_PROTOCOL: the fallback protocol when none is configured

[POS]
Framework-level SSOT for wire protocol identifiers. The harness selects completion vs
responses vs anthropic messages at the HTTP boundary; vendor-specific routing lives in the
business server layer.
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
