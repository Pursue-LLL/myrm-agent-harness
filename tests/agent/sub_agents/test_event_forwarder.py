"""Tests for sub_agents/event_forwarder.py — event forwarding and progress tracking."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.event_forwarder import SubagentEventForwarder
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture
def basic_config():
    """Basic subagent config for testing."""
    return SubagentConfig(
        system_prompt="system",
        budget_tokens=10000,
        max_result_tokens=5000,
        timeout_seconds=60,
        max_retries=2,
        retry_backoff_seconds=1,
    )


@pytest.fixture
def event_forwarder(basic_config):
    """Create event forwarder instance."""
    return SubagentEventForwarder(task_id="test-task", agent_type="worker", config=basic_config, start_time=0.0)


class TestEventForwarderInit:
    """Test SubagentEventForwarder initialization."""

    def test_init_sets_task_info(self, basic_config):
        forwarder = SubagentEventForwarder(
            task_id="test-task", agent_type="worker", config=basic_config, start_time=0.0
        )
        assert forwarder.task_id == "test-task"
        assert forwarder.agent_type == "worker"
        assert forwarder.config == basic_config
        assert forwarder.start_time == 0.0

    def test_init_sets_default_tracking_state(self, event_forwarder):
        assert event_forwarder.cumulative_tokens == 0
        assert event_forwarder.tool_count == 0
        assert event_forwarder.last_progress == -1.0
        assert event_forwarder.last_emit_time == 0.0
        assert event_forwarder.current_tool_name is None
        assert event_forwarder.token_history == []


class TestProgressCalculation:
    """Test progress calculation logic."""

    def test_calculate_progress_token_based(self, event_forwarder):
        """Test token-based progress calculation."""
        progress, progress_data = event_forwarder._calculate_default_progress(elapsed_seconds=10.0)

        assert progress == 0.0  # No tokens consumed yet
        assert progress_data["progress"] == 0.0
        assert progress_data["current_tokens"] == 0
        assert progress_data["budget_tokens"] == 10000
        assert progress_data["is_estimated"] is False

    def test_calculate_progress_tool_based_no_budget(self):
        """Test tool-based progress when no budget is set."""
        config = SubagentConfig(
            system_prompt="system",
            budget_tokens=None,  # No budget
            max_result_tokens=5000,
            timeout_seconds=60,
        )
        forwarder = SubagentEventForwarder(task_id="test-task", agent_type="worker", config=config, start_time=0.0)
        forwarder.tool_count = 4

        progress, progress_data = forwarder._calculate_default_progress(elapsed_seconds=10.0)

        assert progress == 0.5  # 4 tools / 8 = 0.5
        assert progress_data["is_estimated"] is True

    def test_eta_prediction(self, event_forwarder):
        """Test ETA prediction based on token consumption rate."""
        # Simulate token consumption history
        event_forwarder.token_history = [
            (0.0, 0),
            (10.0, 2000),
            (20.0, 4000),
        ]
        event_forwarder.cumulative_tokens = 4000

        _progress, progress_data = event_forwarder._calculate_default_progress(elapsed_seconds=20.0)

        assert "eta_seconds" in progress_data
        assert "eta_readable" in progress_data
        # Token rate: 4000/20 = 200 tokens/s
        # Remaining: 10000 - 4000 = 6000 tokens
        # ETA: 6000/200 = 30s
        assert progress_data["eta_seconds"] == 30


class TestBudgetCheck:
    """Test budget exceeded checking."""

    def test_budget_not_exceeded(self, event_forwarder):
        event_forwarder.cumulative_tokens = 5000
        event_forwarder.check_budget()  # Should not raise

    def test_budget_exceeded(self, event_forwarder):
        from myrm_agent_harness.agent.sub_agents.types import SubagentBudgetExceededError
        event_forwarder.cumulative_tokens = 15000  # Exceeds 10000
        with pytest.raises(SubagentBudgetExceededError):
            event_forwarder.check_budget()

    def test_budget_none_never_exceeded(self):
        """Test that when budget is None, check always returns False."""
        config = SubagentConfig(
            system_prompt="system",
            budget_tokens=None,  # No budget
            max_result_tokens=5000,
            timeout_seconds=60,
        )
        forwarder = SubagentEventForwarder(task_id="test-task", agent_type="worker", config=config, start_time=0.0)
        forwarder.cumulative_tokens = 1000000  # Very large

        forwarder.check_budget()  # Should not raise


class TestEventHandling:
    """Test event handling logic."""

    @pytest.mark.asyncio
    async def test_handle_token_usage_updates_cumulative_tokens(self, event_forwarder):
        """Test that TOKEN_USAGE event updates cumulative_tokens."""
        event = {
            "type": AgentEventType.TOKEN_USAGE.value,
            "data": {
                "usage": {
                    "total_tokens": 1000,
                },
            },
        }

        await event_forwarder.handle_event(event)

        assert event_forwarder.cumulative_tokens == 1000

    @pytest.mark.asyncio
    async def test_handle_token_usage_invokes_running_usage_callback(self, event_forwarder) -> None:
        captured: list[dict[str, object]] = []
        event_forwarder._on_running_token_usage = captured.append

        class FakeSink:
            async def emit(self, event: dict[str, object]) -> None:
                return None

        event_forwarder._parent_progress_sink = FakeSink()

        event = {
            "type": AgentEventType.TOKEN_USAGE.value,
            "data": {
                "usage": {
                    "total_tokens": 1000,
                    "input_tokens": 700,
                    "output_tokens": 300,
                },
            },
        }

        await event_forwarder.handle_event(event)

        assert len(captured) == 1
        assert captured[0]["total_tokens"] == 1000
        assert captured[0]["input_tokens"] == 700

    @pytest.mark.asyncio
    async def test_handle_tool_start_updates_current_tool_name(self, event_forwarder):
        """Test that TOOL_START event updates current_tool_name."""
        event = {
            "type": AgentEventType.TOOL_START.value,
            "data": {
                "tool_name": "bash",
            },
        }

        await event_forwarder.handle_event(event)

        assert event_forwarder.current_tool_name == "bash"

    @pytest.mark.asyncio
    async def test_handle_tool_end_increments_tool_count(self, event_forwarder):
        """Test that TOOL_END event increments tool_count."""
        event = {
            "type": AgentEventType.TOOL_END.value,
            "data": {
                "tool_name": "bash",
            },
            "duration_ms": 100,
        }

        await event_forwarder.handle_event(event)

        assert event_forwarder.tool_count == 1


class TestParentProgressSink:
    """Subagent task uses a child progress queue; parent sink must be explicit."""

    @pytest.mark.asyncio
    async def test_active_sink_routes_tasks_steps_to_parent(self, basic_config) -> None:
        emitted: list[dict] = []

        class FakeSink:
            async def emit(self, event: dict) -> None:
                emitted.append(event)

        parent = FakeSink()
        forwarder = SubagentEventForwarder(
            task_id="t1",
            agent_type="worker",
            config=basic_config,
            start_time=0.0,
            parent_progress_sink=parent,
        )
        event = {
            "type": AgentEventType.TASKS_STEPS.value,
            "step_key": "tool_error",
            "status": "error",
            "error": "[SYSTEM_ENFORCED] denied",
        }
        await forwarder.handle_event(event)

        assert len(emitted) == 1
        assert emitted[0]["type"] == AgentEventType.SUBAGENT_LOG.value
        data = emitted[0]["data"]
        assert data.get("error") == "[SYSTEM_ENFORCED] denied"
        assert data.get("level") == "ERROR"


# ---------------------------------------------------------------------------
# Staleness Detection Tests
# ---------------------------------------------------------------------------


class TestStalenessInit:
    """Test staleness-related fields are properly initialized."""

    def test_init_staleness_state(self, event_forwarder: SubagentEventForwarder) -> None:
        assert event_forwarder._last_effective_progress_at == 0.0  # matches start_time
        assert event_forwarder._in_tool is False
        assert event_forwarder._stale_emitted is False

    def test_is_stale_false_initially(self, basic_config: SubagentConfig) -> None:
        import time as _time

        now = _time.time()
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=basic_config, start_time=now,
        )
        assert forwarder.is_stale() is False


class TestStalenessConfig:
    """Test SubagentConfig staleness defaults and custom values."""

    def test_stale_config_defaults(self) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        assert cfg.stale_after_seconds == 300
        assert cfg.in_tool_stale_multiplier == 4
        assert cfg.stale_auto_cancel is False

    def test_custom_stale_config(self) -> None:
        cfg = SubagentConfig(
            system_prompt="sys",
            stale_after_seconds=60,
            in_tool_stale_multiplier=2,
            stale_auto_cancel=True,
        )
        assert cfg.stale_after_seconds == 60
        assert cfg.in_tool_stale_multiplier == 2
        assert cfg.stale_auto_cancel is True


class TestIsStale:
    """Test is_stale() threshold logic."""

    def test_stale_after_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=10)
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        # At t=100, last_effective=100, so (100-100)=0 < 10 → not stale
        monkeypatch.setattr("time.time", lambda: 100.0)
        assert forwarder.is_stale() is False

        # At t=111, (111-100)=11 > 10 → stale
        monkeypatch.setattr("time.time", lambda: 111.0)
        assert forwarder.is_stale() is True

    def test_in_tool_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(
            system_prompt="sys", stale_after_seconds=10, in_tool_stale_multiplier=3,
        )
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        forwarder._in_tool = True

        # threshold = 10 * 3 = 30; at t=125 → (125-100)=25 < 30 → not stale
        monkeypatch.setattr("time.time", lambda: 125.0)
        assert forwarder.is_stale() is False

        # at t=131 → (131-100)=31 > 30 → stale
        monkeypatch.setattr("time.time", lambda: 131.0)
        assert forwarder.is_stale() is True


class TestMarkProgress:
    """Test _mark_progress() resets staleness tracking."""

    def test_mark_progress_resets_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=10)
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        # Simulate stale state
        forwarder._stale_emitted = True

        monkeypatch.setattr("time.time", lambda: 200.0)
        forwarder._mark_progress()

        assert forwarder._last_effective_progress_at == 200.0
        assert forwarder._stale_emitted is False

        # Should not be stale immediately after progress
        monkeypatch.setattr("time.time", lambda: 205.0)
        assert forwarder.is_stale() is False


class TestStaleEventEmission:
    """Test _check_and_emit_stale() event emission behavior."""

    @pytest.mark.asyncio
    async def test_stale_emitted_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SUBAGENT_STALE should fire exactly once until progress resets it."""
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=5)
        emitted: list[dict] = []

        class FakeSink:
            async def emit(self, event: dict) -> None:
                emitted.append(event)

        sink = FakeSink()
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="researcher", config=cfg, start_time=100.0,
            parent_progress_sink=sink,
        )
        forwarder.cumulative_tokens = 500

        monkeypatch.setattr("time.time", lambda: 106.0)
        # Patch out lifecycle event publish to avoid import errors
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 1
        assert emitted[0]["type"] == AgentEventType.SUBAGENT_STALE.value

        # Second call should NOT emit again
        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_stale_not_emitted_when_not_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=60)
        emitted: list[dict] = []

        class FakeSink:
            async def emit(self, event: dict) -> None:
                emitted.append(event)

        sink = FakeSink()
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
            parent_progress_sink=sink,
        )
        monkeypatch.setattr("time.time", lambda: 110.0)  # 10s < 60s threshold
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 0

    @pytest.mark.asyncio
    async def test_stale_data_structure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=5, stale_auto_cancel=True)
        emitted: list[dict] = []

        class FakeSink:
            async def emit(self, event: dict) -> None:
                emitted.append(event)

        sink = FakeSink()
        forwarder = SubagentEventForwarder(
            task_id="task-abc", agent_type="coder", config=cfg, start_time=100.0,
            parent_progress_sink=sink,
        )
        forwarder.cumulative_tokens = 1234
        forwarder.current_tool_name = "bash"
        monkeypatch.setattr("time.time", lambda: 106.0)
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        await forwarder._check_and_emit_stale(sink)

        assert len(emitted) == 1
        data = emitted[0]["data"]
        assert data["task_id"] == "task-abc"
        assert data["agent_type"] == "coder"
        assert data["wasted_tokens"] == 1234
        assert data["current_tool"] == "bash"
        assert data["auto_cancel"] is True
        assert isinstance(data["stale_duration_seconds"], float)
        assert isinstance(data["elapsed_seconds"], float)

    @pytest.mark.asyncio
    async def test_stale_resets_after_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After progress, stale can fire again."""
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=5)
        emitted: list[dict] = []

        class FakeSink:
            async def emit(self, event: dict) -> None:
                emitted.append(event)

        sink = FakeSink()
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
            parent_progress_sink=sink,
        )
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        # First stale
        monkeypatch.setattr("time.time", lambda: 106.0)
        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 1

        # Progress resets stale
        monkeypatch.setattr("time.time", lambda: 110.0)
        forwarder._mark_progress()

        # Not stale yet
        monkeypatch.setattr("time.time", lambda: 113.0)
        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 1

        # Stale again
        monkeypatch.setattr("time.time", lambda: 116.0)
        await forwarder._check_and_emit_stale(sink)
        assert len(emitted) == 2

    @pytest.mark.asyncio
    async def test_stale_with_none_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No crash when sink is None."""
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=5)
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        monkeypatch.setattr("time.time", lambda: 106.0)
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        await forwarder._check_and_emit_stale(None)
        assert forwarder._stale_emitted is True


