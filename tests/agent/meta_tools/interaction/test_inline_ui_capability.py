"""Unit tests for inline A2UI surface capability gate."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.interaction.inline_ui_capability import (
    ClientSurface,
    resolve_client_surface,
    supports_inline_interactive_ui,
)
from myrm_agent_harness.agent.security.channel_presets import ChannelType


def test_supports_inline_on_web_chat_default_surface() -> None:
    assert supports_inline_interactive_ui(ChannelType.WEB_CHAT)


def test_supports_inline_on_web_chat_web_and_tauri() -> None:
    assert supports_inline_interactive_ui(ChannelType.WEB_CHAT, client_surface=ClientSurface.WEB)
    assert supports_inline_interactive_ui(ChannelType.WEB_CHAT, client_surface=ClientSurface.TAURI)


def test_rejects_im_and_cron_channels() -> None:
    assert not supports_inline_interactive_ui(ChannelType.IM)
    assert not supports_inline_interactive_ui(ChannelType.CRON)


def test_rejects_headless_surface_on_web_chat() -> None:
    assert not supports_inline_interactive_ui(
        ChannelType.WEB_CHAT,
        client_surface=ClientSurface.HEADLESS,
    )


def test_resolve_client_surface_normalizes_and_defaults_unknown() -> None:
    assert resolve_client_surface(None) is None
    assert resolve_client_surface("") is None
    assert resolve_client_surface("   ") is None
    assert resolve_client_surface("  TAURI ") is ClientSurface.TAURI
    assert resolve_client_surface("unknown-client") is None
