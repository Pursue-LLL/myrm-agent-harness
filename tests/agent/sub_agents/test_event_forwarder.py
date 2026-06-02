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
