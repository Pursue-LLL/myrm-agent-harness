"""Tests for run_lifecycle module."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent._internals.run_lifecycle import (
    _collect_tracker_stats,
    cleanup_run,
    compute_context_budget_snapshot,
    post_run_events,
    setup_workspace,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.types import AgentRunStatistics

_MOD = "myrm_agent_harness.agent._internals.run_lifecycle"


class TestSetupWorkspace:
    @pytest.mark.asyncio
    async def test_raises_without_workspaces_root(self) -> None:
        with pytest.raises(ValueError, match="workspaces_storage_root"):
            await setup_workspace(executor=None, context={"session_id": "s1"})

    @pytest.mark.asyncio
    async def test_raises_without_session_id(self) -> None:
        with pytest.raises(ValueError, match="session_id"):
            await setup_workspace(
                executor=None,
                context={
                    "session_id": "",
                    "workspaces_storage_root": "/tmp/host-ws",
                },
            )

    @pytest.mark.asyncio
    async def test_raises_with_none_context(self) -> None:
        with pytest.raises(ValueError, match="workspaces_storage_root"):
            await setup_workspace(executor=None, context=None)

    @pytest.mark.asyncio
    async def test_creates_workspace_with_provided_executor(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_or_create = AsyncMock(return_value="ws_obj")
        mock_svc.get_workspace_absolute_path.return_value = "/tmp/ws"

        mock_executor = MagicMock()
        mock_executor.get_executor_name.return_value = "TestExecutor"

        fake_root = "/tmp/host-aggregate"
        with (
            patch(f"{_MOD}.create_workspace_service", return_value=mock_svc) as mock_fact,
            patch(f"{_MOD}.set_workspace_root"),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.set_executor"),
        ):
            ctx, exe = await setup_workspace(
                executor=mock_executor,
                context={"session_id": "test_session", "workspaces_storage_root": fake_root},
            )

        assert ctx["workspace_path"] == "/tmp/ws"
        assert exe is mock_executor
        mock_executor.bind_workspace.assert_called_with("/tmp/ws")
        mock_fact.assert_called_once()
        call_kw = mock_fact.call_args.kwargs
        assert call_kw["root_dir"] == Path(fake_root).expanduser().resolve()

    @pytest.mark.asyncio
    async def test_auto_creates_executor(self) -> None:
        mock_svc = MagicMock()
        mock_svc.get_or_create = AsyncMock(return_value="ws_obj")
        mock_svc.get_workspace_absolute_path.return_value = "/tmp/ws"

        mock_executor = MagicMock()
        mock_executor.get_executor_name.return_value = "AutoExecutor"

        fake_root = "/tmp/host2"
        with (
            patch(f"{_MOD}.create_workspace_service", return_value=mock_svc),
            patch(f"{_MOD}.set_workspace_root"),
            patch("myrm_agent_harness.toolkits.code_execution.create_executor", return_value=mock_executor),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.set_executor"),
        ):
            _ctx, exe = await setup_workspace(
                executor=None, context={"session_id": "s1", "workspaces_storage_root": fake_root}
            )

        assert exe is mock_executor


class TestCleanupRun:
    def _run_cleanup(self, **overrides: object) -> AgentRunStatistics:
        stats = AgentRunStatistics()
        defaults = {
            "stats": stats,
            "start_time": time.time() - 5.0,
            "cancel_token": None,
            "steering_token": None,
            "cancel_all_fn": lambda: 0,
        }
        defaults.update(overrides)

        with (
            patch(f"{_MOD}.set_tool_progress_sink"),
            patch(f"{_MOD}.set_cancel_token"),
            patch(f"{_MOD}.set_workspace_root"),
            patch(f"{_MOD}._collect_tracker_stats"),
            patch(f"{_MOD}.reset_token_tracker"),
            patch(f"{_MOD}.clear_pending_explicit_cache_snapshot"),
            patch("myrm_agent_harness.agent.middlewares.approval.set_security_config"),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.set_executor"),
        ):
            cleanup_run(**defaults)  # type: ignore[arg-type]

        return stats

    def test_basic_cleanup(self) -> None:
        stats = self._run_cleanup()
        assert stats.total_duration_seconds >= 4.0

    def test_cancels_children(self) -> None:
        cancel_fn = MagicMock(return_value=3)
        self._run_cleanup(cancel_all_fn=cancel_fn)
        cancel_fn.assert_called_once()

    def test_clears_steering_token(self) -> None:
        mock_steering = MagicMock()
        with (
            patch(f"{_MOD}.set_tool_progress_sink"),
            patch(f"{_MOD}.set_cancel_token"),
            patch(f"{_MOD}.set_workspace_root"),
            patch(f"{_MOD}._collect_tracker_stats"),
            patch(f"{_MOD}.reset_token_tracker"),
            patch(f"{_MOD}.clear_pending_explicit_cache_snapshot"),
            patch("myrm_agent_harness.agent.middlewares.approval.set_security_config"),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.set_executor"),
            patch("myrm_agent_harness.utils.runtime.steering.set_steering_token") as mock_set_st,
        ):
            cleanup_run(
                stats=AgentRunStatistics(),
                start_time=time.time(),
                cancel_token=None,
                steering_token=mock_steering,
                cancel_all_fn=lambda: 0,
            )
        mock_set_st.assert_called_once_with(None)

    def test_clears_stashed_executor(self) -> None:
        with (
            patch(f"{_MOD}.set_tool_progress_sink"),
            patch(f"{_MOD}.set_cancel_token"),
            patch(f"{_MOD}.set_workspace_root"),
            patch(f"{_MOD}._collect_tracker_stats"),
            patch(f"{_MOD}.reset_token_tracker"),
            patch(f"{_MOD}.clear_pending_explicit_cache_snapshot"),
            patch("myrm_agent_harness.agent.middlewares.approval.set_security_config"),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.set_executor"),
            patch("myrm_agent_harness.toolkits.code_execution.executors.base.clear_stashed_executor") as mock_clear_exec,
        ):
            cleanup_run(
                stats=AgentRunStatistics(),
                start_time=time.time(),
                cancel_token=None,
                steering_token=None,
                cancel_all_fn=lambda: 0,
                merged_context={"session_id": "sess-exec-cleanup"},
            )
        mock_clear_exec.assert_called_once_with("sess-exec-cleanup")

    def test_survives_cleanup_error(self) -> None:
        stats = AgentRunStatistics()
        with patch(f"{_MOD}.set_tool_progress_sink", side_effect=RuntimeError("boom")):
            cleanup_run(
                stats=stats, start_time=time.time(), cancel_token=None, steering_token=None, cancel_all_fn=lambda: 0
            )


class TestCollectTrackerStats:
    def test_no_tracker(self) -> None:
        stats = AgentRunStatistics()
        with patch(f"{_MOD}.get_token_tracker", return_value=None):
            _collect_tracker_stats(stats)
        assert stats.token_usage is None

    def test_with_tracker(self) -> None:
        stats = AgentRunStatistics()

        mock_usage = MagicMock()
        mock_usage.cached_tokens = 0
        mock_usage.to_dict.return_value = {}

        mock_tracker = MagicMock()
        mock_tracker.get_usage.return_value = mock_usage
        mock_tracker.total_cost_usd = 0.001
        mock_tracker.cost_status = "actual"
        mock_tracker.last_finish_reason = "stop"
        mock_tracker.model_usage = {}
        mock_tracker.usage = mock_usage

        with patch(f"{_MOD}.get_token_tracker", return_value=mock_tracker):
            _collect_tracker_stats(stats)

        assert stats.token_usage is mock_usage
        assert stats.cost_usd == 0.001
        assert stats.cost_status == "actual"

    def test_with_model_usage_and_cache(self) -> None:
        stats = AgentRunStatistics()

        mock_usage = MagicMock()
        mock_usage.cached_tokens = 500
        mock_usage.get_cache_effectiveness.return_value = {
            "cache_hit_rate": 0.5,
            "cost_savings_pct": 0.3,
            "cost_savings_absolute": 150,
        }

        mock_model_usage = MagicMock()
        mock_model_usage.total_tokens = 100
        mock_model_usage.to_dict.return_value = {"total_tokens": 100}

        mock_tracker = MagicMock()
        mock_tracker.get_usage.return_value = mock_usage
        mock_tracker.total_cost_usd = 0.05
        mock_tracker.cost_status = "actual"
        mock_tracker.last_finish_reason = "stop"
        mock_tracker.model_usage = {"claude-3": mock_model_usage}
        mock_tracker.model_cost = {"claude-3": 0.05}
        mock_tracker.usage = mock_usage
        mock_tracker.call_count = 3
        mock_tracker.error_count = 0

        with patch(f"{_MOD}.get_token_tracker", return_value=mock_tracker):
            _collect_tracker_stats(stats)

        assert stats.model_usage is not None
        assert "claude-3" in stats.model_usage
        assert stats.primary_model == "claude-3"


class TestPostRunEvents:
    @pytest.mark.asyncio
    async def test_cancelled_yields_nothing(self) -> None:
        stats = AgentRunStatistics(was_cancelled=True)
        events = [e async for e in post_run_events(stats, "msg1", {}, False, None)]
        assert events == []

    @pytest.mark.asyncio
    async def test_yields_message_end(self) -> None:
        stats = AgentRunStatistics()

        with (
            patch(
                "myrm_agent_harness.agent.streaming.artifact_events.collect_ui_artifacts",
                return_value=_async_gen([]),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.format_mutation_failures",
                return_value=None,
            ),
        ):
            events = [e async for e in post_run_events(stats, "msg1", {}, False, None)]

        assert len(events) == 1
        assert events[0]["type"] == AgentEventType.MESSAGE_END.value

    @pytest.mark.asyncio
    async def test_includes_cost_info(self) -> None:
        mock_usage = MagicMock()
        mock_usage.to_dict.return_value = {"total_tokens": 100}

        stats = AgentRunStatistics(token_usage=mock_usage, cost_usd=0.05, cost_status="actual", primary_model="gpt-4")

        with (
            patch(
                "myrm_agent_harness.agent.streaming.artifact_events.collect_ui_artifacts",
                return_value=_async_gen([]),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.format_mutation_failures",
                return_value=None,
            ),
        ):
            events = [e async for e in post_run_events(stats, "msg1", {}, False, None)]

        end_event = events[-1]
        assert end_event["cost_usd"] == 0.05
        assert end_event["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_includes_model_usage_in_event(self) -> None:
        mock_usage = MagicMock()
        mock_usage.to_dict.return_value = {"total_tokens": 100}

        stats = AgentRunStatistics(
            token_usage=mock_usage, model_usage={"gpt-4": {"total_tokens": 100, "cost_usd": 0.01}}
        )

        with (
            patch(
                "myrm_agent_harness.agent.streaming.artifact_events.collect_ui_artifacts",
                return_value=_async_gen([]),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares._mutation_verifier.format_mutation_failures",
                return_value=None,
            ),
        ):
            events = [e async for e in post_run_events(stats, "msg1", {}, False, None)]

        end_event = events[-1]
        assert "usage" in end_event
        assert "model_usage" in end_event["usage"]


class TestComputeContextBudgetSnapshot:
    """Tests for compute_context_budget_snapshot."""

    def _make_stats(self, prompt_tokens: int) -> AgentRunStatistics:
        mock_last_call = MagicMock()
        mock_last_call.prompt_tokens = prompt_tokens

        mock_usage = MagicMock()
        mock_usage.last_call = mock_last_call

        return AgentRunStatistics(token_usage=mock_usage)

    def test_returns_none_without_usage(self) -> None:
        stats = AgentRunStatistics()
        result = compute_context_budget_snapshot(stats, 128_000)
        assert result is None

    def test_returns_none_with_zero_prompt(self) -> None:
        stats = self._make_stats(0)
        result = compute_context_budget_snapshot(stats, 128_000)
        assert result is None

    def test_healthy_status(self) -> None:
        stats = self._make_stats(50_000)
        result = compute_context_budget_snapshot(stats, 128_000)
        assert result is not None
        assert result.current_tokens == 50_000
        assert result.max_context_tokens == 128_000
        assert result.health_status == "healthy"
        assert 39 <= result.usage_percent <= 40

    def test_warning_status_at_80_percent(self) -> None:
        stats = self._make_stats(80_000)
        result = compute_context_budget_snapshot(stats, 100_000)
        assert result is not None
        assert result.health_status == "warning"
        assert result.usage_percent == 80.0

    def test_critical_status_at_90_percent(self) -> None:
        stats = self._make_stats(90_000)
        result = compute_context_budget_snapshot(stats, 100_000)
        assert result is not None
        assert result.health_status == "critical"
        assert result.usage_percent == 90.0

    def test_fallback_to_128k_when_none(self) -> None:
        stats = self._make_stats(64_000)
        result = compute_context_budget_snapshot(stats, None)
        assert result is not None
        assert result.max_context_tokens == 128_000
        assert result.usage_percent == 50.0

    def test_small_model_16k(self) -> None:
        """GPT-3.5 with 16K context: 14K tokens should be critical."""
        stats = self._make_stats(14_400)
        result = compute_context_budget_snapshot(stats, 16_000)
        assert result is not None
        assert result.health_status == "critical"
        assert result.max_context_tokens == 16_000
        assert result.usage_percent == 90.0

    def test_large_model_200k(self) -> None:
        """Claude with 200K context: 100K tokens should be healthy."""
        stats = self._make_stats(100_000)
        result = compute_context_budget_snapshot(stats, 200_000)
        assert result is not None
        assert result.health_status == "healthy"
        assert result.usage_percent == 50.0


async def _async_gen(items: list[object]):
    for item in items:
        yield item
