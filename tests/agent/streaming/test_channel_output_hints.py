"""channel_output_hints.py unit tests

Covers:
- CHANNEL_OUTPUT_HINTS registry completeness and structure
- resolve_channel_output_hint(): lookup, normalization, edge cases
- Alignment with actual channel provider names
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from myrm_agent_harness.agent.streaming.channel_output_hints import (
    CHANNEL_OUTPUT_HINTS,
    resolve_channel_output_hint,
)

# ============================================================================
# CHANNEL_OUTPUT_HINTS registry structure
# ============================================================================


class TestChannelOutputHintsRegistry:
    def test_registry_is_non_empty(self) -> None:
        assert len(CHANNEL_OUTPUT_HINTS) >= 25

    def test_all_keys_are_lowercase(self) -> None:
        for key in CHANNEL_OUTPUT_HINTS:
            assert key == key.lower(), f"Key '{key}' is not lowercase"

    def test_all_values_start_with_output_format_tag(self) -> None:
        for key, hint in CHANNEL_OUTPUT_HINTS.items():
            assert "[Output Format]" in hint, f"'{key}' hint missing [Output Format] tag"

    def test_all_values_start_with_double_newline(self) -> None:
        for key, hint in CHANNEL_OUTPUT_HINTS.items():
            assert hint.startswith("\n\n"), f"'{key}' hint should start with \\n\\n"

    def test_hints_are_concise(self) -> None:
        """Each hint should be under 300 chars to minimize KV cache impact."""
        for key, hint in CHANNEL_OUTPUT_HINTS.items():
            assert len(hint) < 300, f"'{key}' hint too long ({len(hint)} chars)"

    def test_no_duplicate_values(self) -> None:
        values = list(CHANNEL_OUTPUT_HINTS.values())
        assert len(values) == len(set(values)), "Duplicate hint values found"


# ============================================================================
# resolve_channel_output_hint — basic lookup
# ============================================================================


class TestResolveChannelOutputHint:
    def test_known_channel_returns_hint(self) -> None:
        result = resolve_channel_output_hint("telegram")
        assert "[Output Format]" in result
        assert "Telegram" in result

    def test_web_chat_supports_full_markdown(self) -> None:
        result = resolve_channel_output_hint("web_chat")
        assert "Markdown" in result

    def test_whatsapp_is_plain_text(self) -> None:
        result = resolve_channel_output_hint("whatsapp")
        assert "plain text" in result.lower()

    def test_voice_is_conversational(self) -> None:
        result = resolve_channel_output_hint("voice")
        assert "text-to-speech" in result or "conversational" in result

    def test_cron_is_structured(self) -> None:
        result = resolve_channel_output_hint("cron")
        assert "scheduled job" in result


# ============================================================================
# resolve_channel_output_hint — normalization
# ============================================================================


class TestResolveNormalization:
    def test_case_insensitive(self) -> None:
        assert resolve_channel_output_hint("TELEGRAM") == resolve_channel_output_hint("telegram")

    def test_mixed_case(self) -> None:
        assert resolve_channel_output_hint("Telegram") == resolve_channel_output_hint("telegram")

    def test_strips_whitespace(self) -> None:
        assert resolve_channel_output_hint("  telegram  ") == resolve_channel_output_hint("telegram")

    def test_strips_leading_trailing(self) -> None:
        assert resolve_channel_output_hint("\ttelegram\n") == resolve_channel_output_hint("telegram")


# ============================================================================
# resolve_channel_output_hint — graceful fallback
# ============================================================================


class TestResolveFallback:
    def test_none_returns_empty(self) -> None:
        assert resolve_channel_output_hint(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert resolve_channel_output_hint("") == ""

    def test_unknown_channel_returns_empty(self) -> None:
        assert resolve_channel_output_hint("nonexistent_platform") == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert resolve_channel_output_hint("   ") == ""


# ============================================================================
# Alignment with channel providers
# ============================================================================


class TestProviderAlignment:
    """Verify all known channel provider names have corresponding hints."""

    KNOWN_PROVIDER_NAMES: ClassVar[list[str]] = [
        "telegram",
        "feishu",
        "dingtalk",
        "discord",
        "slack",
        "wecom",
        "teams",
        "matrix",
        "googlechat",
        "whatsapp",
        "mattermost",
        "zalo",
        "line",
        "onebot",
        "qq",
        "signal",
        "irc",
        "imessage",
        "email",
        "sms",
        "webhook",
        "voice",
        "wechat",
        "wechat_official",
        "wecom_aibot",
    ]

    @pytest.mark.parametrize("provider_name", KNOWN_PROVIDER_NAMES)
    def test_provider_has_hint(self, provider_name: str) -> None:
        hint = resolve_channel_output_hint(provider_name)
        assert hint != "", f"Provider '{provider_name}' has no channel output hint"


# ============================================================================
# KV Cache safety
# ============================================================================


class TestKVCacheSafety:
    def test_idempotent_same_channel(self) -> None:
        """Same channel must always produce identical output (KV cache stability)."""
        r1 = resolve_channel_output_hint("telegram")
        r2 = resolve_channel_output_hint("telegram")
        assert r1 == r2

    def test_different_channels_differ(self) -> None:
        """Different channels produce different hints."""
        telegram = resolve_channel_output_hint("telegram")
        whatsapp = resolve_channel_output_hint("whatsapp")
        assert telegram != whatsapp

    def test_result_is_string(self) -> None:
        assert isinstance(resolve_channel_output_hint("telegram"), str)
        assert isinstance(resolve_channel_output_hint(None), str)
