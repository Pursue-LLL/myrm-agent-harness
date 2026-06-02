"""Unit tests for trigger types, serialization, and security utilities."""

from __future__ import annotations

import re

import pytest

from myrm_agent_harness.toolkits.cron.triggers import (
    EventTrigger,
    SystemEventTrigger,
    TriggerConfig,
    WebhookTrigger,
    dict_to_trigger_config,
    generate_webhook_path,
    generate_webhook_secret,
    is_private_url,
    trigger_config_to_dict,
    validate_regex_pattern,
    validate_webhook_secret,
)

# ---------------------------------------------------------------------------
# Security utilities
# ---------------------------------------------------------------------------


class TestValidateWebhookSecret:
    def test_matching(self) -> None:
        assert validate_webhook_secret("secret123", "secret123") is True

    def test_non_matching(self) -> None:
        assert validate_webhook_secret("secret123", "wrong") is False

    def test_empty_strings(self) -> None:
        assert validate_webhook_secret("", "") is True

    def test_timing_safe(self) -> None:
        assert validate_webhook_secret("abc", "abx") is False


class TestIsPrivateUrl:
    def test_localhost(self) -> None:
        assert is_private_url("http://localhost:8080/hook") is True

    def test_loopback(self) -> None:
        assert is_private_url("http://127.0.0.1/hook") is True

    def test_no_hostname(self) -> None:
        assert is_private_url("not-a-url") is True

    def test_ipv6_loopback(self) -> None:
        assert is_private_url("http://[::1]:8080/hook") is True

    def test_zero_address(self) -> None:
        assert is_private_url("http://0.0.0.0:8080/hook") is True


class TestValidateRegexPattern:
    def test_valid_pattern(self) -> None:
        result = validate_regex_pattern(r"\d+")
        assert isinstance(result, re.Pattern)

    def test_too_large(self) -> None:
        with pytest.raises(ValueError, match="too large"):
            validate_regex_pattern("a" * 100_000, max_bytes=1000)

    def test_complex_pattern(self) -> None:
        result = validate_regex_pattern(r"(error|warn)\s*:\s*\w+")
        assert result.search("error: timeout")

    def test_unicode_pattern(self) -> None:
        result = validate_regex_pattern(r"告警")
        assert result.search("系统告警通知")


# ---------------------------------------------------------------------------
# Webhook path / secret generation
# ---------------------------------------------------------------------------


class TestWebhookGeneration:
    def test_path_uniqueness(self) -> None:
        paths = {generate_webhook_path() for _ in range(10)}
        assert len(paths) == 10

    def test_path_hex_format(self) -> None:
        path = generate_webhook_path()
        int(path, 16)

    def test_secret_length(self) -> None:
        secret = generate_webhook_secret()
        assert len(secret) == 64


# ---------------------------------------------------------------------------
# TriggerConfig serialization round-trip
# ---------------------------------------------------------------------------


class TestTriggerConfigSerialization:
    def test_none_input(self) -> None:
        assert trigger_config_to_dict(None) is None
        assert dict_to_trigger_config(None) is None

    def test_empty_config(self) -> None:
        tc = TriggerConfig()
        assert trigger_config_to_dict(tc) is None

    def test_webhooks_round_trip(self) -> None:
        tc = TriggerConfig(
            webhooks=(WebhookTrigger(path="abc", secret="s1"),),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.webhooks) == 1
        assert restored.webhooks[0].path == "abc"
        assert restored.webhooks[0].secret == "s1"

    def test_events_round_trip(self) -> None:
        tc = TriggerConfig(
            events=(
                EventTrigger(pattern=r"\d+", channel="telegram"),
                EventTrigger(pattern="error"),
            ),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.events) == 2
        assert restored.events[0].pattern == r"\d+"
        assert restored.events[0].channel == "telegram"
        assert restored.events[1].channel is None

    def test_system_events_round_trip(self) -> None:
        tc = TriggerConfig(
            system_events=(
                SystemEventTrigger(
                    source="github",
                    event_type="push",
                    filters={"ref": "refs/heads/main"},
                ),
            ),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.system_events) == 1
        se = restored.system_events[0]
        assert se.source == "github"
        assert se.event_type == "push"
        assert se.filters == {"ref": "refs/heads/main"}

    def test_mixed_round_trip(self) -> None:
        tc = TriggerConfig(
            webhooks=(WebhookTrigger(path="p1"),),
            events=(EventTrigger(pattern="test"),),
            system_events=(SystemEventTrigger(source="sentry", event_type="alert"),),
        )
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.webhooks) == 1
        assert len(restored.events) == 1
        assert len(restored.system_events) == 1

    def test_empty_dict_returns_none(self) -> None:
        assert dict_to_trigger_config({}) is None

    def test_webhook_without_secret(self) -> None:
        tc = TriggerConfig(webhooks=(WebhookTrigger(path="x"),))
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert restored.webhooks[0].secret is None


# ---------------------------------------------------------------------------
# TriggerConfig immutability
# ---------------------------------------------------------------------------


class TestTriggerConfigImmutability:
    def test_frozen(self) -> None:
        tc = TriggerConfig(events=(EventTrigger(pattern="test"),))
        with pytest.raises(AttributeError):
            tc.events = ()  # type: ignore[misc]

    def test_event_trigger_frozen(self) -> None:
        et = EventTrigger(pattern="test")
        with pytest.raises(AttributeError):
            et.pattern = "other"  # type: ignore[misc]
