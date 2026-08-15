"""Tests for prefix cache preheat utility.

[INPUT]
- agent.context_management.preheat::preheat_prefix_cache (POS: Prefix cache preheat utility for agent init, post-compaction, and idle keep-alive.)
- agent.context_management.preheat::needs_explicit_preheat (POS: Prefix cache preheat utility for agent init, post-compaction, and idle keep-alive.)
- agent.context_management.preheat::schedule_init_preheat (POS: Prefix cache preheat utility for agent init, post-compaction, and idle keep-alive.)
- agent.context_management.preheat::CacheKeepAliveManager (POS: Prefix cache preheat utility for agent init, post-compaction, and idle keep-alive.)

[OUTPUT]
- Tests for provider detection, cache warming probe, init preheat scheduling, and idle keep-alive.

[POS]
Unit tests for preheat.py — provider detection, async cache warming, init preheat, and CacheKeepAliveManager.
"""

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.context_management.preheat import (
    _KEEPALIVE_INTERVAL_SECONDS,
    _MIN_PREHEAT_TOKENS,
    CacheKeepAliveManager,
    needs_explicit_preheat,
    preheat_prefix_cache,
    schedule_init_preheat,
)


def _mock_create_task(fake_task: MagicMock | None = None) -> MagicMock:
    """``loop.create_task`` mock that closes the passed coroutine.

    ``mgr.start()`` calls ``loop.create_task(mgr._loop(), name=...)``, producing
    a real coroutine. A bare MagicMock never awaits it, leaking an
    unawaited-coroutine RuntimeWarning at GC; closing it inside the side effect
    keeps tests clean.
    """
    def _create_task(coro: object, **kwargs: object) -> MagicMock:
        if asyncio.iscoroutine(coro):
            coro.close()
        return fake_task or MagicMock()

    return MagicMock(side_effect=_create_task)


class TestNeedsExplicitPreheat:
    """Tests for provider detection logic."""

    @pytest.mark.parametrize(
        ("model_name", "expected"),
        [
            ("anthropic/claude-3-5-sonnet", True),
            ("claude-3-opus", True),
            ("bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0", True),
            ("bedrock/us.anthropic.claude-3-7-sonnet-20250219-v1:0", True),
            ("vertex_ai/claude-3-5-sonnet@20241022", True),
            ("openrouter/anthropic/claude-3-opus", True),
            ("qwen-max", True),
            ("dashscope/qwen-turbo", True),
            ("openai/qwen-plus", True),
            ("gpt-4o", False),
            ("deepseek-v3", False),
            ("gemini-1.5-pro", False),
            ("", False),
        ],
    )
    def test_provider_detection(self, model_name: str, expected: bool) -> None:
        assert needs_explicit_preheat(model_name) == expected

    def test_case_insensitive(self) -> None:
        assert needs_explicit_preheat("Anthropic/Claude-3") is True
        assert needs_explicit_preheat("QWEN-MAX") is True


@pytest.mark.asyncio
class TestPreheatPrefixCache:
    """Tests for the async preheat_prefix_cache function."""

    async def test_skip_auto_cache_provider(self) -> None:
        llm = AsyncMock()
        messages = [MagicMock()]
        result = await preheat_prefix_cache(llm, messages, "gpt-4o")
        assert result is False
        llm.ainvoke.assert_not_called()

    async def test_skip_empty_messages(self) -> None:
        llm = AsyncMock()
        result = await preheat_prefix_cache(llm, [], "anthropic/claude-3")
        assert result is False
        llm.ainvoke.assert_not_called()

    async def test_successful_preheat_uses_max_tokens_zero(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock()
        messages = [MagicMock(), MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3-5-sonnet")
        assert result is True
        llm.ainvoke.assert_awaited_once_with(messages, max_tokens=0)

    async def test_fallback_to_max_tokens_one_on_any_error(self) -> None:
        """When max_tokens=0 is rejected, fall back to max_tokens=1."""
        llm = AsyncMock()
        llm.ainvoke.side_effect = [ValueError("max_tokens must be > 0"), MagicMock()]
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3")
        assert result is True
        assert llm.ainvoke.await_count == 2
        llm.ainvoke.assert_awaited_with(messages, max_tokens=1)

    async def test_fallback_on_bad_request_error(self) -> None:
        """BadRequestError (HTTP 400) from max_tokens=0 should also trigger fallback."""
        llm = AsyncMock()
        llm.ainvoke.side_effect = [RuntimeError("BadRequest: max_tokens too small"), MagicMock()]
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3")
        assert result is True
        assert llm.ainvoke.await_count == 2

    async def test_preheat_failure_returns_false(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.side_effect = RuntimeError("API error")
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "anthropic/claude-3")
        assert result is False

    async def test_cancelled_error_propagates(self) -> None:
        """CancelledError should not be swallowed by the exception handler."""
        llm = AsyncMock()
        llm.ainvoke.side_effect = asyncio.CancelledError()
        messages = [MagicMock()]

        with pytest.raises(asyncio.CancelledError):
            await preheat_prefix_cache(llm, messages, "anthropic/claude-3")

    async def test_preheat_with_qwen(self) -> None:
        llm = AsyncMock()
        llm.ainvoke.return_value = MagicMock()
        messages = [MagicMock()]

        result = await preheat_prefix_cache(llm, messages, "qwen-max")
        assert result is True
        llm.ainvoke.assert_awaited_once()


class TestScheduleInitPreheat:
    """Tests for fire-and-forget init preheat scheduling."""

    def test_skip_when_no_system_prompt(self) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, None, "anthropic/claude-3")
        schedule_init_preheat(llm, "", "anthropic/claude-3")

    def test_skip_when_non_explicit_provider(self) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "A long system prompt " * 200, "gpt-4o")

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=500)
    def test_skip_when_tokens_below_minimum(self, mock_est: MagicMock) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "Short prompt", "anthropic/claude-3")

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=_MIN_PREHEAT_TOKENS + 100)
    @patch("asyncio.get_running_loop")
    def test_schedules_task_when_eligible(self, mock_loop: MagicMock, mock_est: MagicMock) -> None:
        mock_loop.return_value.create_task = _mock_create_task()
        llm = MagicMock()

        schedule_init_preheat(llm, "A " * 2000, "anthropic/claude-3-5-sonnet")

        mock_loop.return_value.create_task.assert_called_once()

    @patch("myrm_agent_harness.utils.token_estimation.estimate_content_tokens", return_value=_MIN_PREHEAT_TOKENS + 100)
    def test_no_running_loop_does_not_raise(self, mock_est: MagicMock) -> None:
        llm = MagicMock()
        schedule_init_preheat(llm, "A " * 2000, "anthropic/claude-3")


