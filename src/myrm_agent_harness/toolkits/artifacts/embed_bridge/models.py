"""[INPUT]
- None (pure domain model contract)

[OUTPUT]
- WidgetDisplayMode, HostContextSnapshot, HostBridgeMessage, EmbedSecurityPolicy, BridgeInjectedContext

[POS]
Harness framework layer contracts for Embeddable Agent Widget & Host Context Bridge (Item 41 P1).
Strictly under 140 lines. Zero `Any`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

WidgetDisplayMode = Literal[
    "floating_bubble",  # Floating trigger bubble in corner
    "slideout_drawer",  # Sliding drawer on right/left edge
    "inline_container", # Fixed container embedded inside host page layout
]


@dataclass(slots=True)
class HostContextSnapshot:
    origin: str
    current_url: str
    page_title: str = ""
    selected_text: str = ""
    form_fields: dict[str, str] = field(default_factory=dict)
    user_metadata: dict[str, str] = field(default_factory=dict)
    captured_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class HostBridgeMessage:
    action: Literal[
        "sync_context",
        "trigger_prompt",
        "resize_viewport",
        "toggle_widget",
        "close_widget",
        "ping",
        "pong",
    ]
    payload: dict[str, str] = field(default_factory=dict)
    timestamp_ms: float = field(default_factory=lambda: time.time() * 1000.0)
    origin: str = ""


@dataclass(slots=True)
class EmbedSecurityPolicy:
    allowed_origins: list[str] = field(default_factory=lambda: ["*"])
    require_token: bool = False
    auth_token: str | None = None
    allow_form_capture: bool = True
    allow_selection_capture: bool = True


@dataclass(slots=True)
class BridgeInjectedContext:
    session_id: str
    context_text: str
    snapshot: HostContextSnapshot
    injected_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)
