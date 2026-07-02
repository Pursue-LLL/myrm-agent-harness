"""Unit tests for trigger types, serialization, and security utilities."""

from __future__ import annotations

import re

import pytest

from myrm_agent_harness.toolkits.cron.triggers import (
    EventTrigger,
    PollTrigger,
    StreamProtocol,
    StreamTrigger,
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

    def test_polls_round_trip(self) -> None:
        tc = TriggerConfig(
            polls=(
                PollTrigger(url="https://api.example.com/data", json_path="$.count", interval_seconds=120),
            ),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        assert "polls" in d
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.polls) == 1
        assert restored.polls[0].url == "https://api.example.com/data"
        assert restored.polls[0].json_path == "$.count"
        assert restored.polls[0].interval_seconds == 120
        assert restored.polls[0].change_detection is True

    def test_streams_round_trip(self) -> None:
        tc = TriggerConfig(
            streams=(
                StreamTrigger(
                    url="wss://stream.example.com/ws",
                    protocol=StreamProtocol.WS,
                    filter_json_path="$.data.price",
                    filter_regex=r"^\d{6,}",
                    headers={"Authorization": "Bearer token123"},
                ),
            ),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        assert "streams" in d
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.streams) == 1
        s = restored.streams[0]
        assert s.url == "wss://stream.example.com/ws"
        assert s.protocol == StreamProtocol.WS
        assert s.filter_json_path == "$.data.price"
        assert s.filter_regex == r"^\d{6,}"
        assert s.headers == {"Authorization": "Bearer token123"}

    def test_streams_sse_protocol(self) -> None:
        tc = TriggerConfig(
            streams=(StreamTrigger(url="https://api.example.com/events", protocol=StreamProtocol.SSE),),
        )
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert restored.streams[0].protocol == StreamProtocol.SSE

    def test_streams_minimal(self) -> None:
        tc = TriggerConfig(streams=(StreamTrigger(url="wss://example.com/ws"),))
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert restored.streams[0].filter_json_path is None
        assert restored.streams[0].filter_regex is None
        assert restored.streams[0].headers == {}

    def test_mixed_all_types(self) -> None:
        tc = TriggerConfig(
            webhooks=(WebhookTrigger(path="p1"),),
            events=(EventTrigger(pattern="test"),),
            system_events=(SystemEventTrigger(source="sentry", event_type="alert"),),
            polls=(PollTrigger(url="https://api.example.com/data"),),
            streams=(StreamTrigger(url="wss://stream.example.com/ws"),),
        )
        d = trigger_config_to_dict(tc)
        assert d is not None
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.webhooks) == 1
        assert len(restored.events) == 1
        assert len(restored.system_events) == 1
        assert len(restored.polls) == 1
        assert len(restored.streams) == 1

    def test_only_polls_returns_config(self) -> None:
        tc = TriggerConfig(polls=(PollTrigger(url="https://example.com"),))
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.polls) == 1
        assert not restored.webhooks
        assert not restored.events

    def test_only_streams_returns_config(self) -> None:
        tc = TriggerConfig(streams=(StreamTrigger(url="wss://example.com/ws"),))
        d = trigger_config_to_dict(tc)
        restored = dict_to_trigger_config(d)
        assert restored is not None
        assert len(restored.streams) == 1
        assert not restored.webhooks
        assert not restored.polls


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

    def test_stream_trigger_frozen(self) -> None:
        st = StreamTrigger(url="wss://example.com/ws")
        with pytest.raises(AttributeError):
            st.url = "other"  # type: ignore[misc]

    def test_poll_trigger_frozen(self) -> None:
        pt = PollTrigger(url="https://example.com/api")
        with pytest.raises(AttributeError):
            pt.url = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# StreamTrigger / PollTrigger data model tests
# ---------------------------------------------------------------------------


class TestStreamTriggerModel:
    def test_defaults(self) -> None:
        st = StreamTrigger(url="wss://example.com")
        assert st.protocol == StreamProtocol.WS
        assert st.filter_json_path is None
        assert st.filter_regex is None
        assert st.headers == {}

    def test_sse_protocol(self) -> None:
        st = StreamTrigger(url="https://example.com/events", protocol=StreamProtocol.SSE)
        assert st.protocol == StreamProtocol.SSE

    def test_with_filters(self) -> None:
        st = StreamTrigger(
            url="wss://stream.binance.com/ws",
            filter_json_path="$.p",
            filter_regex=r"^\d{6,}",
        )
        assert st.filter_json_path == "$.p"
        assert st.filter_regex == r"^\d{6,}"

    def test_with_headers(self) -> None:
        st = StreamTrigger(
            url="wss://api.example.com/ws",
            headers={"Authorization": "Bearer xxx", "X-Custom": "val"},
        )
        assert len(st.headers) == 2


class TestPollTriggerModel:
    def test_defaults(self) -> None:
        pt = PollTrigger(url="https://example.com/api")
        assert pt.json_path is None
        assert pt.interval_seconds == 300
        assert pt.change_detection is True

    def test_custom_interval(self) -> None:
        pt = PollTrigger(url="https://example.com", interval_seconds=60)
        assert pt.interval_seconds == 60

    def test_no_change_detection(self) -> None:
        pt = PollTrigger(url="https://example.com", change_detection=False)
        assert pt.change_detection is False


class TestStreamProtocolEnum:
    def test_ws_value(self) -> None:
        assert StreamProtocol.WS.value == "ws"

    def test_sse_value(self) -> None:
        assert StreamProtocol.SSE.value == "sse"

    def test_from_string(self) -> None:
        assert StreamProtocol("ws") == StreamProtocol.WS
        assert StreamProtocol("sse") == StreamProtocol.SSE
