import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.middlewares.rate_limit import (
    MAX_PROACTIVE_WAIT,
    RateLimitMiddleware,
    _compute_min_recovery_seconds,
    _detect_provider_from_headers,
)
from myrm_agent_harness.toolkits.llms.rate_limit.tracker import RateLimitTracker
from myrm_agent_harness.toolkits.llms.rate_limit.types import (
    RateLimitBucket,
    RateLimitState,
)


def _make_request() -> ModelRequest:
    return ModelRequest(messages=[], model=MagicMock())


@pytest.fixture(autouse=True)
def reset_tracker():
    """Reset the RateLimitTracker singleton before each test."""
    RateLimitTracker._instance = None
    yield
    RateLimitTracker._instance = None


# ──────────────────────────────────────────────────────────────────────
#  _detect_provider_from_headers
# ──────────────────────────────────────────────────────────────────────


class TestDetectProviderFromHeaders:
    def test_anthropic_headers(self):
        headers = {
            "anthropic-ratelimit-requests-limit": "100",
            "content-type": "application/json",
        }
        assert _detect_provider_from_headers(headers) == "anthropic"

    def test_openai_standard_headers(self):
        headers = {
            "x-ratelimit-limit-requests": "5000",
            "content-type": "application/json",
        }
        assert _detect_provider_from_headers(headers) == "openai"

    def test_deepseek_headers(self):
        headers = {
            "x-ratelimit-limit-requests": "200",
            "x-ratelimit-remaining-requests": "199",
        }
        assert _detect_provider_from_headers(headers) == "openai"

    def test_empty_headers(self):
        assert _detect_provider_from_headers({}) == "openai"

    def test_no_ratelimit_headers(self):
        headers = {"content-type": "text/plain", "server": "nginx"}
        assert _detect_provider_from_headers(headers) == "openai"

    def test_mixed_headers_anthropic_wins(self):
        headers = {
            "anthropic-ratelimit-requests-limit": "100",
            "x-ratelimit-limit-requests": "5000",
        }
        assert _detect_provider_from_headers(headers) == "anthropic"

    def test_case_insensitive_anthropic(self):
        headers = {"Anthropic-Ratelimit-Requests-Limit": "100"}
        assert _detect_provider_from_headers(headers) == "anthropic"


# ──────────────────────────────────────────────────────────────────────
#  _compute_min_recovery_seconds
# ──────────────────────────────────────────────────────────────────────


class TestComputeMinRecoverySeconds:
    def test_single_exhausted_bucket(self):
        state = RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=5.0, updated_at=time.time()
            ),
        )
        result = _compute_min_recovery_seconds(state)
        assert 4.0 < result <= 5.0

    def test_multiple_exhausted_buckets_returns_min(self):
        now = time.time()
        state = RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=30.0, updated_at=now
            ),
            tpm=RateLimitBucket(
                limit=100000, remaining=0, reset_seconds=5.0, updated_at=now
            ),
        )
        result = _compute_min_recovery_seconds(state)
        assert 4.0 < result <= 5.0

    def test_no_exhausted_buckets(self):
        state = RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=5, reset_seconds=60.0, updated_at=time.time()
            ),
        )
        assert _compute_min_recovery_seconds(state) == 0.0

    def test_all_buckets_none(self):
        state = RateLimitState(provider="openai", model="gpt-4")
        assert _compute_min_recovery_seconds(state) == 0.0

    def test_expired_reset_returns_zero(self):
        state = RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=1.0, updated_at=time.time() - 10.0
            ),
        )
        assert _compute_min_recovery_seconds(state) == 0.0


# ──────────────────────────────────────────────────────────────────────
#  Proactive throttling
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proactive_throttling_single_provider():
    """Single exhausted provider triggers sleep."""
    tracker = RateLimitTracker.get()
    tracker.update(
        RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=0.5, updated_at=time.time()
            ),
        )
    )

    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await middleware.awrap_model_call(request, handler)
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] == pytest.approx(0.5, abs=0.1)
        handler.assert_called_once_with(request)