class TestStalenessIntegration:
    """Test staleness tracking through event handlers."""

    @pytest.mark.asyncio
    async def test_token_usage_marks_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys", stale_after_seconds=10)
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        monkeypatch.setattr("time.time", lambda: 105.0)
        monkeypatch.setattr(forwarder, "_publish_stale_lifecycle_event", lambda d: None)

        event = {
            "type": AgentEventType.TOKEN_USAGE.value,
            "data": {"usage": {"total_tokens": 500}},
        }
        await forwarder.handle_event(event)

        assert forwarder._last_effective_progress_at == 105.0

    @pytest.mark.asyncio
    async def test_tool_start_sets_in_tool(self) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=0.0,
        )
        event = {"type": AgentEventType.TOOL_START.value, "data": {"tool_name": "bash"}}
        await forwarder.handle_event(event)
        assert forwarder._in_tool is True

    @pytest.mark.asyncio
    async def test_tool_end_clears_in_tool_and_marks_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=100.0,
        )
        forwarder._in_tool = True
        monkeypatch.setattr("time.time", lambda: 120.0)

        event = {"type": AgentEventType.TOOL_END.value, "data": {"tool_name": "bash"}, "duration_ms": 100}
        await forwarder.handle_event(event)

        assert forwarder._in_tool is False
        assert forwarder._last_effective_progress_at == 120.0

    @pytest.mark.asyncio
    async def test_tool_failure_clears_in_tool(self) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=0.0,
        )
        forwarder._in_tool = True
        event = {"type": AgentEventType.TOOL_FAILURE.value, "data": {"tool_name": "bash", "error": "fail"}}
        await forwarder.handle_event(event)
        assert forwarder._in_tool is False

    @pytest.mark.asyncio
    async def test_tool_cancelled_clears_in_tool(self) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=0.0,
        )
        forwarder._in_tool = True
        event = {
            "type": AgentEventType.TOOL_CANCELLED.value,
            "data": {"tool_name": "bash", "cancel_reason": "user", "duration_ms": 0},
        }
        await forwarder.handle_event(event)
        assert forwarder._in_tool is False

    @pytest.mark.asyncio
    async def test_tool_timeout_clears_in_tool(self) -> None:
        cfg = SubagentConfig(system_prompt="sys")
        forwarder = SubagentEventForwarder(
            task_id="t", agent_type="w", config=cfg, start_time=0.0,
        )
        forwarder._in_tool = True
        event = {
            "type": AgentEventType.TOOL_TIMEOUT.value,
            "data": {"tool_name": "bash", "timeout_seconds": 30, "attempt": 1, "elapsed_ms": 30000},
        }
        await forwarder.handle_event(event)
        assert forwarder._in_tool is False