class TestCacheKeepAliveManager:
    """Tests for idle prompt cache keep-alive manager."""

    def test_init_state(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        assert mgr._task is None
        assert mgr._stopped is False
        assert mgr._model_name == "anthropic/claude-3"

    def test_touch_updates_last_activity(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        before = mgr._last_activity
        time.sleep(0.01)
        mgr.touch()
        assert mgr._last_activity > before

    def test_start_creates_task(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        loop = MagicMock()
        loop.create_task = _mock_create_task()
        with patch("asyncio.get_running_loop", return_value=loop):
            mgr.start()
        loop.create_task.assert_called_once()
        assert mgr._task is not None

    def test_start_idempotent(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        loop = MagicMock()
        fake_task = MagicMock()
        loop.create_task = _mock_create_task(fake_task)
        with patch("asyncio.get_running_loop", return_value=loop):
            mgr.start()
            mgr.start()
        assert loop.create_task.call_count == 1

    def test_start_no_running_loop(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr.start()
        assert mgr._task is None

    def test_stop_cancels_task(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        fake_task = MagicMock()
        mgr._task = fake_task
        mgr.stop()
        fake_task.cancel.assert_called_once()
        assert mgr._task is None
        assert mgr._stopped is True

    def test_stop_idempotent(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr.stop()
        mgr.stop()
        assert mgr._stopped is True

    def test_start_after_stop_does_nothing(self) -> None:
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr.stop()
        loop = MagicMock()
        loop.create_task = MagicMock()
        with patch("asyncio.get_running_loop", return_value=loop):
            mgr.start()
        loop.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_skips_when_recently_active(self) -> None:
        """Loop should not send probe when agent was recently active.

        Uses a longer interval (0.5s) and keeps touching every 0.05s so the
        manager never considers the session idle.
        """
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr.touch()

        mock_preheat = AsyncMock(return_value=True)
        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.5,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                mock_preheat,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            for _ in range(4):
                await asyncio.sleep(0.05)
                mgr.touch()
            mgr.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_preheat.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_sends_probe_when_idle(self) -> None:
        """Loop should send probe when idle for longer than the interval."""
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr._last_activity = time.monotonic() - 600

        mock_preheat = AsyncMock(return_value=True)
        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.05,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                mock_preheat,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            await asyncio.sleep(0.15)
            mgr.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert mock_preheat.call_count >= 1

    @pytest.mark.asyncio
    async def test_loop_handles_probe_failure(self) -> None:
        """Probe failure should not crash the loop (fail-open)."""
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr._last_activity = time.monotonic() - 600

        mock_preheat = AsyncMock(side_effect=RuntimeError("API down"))
        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.05,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                mock_preheat,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            await asyncio.sleep(0.15)
            mgr.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_loop_exits_on_cancel(self) -> None:
        """Loop should exit gracefully on cancellation."""
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")

        task = asyncio.create_task(mgr._loop())
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_loop_respects_stopped_flag_after_sleep(self) -> None:
        """If stop() is called during the sleep, the loop should exit
        after waking without sending a probe."""
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")
        mgr._last_activity = time.monotonic() - 600

        mock_preheat = AsyncMock(return_value=True)
        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.1,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                mock_preheat,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            await asyncio.sleep(0.05)
            mgr.stop()
            await asyncio.sleep(0.2)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_preheat.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_touches_reset_idle(self) -> None:
        """Rapid touch() calls should keep resetting the idle timer,
        preventing probes from being sent."""
        llm = MagicMock()
        mgr = CacheKeepAliveManager(llm, "system prompt", "anthropic/claude-3")

        mock_preheat = AsyncMock(return_value=True)
        with (
            patch(
                "myrm_agent_harness.agent.context_management.preheat._KEEPALIVE_INTERVAL_SECONDS",
                0.3,
            ),
            patch(
                "myrm_agent_harness.agent.context_management.preheat.preheat_prefix_cache",
                mock_preheat,
            ),
        ):
            task = asyncio.create_task(mgr._loop())
            for _ in range(8):
                await asyncio.sleep(0.05)
                mgr.touch()
            mgr.stop()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        mock_preheat.assert_not_called()

    def test_keepalive_interval_constant(self) -> None:
        assert _KEEPALIVE_INTERVAL_SECONDS == 4 * 60