@pytest.mark.asyncio
async def test_no_throttle_when_one_provider_healthy():
    """With two providers, only one exhausted => no sleep."""
    tracker = RateLimitTracker.get()
    tracker.update(
        RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=30.0, updated_at=time.time()
            ),
        )
    )
    tracker.update(
        RateLimitState(
            provider="anthropic",
            model="claude-3",
            rpm=RateLimitBucket(
                limit=50, remaining=40, reset_seconds=60.0, updated_at=time.time()
            ),
        )
    )

    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await middleware.awrap_model_call(request, handler)
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_throttle_all_providers_exhausted_uses_min_wait():
    """With all providers exhausted, sleep the shortest recovery time."""
    tracker = RateLimitTracker.get()
    now = time.time()
    tracker.update(
        RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=30.0, updated_at=now
            ),
        )
    )
    tracker.update(
        RateLimitState(
            provider="anthropic",
            model="claude-3",
            rpm=RateLimitBucket(
                limit=50, remaining=0, reset_seconds=5.0, updated_at=now
            ),
        )
    )

    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await middleware.awrap_model_call(request, handler)
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] == pytest.approx(5.0, abs=0.5)


@pytest.mark.asyncio
async def test_throttle_capped_at_max_proactive_wait():
    """Sleep is capped at MAX_PROACTIVE_WAIT even if recovery is longer."""
    tracker = RateLimitTracker.get()
    tracker.update(
        RateLimitState(
            provider="openai",
            model="gpt-4",
            rph=RateLimitBucket(
                limit=100, remaining=0, reset_seconds=3600.0, updated_at=time.time()
            ),
        )
    )

    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await middleware.awrap_model_call(request, handler)
        mock_sleep.assert_called_once()
        assert mock_sleep.call_args[0][0] == MAX_PROACTIVE_WAIT


@pytest.mark.asyncio
async def test_throttle_emits_rate_limit_throttled_event():
    """When all providers exhausted, emit rate_limit_throttled SSE event."""
    tracker = RateLimitTracker.get()
    tracker.update(
        RateLimitState(
            provider="openai",
            model="gpt-4",
            rpm=RateLimitBucket(
                limit=10, remaining=0, reset_seconds=5.0, updated_at=time.time()
            ),
        )
    )

    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch(
            "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink"
        ) as mock_get_sink,
    ):
        mock_sink = AsyncMock()
        mock_get_sink.return_value = mock_sink
        await middleware.awrap_model_call(request, handler)

        throttled_calls = [
            c
            for c in mock_sink.emit.call_args_list
            if c[0][0]["type"] == "rate_limit_throttled"
        ]
        assert len(throttled_calls) == 1
        assert "wait_seconds" in throttled_calls[0][0][0]["data"]


@pytest.mark.asyncio
async def test_no_throttle_with_empty_tracker():
    """No tracked states => no sleep."""
    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[AIMessage(content="test")]))

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await middleware.awrap_model_call(request, handler)
        mock_sleep.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
#  Header parsing & provider detection
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_header_parsing_and_tracker_update():
    middleware = RateLimitMiddleware()
    request = _make_request()

    headers = {
        "x-ratelimit-limit-requests": "5000",
        "x-ratelimit-remaining-requests": "4999",
        "x-ratelimit-reset-requests": "1s",
    }
    response_msg = AIMessage(
        content="test", response_metadata={"headers": headers, "model_name": "gpt-4"}
    )
    handler = AsyncMock(return_value=ModelResponse(result=[response_msg]))

    with patch(
        "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink"
    ) as mock_get_sink:
        mock_sink = AsyncMock()
        mock_get_sink.return_value = mock_sink

        await middleware.awrap_model_call(request, handler)

        tracker = RateLimitTracker.get()
        state = tracker.get_state("openai", "gpt-4")
        assert state is not None
        assert state.rpm.limit == 5000
        assert state.rpm.remaining == 4999

        mock_sink.emit.assert_called_once()
        assert mock_sink.emit.call_args[0][0]["type"] == "rate_limit_updated"


