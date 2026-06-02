from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.llms.rate_limit.parser import (
    _parse_reset_time,
    parse_rate_limit_headers,
)


def test_parse_reset_time():
    # OpenAI formats
    assert _parse_reset_time("6m0s") == 360.0
    assert _parse_reset_time("1s") == 1.0
    assert _parse_reset_time("2ms") == 0.002
    assert _parse_reset_time("1h2m3s") == 3723.0

    # Anthropic ISO 8601 format
    # Mock time.time() to a fixed value for testing ISO 8601
    with patch("time.time", return_value=1704067200.0):  # 2024-01-01T00:00:00Z
        assert _parse_reset_time("2024-01-01T00:00:10Z") == 10.0
        assert _parse_reset_time("2024-01-01T00:00:00Z") == 0.0
        assert _parse_reset_time("2023-12-31T23:59:50Z") == 0.0  # Past time should be 0

    # Plain float formats
    assert _parse_reset_time("10.5") == 10.5
    assert _parse_reset_time(10.5) == 10.5

    # Unix timestamp (large float)
    with patch("time.time", return_value=1000000000.0):
        assert _parse_reset_time("1000000010.0") == 10.0
        assert _parse_reset_time("999999990.0") == 0.0

    # Invalid formats
    assert _parse_reset_time(None) is None
    assert _parse_reset_time("") is None
    assert _parse_reset_time("invalid") is None


def test_parse_rate_limit_headers_openai():
    headers = {
        "x-ratelimit-limit-requests": "5000",
        "x-ratelimit-remaining-requests": "4999",
        "x-ratelimit-reset-requests": "1s",
        "x-ratelimit-limit-tokens": "160000",
        "x-ratelimit-remaining-tokens": "159000",
        "x-ratelimit-reset-tokens": "6m0s",
    }

    state = parse_rate_limit_headers(headers, "openai", "gpt-4")
    assert state is not None
    assert state.provider == "openai"
    assert state.model == "gpt-4"

    assert state.rpm is not None
    assert state.rpm.limit == 5000
    assert state.rpm.remaining == 4999
    assert state.rpm.reset_seconds == 1.0

    assert state.tpm is not None
    assert state.tpm.limit == 160000
    assert state.tpm.remaining == 159000
    assert state.tpm.reset_seconds == 360.0

    assert state.rph is None
    assert state.tph is None

    assert state.highest_usage_pct == pytest.approx(
        1000 / 160000
    )  # (160000 - 159000) / 160000


def test_parse_rate_limit_headers_anthropic():
    # Mock time for Anthropic ISO 8601 format
    with patch("time.time", return_value=1704067200.0):  # 2024-01-01T00:00:00Z
        headers = {
            "anthropic-ratelimit-requests-limit": "1000",
            "anthropic-ratelimit-requests-remaining": "900",
            "anthropic-ratelimit-requests-reset": "2024-01-01T00:00:10Z",
            "anthropic-ratelimit-tokens-limit": "40000",
            "anthropic-ratelimit-tokens-remaining": "30000",
            "anthropic-ratelimit-tokens-reset": "2024-01-01T00:01:00Z",
        }

        state = parse_rate_limit_headers(headers, "anthropic", "claude-3")
        assert state is not None
        assert state.provider == "anthropic"
        assert state.model == "claude-3"

        assert state.rpm is not None
        assert state.rpm.limit == 1000
        assert state.rpm.remaining == 900
        assert state.rpm.reset_seconds == 10.0

        assert state.tpm is not None
        assert state.tpm.limit == 40000
        assert state.tpm.remaining == 30000
        assert state.tpm.reset_seconds == 60.0


def test_parse_rate_limit_headers_empty():
    state = parse_rate_limit_headers({}, "openai", "gpt-4")
    assert state is None
