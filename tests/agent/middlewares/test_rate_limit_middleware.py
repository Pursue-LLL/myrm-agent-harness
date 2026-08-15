"""Tests for the proactive rate-limit middleware.

Covers provider header detection, min-recovery computation, proactive
throttling (all-providers-exhausted), response header parsing, SSE emission,
and warning debounce logic.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.middlewares.rate_limit import (
    MAX_PROACTIVE_WAIT,
    RateLimitMiddleware,
    _compute_min_recovery_seconds,
    _detect_provider_from_headers,
)
from myrm_agent_harness.toolkits.llms.rate_limit.types import (
    RateLimitBucket,
    RateLimitState,
)


def _state(
    *,
    rpm_remaining: int | None = None,
    tpm_remaining: int | None = None,
    rpm_reset: float = 30.0,
    tpm_reset: float = 60.0,
    updated_at: float | None = None,
) -> RateLimitState:
    buckets: dict[str, RateLimitBucket | None] = {
        "rpm": None,
        "rph": None,
        "tpm": None,
        "tph": None,
    }
    now = time.time() if updated_at is None else updated_at
    if rpm_remaining is not None:
        buckets["rpm"] = RateLimitBucket(limit=10, remaining=rpm_remaining, reset_seconds=rpm_reset, updated_at=now)
    if tpm_remaining is not None:
        buckets["tpm"] = RateLimitBucket(limit=1000, remaining=tpm_remaining, reset_seconds=tpm_reset, updated_at=now)
    return RateLimitState(
        provider="openai",
        model="gpt-test",
        rpm=buckets["rpm"],
        rph=buckets["rph"],
        tpm=buckets["tpm"],
        tph=buckets["tph"],
    )


class TestDetectProvider:
    def test_anthropic_header(self) -> None:
        assert _detect_provider_from_headers({"anthropic-ratelimit-requests-limit": "10"}) == "anthropic"

    def test_case_insensitive_anthropic(self) -> None:
        assert _detect_provider_from_headers({"Anthropic-RateLimit-Requests-Limit": "10"}) == "anthropic"

    def test_openai_headers(self) -> None:
        assert _detect_provider_from_headers({"x-ratelimit-limit-requests": "10"}) == "openai"

    def test_empty_headers(self) -> None:
        assert _detect_provider_from_headers({}) == "openai"


class TestComputeMinRecovery:
    def test_rpm_exhausted_returns_remaining(self) -> None:
        state = _state(rpm_remaining=0, rpm_reset=30.0)
        expected = state.rpm.remaining_seconds_now  # type: ignore[union-attr]
        assert _compute_min_recovery_seconds(state) == pytest.approx(expected)

    def test_tpm_exhausted_returns_remaining(self) -> None:
        state = _state(tpm_remaining=999, tpm_reset=15.0)
        expected = state.tpm.remaining_seconds_now  # type: ignore[union-attr]
        assert _compute_min_recovery_seconds(state) == pytest.approx(expected)

    def test_min_across_buckets(self) -> None:
        state = _state(rpm_remaining=0, rpm_reset=30.0, tpm_remaining=999, tpm_reset=5.0)
        expected = state.tpm.remaining_seconds_now  # type: ignore[union-attr]
        assert _compute_min_recovery_seconds(state) == pytest.approx(expected)

    def test_elapsed_seconds_subtracted(self) -> None:
        state = _state(rpm_remaining=0, rpm_reset=30.0, updated_at=time.time() - 10.0)
        assert _compute_min_recovery_seconds(state) == pytest.approx(20.0, abs=1.0)

    def test_all_healthy_returns_zero(self) -> None:
        state = _state(rpm_remaining=5, tpm_remaining=1000)
        assert _compute_min_recovery_seconds(state) == 0.0

    def test_all_exhausted_but_expired_returns_zero(self) -> None:
        state = _state(rpm_remaining=0, rpm_reset=1.0, updated_at=time.time() - 5.0)
        assert _compute_min_recovery_seconds(state) == 0.0


class TestMiddlewareBasics:
    def test_init_defaults(self) -> None:
        mw = RateLimitMiddleware()
        assert mw.warning_threshold_pct == 0.8
        assert mw.debounce_seconds == 300.0
        assert mw._last_warning_times == {}

    def test_init_custom_threshold(self) -> None:
        mw = RateLimitMiddleware(warning_threshold_pct=0.5, debounce_seconds=60.0)
        assert mw.warning_threshold_pct == 0.5
        assert mw.debounce_seconds == 60.0

    def test_wrap_model_call_passthrough(self) -> None:
        mw = RateLimitMiddleware()
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        handler = MagicMock(return_value="response")
        assert mw.wrap_model_call(request, handler) == "response"
        handler.assert_called_once_with(request)


class TestAwrapModelCall:
    @pytest.mark.asyncio
    async def test_no_states_skips_throttle(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker):
            response = await mw.awrap_model_call(request, handler)
        assert response is not None
        handler.assert_awaited_once_with(request)

    @pytest.mark.asyncio
    async def test_healthy_states_skip_sleep(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        healthy = _state(rpm_remaining=5, tpm_remaining=1000)
        tracker.get_all_states.return_value = [healthy]
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            await mw.awrap_model_call(request, handler)
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_exhausted_sleeps_and_emits(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        exhausted = _state(rpm_remaining=0, rpm_reset=30.0)
        tracker.get_all_states.return_value = [exhausted]
        sink = MagicMock()
        sink.emit = AsyncMock()
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink",
                return_value=sink,
            ),
        ):
            await mw.awrap_model_call(request, handler)
        mock_sleep.assert_awaited_once()
        args = mock_sleep.await_args.args
        assert args[0] == pytest.approx(min(30.0, MAX_PROACTIVE_WAIT), abs=1.0)
        assert sink.emit.await_args.args[0]["type"] == "rate_limit_throttled"

    @pytest.mark.asyncio
    async def test_partial_exhausted_does_not_sleep(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        healthy = _state(rpm_remaining=5, tpm_remaining=1000)
        exhausted = _state(rpm_remaining=0, rpm_reset=30.0)
        tracker.get_all_states.return_value = [healthy, exhausted]
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            await mw.awrap_model_call(request, handler)
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sink_emit_failure_is_suppressed(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        exhausted = _state(rpm_remaining=0, rpm_reset=30.0)
        tracker.get_all_states.return_value = [exhausted]
        sink = MagicMock()
        sink.emit = AsyncMock(side_effect=RuntimeError("sse down"))
        handler = AsyncMock(return_value=ModelResponse(result=[]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink",
                return_value=sink,
            ),
        ):
            await mw.awrap_model_call(request, handler)

    @pytest.mark.asyncio
    async def test_no_headers_skips_parse(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        ai_msg = AIMessage(content="hi")
        handler = AsyncMock(return_value=ModelResponse(result=[ai_msg]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.parse_rate_limit_headers") as mock_parse,
        ):
            await mw.awrap_model_call(request, handler)
        mock_parse.assert_not_called()

    @pytest.mark.asyncio
    async def test_headers_parse_and_update(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        tracker.update.return_value = True
        parsed = _state(rpm_remaining=5, tpm_remaining=1000)
        ai_msg = AIMessage(
            content="hi",
            response_metadata={"headers": {"x-ratelimit-limit-requests": "10"}, "model_name": "gpt-test"},
        )
        handler = AsyncMock(return_value=ModelResponse(result=[ai_msg]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        sink = MagicMock()
        sink.emit = AsyncMock()
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.parse_rate_limit_headers",
                return_value=parsed,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink",
                return_value=sink,
            ),
        ):
            await mw.awrap_model_call(request, handler)
        tracker.update.assert_called_once_with(parsed)
        emitted_types = [call.args[0]["type"] for call in sink.emit.await_args_list]
        assert "rate_limit_updated" in emitted_types

    @pytest.mark.asyncio
    async def test_update_returns_false_skips_emit(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        tracker.update.return_value = False
        parsed = _state(rpm_remaining=5, tpm_remaining=500)
        ai_msg = AIMessage(
            content="hi",
            response_metadata={"headers": {"x-ratelimit-limit-requests": "10"}, "model_name": "gpt-test"},
        )
        handler = AsyncMock(return_value=ModelResponse(result=[ai_msg]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        sink = MagicMock()
        sink.emit = AsyncMock()
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.parse_rate_limit_headers",
                return_value=parsed,
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.get_tool_progress_sink",
                return_value=sink,
            ),
        ):
            await mw.awrap_model_call(request, handler)
        sink.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_parse_error_is_caught(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        ai_msg = AIMessage(
            content="hi",
            response_metadata={"headers": {"x-ratelimit-limit-requests": "10"}},
        )
        handler = AsyncMock(return_value=ModelResponse(result=[ai_msg]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch(
                "myrm_agent_harness.agent.middlewares.rate_limit.parse_rate_limit_headers",
                side_effect=ValueError("bad headers"),
            ),
        ):
            response = await mw.awrap_model_call(request, handler)
        assert response is not None

    @pytest.mark.asyncio
    async def test_non_ai_message_skips_parse(self) -> None:
        mw = RateLimitMiddleware()
        tracker = MagicMock()
        tracker.get_all_states.return_value = []
        handler = AsyncMock(return_value=ModelResponse(result=[HumanMessage(content="hi")]))
        request = ModelRequest(model=MagicMock(), messages=[HumanMessage(content="hi")])
        with (
            patch("myrm_agent_harness.agent.middlewares.rate_limit.RateLimitTracker.get", return_value=tracker),
            patch("myrm_agent_harness.agent.middlewares.rate_limit.parse_rate_limit_headers") as mock_parse,
        ):
            await mw.awrap_model_call(request, handler)
        mock_parse.assert_not_called()


class TestCheckAndEmitWarning:
    @pytest.mark.asyncio
    async def test_high_usage_emits_warning(self) -> None:
        mw = RateLimitMiddleware()
        state = _state(rpm_remaining=1, tpm_remaining=100)
        sink = MagicMock()
        sink.emit = AsyncMock()
        await mw._check_and_emit_warning(state, sink)
        assert ("openai", "gpt-test") in mw._last_warning_times
        emitted = [call.args[0]["type"] for call in sink.emit.await_args_list]
        assert "rate_limit_warning" in emitted

    @pytest.mark.asyncio
    async def test_debounced_within_window(self) -> None:
        mw = RateLimitMiddleware(debounce_seconds=3600.0)
        state = _state(rpm_remaining=1, tpm_remaining=100)
        sink = MagicMock()
        sink.emit = AsyncMock()
        await mw._check_and_emit_warning(state, sink)
        await mw._check_and_emit_warning(state, sink)
        assert sink.emit.await_count == 1

    @pytest.mark.asyncio
    async def test_emit_failure_is_caught(self) -> None:
        mw = RateLimitMiddleware()
        state = _state(rpm_remaining=1, tpm_remaining=100)
        sink = MagicMock()
        sink.emit = AsyncMock(side_effect=RuntimeError("boom"))
        await mw._check_and_emit_warning(state, sink)
        assert ("openai", "gpt-test") in mw._last_warning_times