@pytest.mark.asyncio
async def test_anthropic_header_detection():
    """Anthropic headers are correctly detected and parsed."""
    middleware = RateLimitMiddleware()
    request = _make_request()

    headers = {
        "anthropic-ratelimit-requests-limit": "100",
        "anthropic-ratelimit-requests-remaining": "99",
        "anthropic-ratelimit-requests-reset": "2025-01-01T00:01:00Z",
    }
    response_msg = AIMessage(
        content="test",
        response_metadata={"headers": headers, "model_name": "claude-3-sonnet"},
    )
    handler = AsyncMock(return_value=ModelResponse(result=[response_msg]))

    with patch(
        "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink"
    ) as mock_get_sink:
        mock_sink = AsyncMock()
        mock_get_sink.return_value = mock_sink

        await middleware.awrap_model_call(request, handler)

        tracker = RateLimitTracker.get()
        state = tracker.get_state("anthropic", "claude-3-sonnet")
        assert state is not None


@pytest.mark.asyncio
async def test_deepseek_model_uses_openai_provider():
    """Non-OpenAI/Anthropic model names with x-ratelimit headers are detected as openai format."""
    middleware = RateLimitMiddleware()
    request = _make_request()

    headers = {
        "x-ratelimit-limit-requests": "300",
        "x-ratelimit-remaining-requests": "299",
        "x-ratelimit-reset-requests": "1s",
    }
    response_msg = AIMessage(
        content="test",
        response_metadata={"headers": headers, "model_name": "deepseek-chat"},
    )
    handler = AsyncMock(return_value=ModelResponse(result=[response_msg]))

    with patch(
        "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink"
    ) as mock_get_sink:
        mock_sink = AsyncMock()
        mock_get_sink.return_value = mock_sink

        await middleware.awrap_model_call(request, handler)

        tracker = RateLimitTracker.get()
        state = tracker.get_state("openai", "deepseek-chat")
        assert state is not None
        assert state.rpm.limit == 300


# ──────────────────────────────────────────────────────────────────────
#  Warning emission
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warning_emission_with_debounce():
    middleware = RateLimitMiddleware(warning_threshold_pct=0.8, debounce_seconds=10.0)
    request = _make_request()

    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "10",
        "x-ratelimit-reset-requests": "10s",
    }
    response_msg = AIMessage(
        content="test", response_metadata={"headers": headers, "model_name": "gpt-4"}
    )
    handler = AsyncMock(return_value=ModelResponse(result=[response_msg]))

    with patch(
        "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink"
    ) as mock_get_sink:
        mock_sink = AsyncMock()
        mock_get_sink.return_value = mock_sink

        await middleware.awrap_model_call(request, handler)

        assert mock_sink.emit.call_count == 2
        calls = mock_sink.emit.call_args_list
        assert calls[0][0][0]["type"] == "rate_limit_updated"
        assert calls[1][0][0]["type"] == "rate_limit_warning"

        mock_sink.reset_mock()
        await middleware.awrap_model_call(request, handler)

        assert mock_sink.emit.call_count == 1
        assert mock_sink.emit.call_args[0][0]["type"] == "rate_limit_updated"


@pytest.mark.asyncio
async def test_no_headers_in_response():
    """Response without headers doesn't crash."""
    middleware = RateLimitMiddleware()
    request = _make_request()

    response_msg = AIMessage(content="test", response_metadata={})
    handler = AsyncMock(return_value=ModelResponse(result=[response_msg]))

    response = await middleware.awrap_model_call(request, handler)
    assert response.result[0].content == "test"


@pytest.mark.asyncio
async def test_empty_response_result():
    """Empty response.result doesn't crash."""
    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = AsyncMock(return_value=ModelResponse(result=[]))

    response = await middleware.awrap_model_call(request, handler)
    assert response.result == []


@pytest.mark.asyncio
async def test_sync_wrap_model_call_raises():
    """Synchronous wrap_model_call raises NotImplementedError."""
    middleware = RateLimitMiddleware()
    request = _make_request()
    handler = MagicMock()

    with pytest.raises(NotImplementedError):
        middleware.wrap_model_call(request, handler)
