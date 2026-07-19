"""Inline interactive UI (A2UI) client surface capability gate.

[INPUT]
- agent.security.channel_presets::ChannelType, resolve_channel_type (POS: channel security SSOT)

[OUTPUT]
- ClientSurface: web / tauri / headless rendering surfaces
- resolve_client_surface: normalize request surface strings
- supports_inline_interactive_ui: whether A2UI tools may mount for a session

[POS]
Harness-layer SSOT for inline A2UI availability. Server mount gates and active_tool_groups
derive from this helper — IM/cron/headless sessions must not load render_ui tokens.
"""

from __future__ import annotations

from enum import StrEnum, unique

from myrm_agent_harness.agent.security.channel_presets import ChannelType


@unique
class ClientSurface(StrEnum):
    """Client environments that can render inline A2UI surfaces."""

    WEB = "web"
    TAURI = "tauri"
    HEADLESS = "headless"


_INLINE_UI_SURFACES: frozenset[ClientSurface] = frozenset({ClientSurface.WEB, ClientSurface.TAURI})


def resolve_client_surface(value: str | None) -> ClientSurface | None:
    """Map a request/client surface string to ``ClientSurface``, or None when omitted."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    try:
        return ClientSurface(normalized)
    except ValueError:
        return None


def supports_inline_interactive_ui(
    channel_type: ChannelType,
    *,
    client_surface: ClientSurface | None = None,
) -> bool:
    """Return True when the session can render and interact with inline A2UI."""
    if channel_type != ChannelType.WEB_CHAT:
        return False
    if client_surface is None:
        return True
    return client_surface in _INLINE_UI_SURFACES
