"""Tests for sub_agents/executor.py — execution logic and retry mechanism."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus


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
def executor():
    """Create executor instance."""
    return SubagentExecutor()


class TestExecutorInit:
    """Test SubagentExecutor initialization."""

    def test_init_creates_executor(self, executor):
        assert executor is not None


class TestRetryLogic:
    """Test retry mechanism."""

    @pytest.mark.asyncio
    async def test_single_attempt_success(self, executor, basic_config):
        """Test successful execution without retry."""
        parent_agent = MagicMock()
        cancel_flags = {}
        children_agents = {}
        children_steering = {}

        # Mock _run_single_attempt to return success
        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock_attempt:
            mock_result = SubAgentResult(
                success=True,
                task_id="test-task",
                agent_type="system",
                result="done",
                completed_at=0.0,
                status=SubAgentStatus.COMPLETED,
            )
            mock_attempt.return_value = mock_result

            result = await executor.run_with_retry(
                task_id="test-task",
                agent_type="system",
                task_description="test",
                config=basic_config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=parent_agent,
                cancel_flags=cancel_flags,
                children_agents=children_agents,
                children_steering=children_steering,
            )

            assert result.success is True
            assert mock_attempt.call_count == 1  # Only one attempt needed

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, executor, basic_config):
        """Test retry mechanism on failure."""
        parent_agent = MagicMock()
        cancel_flags = {}
        children_agents = {}
        children_steering = {}

        # Mock _run_single_attempt to fail once then succeed
        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock_attempt:
            mock_attempt.side_effect = [
                Exception("First attempt failed"),
                SubAgentResult(
                    success=True,
                    task_id="test-task",
                    agent_type="system",
                    result="done",
                    completed_at=0.0,
                    status=SubAgentStatus.COMPLETED,
                ),
            ]

            result = await executor.run_with_retry(
                task_id="test-task",
                agent_type="system",
                task_description="test",
                config=basic_config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=parent_agent,
                cancel_flags=cancel_flags,
                children_agents=children_agents,
                children_steering=children_steering,
            )

            assert result.success is True
            assert mock_attempt.call_count == 2  # Retry once

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, executor, basic_config):
        """Test that max retries limit is respected."""
        parent_agent = MagicMock()
        cancel_flags = {}
        children_agents = {}
        children_steering = {}

        # Mock _run_single_attempt to always fail
        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock_attempt:
            mock_attempt.side_effect = Exception("Always fails")

            result = await executor.run_with_retry(
                task_id="test-task",
                agent_type="system",
                task_description="test",
                config=basic_config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=parent_agent,
                cancel_flags=cancel_flags,
                children_agents=children_agents,
                children_steering=children_steering,
            )

            assert result.success is False
            assert result.status == SubAgentStatus.FAILED
            assert mock_attempt.call_count == basic_config.max_retries


class TestTimeoutHandling:
    """Test timeout retry and exhaustion."""

    @pytest.mark.asyncio
    async def test_timeout_retries_then_returns_timed_out(self, executor):
        """TimeoutError should retry and eventually return TIMED_OUT."""
        config = SubagentConfig(
            system_prompt="s", max_retries=2, timeout_seconds=10, retry_backoff_seconds=0,
        )
        parent_agent = MagicMock()

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = TimeoutError("timed out")

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents={}, children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.TIMED_OUT
        assert "Timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_timeout_retry_then_success(self, executor):
        """TimeoutError on first attempt, success on second."""
        config = SubagentConfig(
            system_prompt="s", max_retries=2, timeout_seconds=10, retry_backoff_seconds=0,
        )
        parent_agent = MagicMock()
        ok = SubAgentResult(
            success=True, task_id="t1", agent_type="sys", result="ok",
            completed_at=0.0, status=SubAgentStatus.COMPLETED,
        )

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = [TimeoutError("t"), ok]

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents={}, children_steering={},
            )

        assert result.success is True
        assert mock.call_count == 2


class TestBudgetExceeded:
    """Test budget exceeded handling."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_cancelled_by_budget(self, executor):
        """SubagentBudgetExceededError should return CANCELLED_BY_BUDGET."""
        from myrm_agent_harness.agent.sub_agents.types import SubagentBudgetExceededError

        config = SubagentConfig(system_prompt="s", max_retries=2, retry_backoff_seconds=0)
        parent_agent = MagicMock()

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = SubagentBudgetExceededError("over budget")

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents={}, children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.CANCELLED_BY_BUDGET
        assert mock.call_count == 1  # no retry


class TestCancellation:
    """Test CancelledError handling."""

    @pytest.mark.asyncio
    async def test_cancelled_error_returns_cancelled(self, executor):
        """asyncio.CancelledError should return CANCELLED status."""
        import asyncio

        config = SubagentConfig(system_prompt="s", max_retries=2, retry_backoff_seconds=0)
        parent_agent = MagicMock()

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = asyncio.CancelledError()

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents={}, children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.CANCELLED
        assert result.error == "Cancelled"

    @pytest.mark.asyncio
    async def test_cascade_cancel_descendants_on_cancellation(self, executor):
        """Cancelling a child should cascade-cancel its descendants."""
        import asyncio

        config = SubagentConfig(system_prompt="s", max_retries=2, retry_backoff_seconds=0)
        parent_agent = MagicMock()
        child_agent = MagicMock()
        child_agent.cancel_all_children = MagicMock(return_value=2)

        children_agents: dict[str, object] = {"t1": child_agent}

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = asyncio.CancelledError()

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents=children_agents, children_steering={},
            )

        assert result.status == SubAgentStatus.CANCELLED
        child_agent.cancel_all_children.assert_called_once()

    @pytest.mark.asyncio
    async def test_cascade_cancel_no_child_agent_is_safe(self, executor):
        """Cascade cancel should handle missing child agent gracefully."""
        import asyncio

        config = SubagentConfig(system_prompt="s", max_retries=2, retry_backoff_seconds=0)
        parent_agent = MagicMock()

        with patch.object(executor, "_run_single_attempt", new_callable=AsyncMock) as mock:
            mock.side_effect = asyncio.CancelledError()

            result = await executor.run_with_retry(
                task_id="t1", agent_type="sys", task_description="d",
                config=config, context={}, tool_registry_getter=lambda: [],
                start_time=0.0, parent_agent=parent_agent,
                cancel_flags={}, children_agents={}, children_steering={},
            )

        assert result.status == SubAgentStatus.CANCELLED


class TestContextInheritance:
    """Test context inheritance logic."""

    @pytest.mark.asyncio
    async def test_inherit_parent_context(self, executor):
        """Test that child context inherits essential fields from parent."""
        parent_agent = MagicMock()
        parent_agent._last_context = {
            "session_id": "parent-session",
            "user_id": "user-123",
            "workspace_path": "/path/to/workspace",
            "approval_session_key": "approval-key",
            "extra_field": "should-not-inherit",
        }

        context = {"custom_field": "custom-value"}

        merged = await executor._inherit_parent_context(context=context, task_id="test-task", parent_agent=parent_agent)

        # Verify inherited fields
        assert merged["session_id"] == "parent-session"
        assert merged["workspace_path"] == "/path/to/workspace"
        assert merged["approval_session_key"] == "approval-key"

        # Verify custom field preserved
        assert merged["custom_field"] == "custom-value"

        # Verify extra field not inherited
        assert "extra_field" not in merged

    @pytest.mark.asyncio
    async def test_inherit_parent_context_no_override(self, executor):
        """Test that child context is not overridden if field already exists."""
        parent_agent = MagicMock()
        parent_agent._last_context = {
            "session_id": "parent-session",
        }

        context = {
            "session_id": "child-session",  # Should not be overridden
            "user_id": "child-user",  # Should not be overridden
        }

        merged = await executor._inherit_parent_context(context=context, task_id="test-task", parent_agent=parent_agent)

        # Verify child values are preserved
        assert merged["session_id"] == "child-session"


class TestCacheHitPivot:
    """Test Cache-Hit Pivot architecture for fork mode."""

    @pytest.mark.asyncio
    async def test_cache_hit_pivot_fork_mode_history_slicing(self, executor):
        """Test that in fork mode, the trailing AIMessage (tool call) is sliced off."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        config = SubagentConfig(system_prompt="sys", context_mode="fork", max_fork_tokens=1000)
        parent_agent = MagicMock()
        parent_agent.config.system_prompt = "parent system"
        parent_agent.session_id = "test-session"

        parent_state = MagicMock()
        parent_state.values = {"messages": [
            SystemMessage(content="parent system"),
            HumanMessage(content="user query"),
            AIMessage(content="tool call")
        ]}
        parent_agent.checkpointer.aget = AsyncMock(return_value=parent_state)

        child_agent = MagicMock()
        async def mock_run(*args, **kwargs):
            child_agent.run_kwargs = kwargs
            yield {"type": "message", "data": "test"}
        child_agent.run = mock_run

        with patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=child_agent):
            await executor._run_single_attempt(
                task_id="t", agent_type="a", task_description="task", config=config,
                context={"session_id": "test-session"}, tool_registry_getter=lambda: [], start_time=0.0,
                parent_tracker=None, parent_taint=None,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                fire_hook=AsyncMock(), hook_event_cls=MagicMock()
            )

        kwargs = child_agent.run_kwargs

        history = kwargs["chat_history"]
        assert len(history) == 2
        assert isinstance(history[0], SystemMessage)
        assert isinstance(history[1], HumanMessage)

        query = kwargs["query"]
        assert "[System Override]" in query
        assert "Ignore previous global role settings" in query

    @pytest.mark.asyncio
    async def test_cache_hit_pivot_fork_mode_no_trailing_ai_message(self, executor):
        """Test that in fork mode, if no trailing AIMessage exists, history is untouched."""
        from langchain_core.messages import HumanMessage, SystemMessage

        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        config = SubagentConfig(system_prompt="sys", context_mode="fork")
        parent_agent = MagicMock()
        parent_agent.config.system_prompt = "parent system"
        parent_agent.session_id = "test-session"

        parent_state = MagicMock()
        parent_state.values = {"messages": [
            SystemMessage(content="parent system"),
            HumanMessage(content="user query")
        ]}
        parent_agent.checkpointer.aget = AsyncMock(return_value=parent_state)

        child_agent = MagicMock()
        async def mock_run(*args, **kwargs):
            child_agent.run_kwargs = kwargs
            yield {"type": "message", "data": "test"}
        child_agent.run = mock_run

        with patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=child_agent):
            await executor._run_single_attempt(
                task_id="t", agent_type="a", task_description="task", config=config,
                context={"session_id": "test-session"}, tool_registry_getter=lambda: [], start_time=0.0,
                parent_tracker=None, parent_taint=None,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                fire_hook=AsyncMock(), hook_event_cls=MagicMock()
            )

        kwargs = child_agent.run_kwargs
        history = kwargs["chat_history"]
        assert len(history) == 2
        assert isinstance(history[0], SystemMessage)
        assert isinstance(history[1], HumanMessage)


class TestTaintInboundWarning:
    """Tests for taint-based inbound security warning on subagent results (Roadmap #4C)."""

    @pytest.mark.asyncio
    async def test_tainted_result_gets_warning_prefix(self, executor, basic_config):
        """When child taint tracker is tainted, final_result gets security warning prefix."""
        from myrm_agent_harness.agent.security.guards.taint_tracker import (
            TaintLabel,
            TaintTracker,
            get_taint_tracker,
            reset_taint_tracker,
        )

        parent_agent = MagicMock()
        parent_taint = TaintTracker()

        reset_taint_tracker()
        child_taint = get_taint_tracker()
        child_taint.record(TaintLabel.EXTERNAL_NETWORK, source="curl_output")

        child_agent = MagicMock()
        child_agent.last_run_stats = MagicMock()
        child_agent.last_run_stats.token_usage = None

        async def mock_run(**kwargs):
            yield {"type": "message", "data": "result text"}
        child_agent.run = mock_run

        with patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=child_agent), \
             patch("myrm_agent_harness.agent.sub_agents.executor._auto_vault_or_truncate", return_value="some result"), \
             patch("myrm_agent_harness.agent.sub_agents.executor._parse_handover_state", return_value=None), \
             patch("myrm_agent_harness.agent.sub_agents.executor.merge_child_stats"):

            result = await executor._run_single_attempt(
                task_id="t1", agent_type="research", task_description="fetch web data",
                config=basic_config,
                context={"session_id": "test-session"}, tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_tracker=None, parent_taint=parent_taint,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                fire_hook=AsyncMock(), hook_event_cls=MagicMock()
            )

        assert result.result is not None
        assert "[SECURITY WARNING]" in result.result
        assert "external_network" in result.result
        assert "some result" in result.result
        assert TaintLabel.EXTERNAL_NETWORK in parent_taint.labels

    @pytest.mark.asyncio
    async def test_non_tainted_result_no_warning(self, executor, basic_config):
        """When child taint tracker is clean, no warning prefix is added."""
        from myrm_agent_harness.agent.security.guards.taint_tracker import (
            TaintTracker,
            reset_taint_tracker,
        )

        parent_agent = MagicMock()
        parent_taint = TaintTracker()

        reset_taint_tracker()

        child_agent = MagicMock()
        child_agent.last_run_stats = MagicMock()
        child_agent.last_run_stats.token_usage = None

        async def mock_run(**kwargs):
            yield {"type": "message", "data": "clean result"}
        child_agent.run = mock_run

        with patch("myrm_agent_harness.agent.sub_agents.executor.build_child_agent", return_value=child_agent), \
             patch("myrm_agent_harness.agent.sub_agents.executor._auto_vault_or_truncate", return_value="clean result"), \
             patch("myrm_agent_harness.agent.sub_agents.executor._parse_handover_state", return_value=None), \
             patch("myrm_agent_harness.agent.sub_agents.executor.merge_child_stats"):

            result = await executor._run_single_attempt(
                task_id="t2", agent_type="research", task_description="read local file",
                config=basic_config,
                context={"session_id": "test-session"}, tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_tracker=None, parent_taint=parent_taint,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                fire_hook=AsyncMock(), hook_event_cls=MagicMock()
            )

        assert result.result == "clean result"
        assert "[SECURITY WARNING]" not in result.result


class TestAutoVaultOrTruncate:
    """Tests for _auto_vault_or_truncate helper function."""

    def test_no_threshold_returns_truncated(self):
        from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate

        config = MagicMock()
        config.auto_vault_threshold = None
        config.max_result_tokens = 100

        result = _auto_vault_or_truncate("short", config, {}, "t1", "research")
        assert result == "short"

    def test_below_threshold_returns_truncated(self):
        from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate

        config = MagicMock()
        config.auto_vault_threshold = 1000
        config.max_result_tokens = 100

        result = _auto_vault_or_truncate("short", config, {}, "t1", "research")
        assert result == "short"

    def test_above_threshold_no_workspace_falls_back(self):
        from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate

        config = MagicMock()
        config.auto_vault_threshold = 10
        config.max_result_tokens = 5

        result = _auto_vault_or_truncate("a" * 100, config, {}, "t1", "research")
        assert len(result) <= 100

    def test_above_threshold_vault_exception_falls_back(self):
        from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate

        config = MagicMock()
        config.auto_vault_threshold = 10
        config.max_result_tokens = 20

        with patch("myrm_agent_harness.agent.artifacts.vault.ArtifactVault", side_effect=Exception("vault error")):
            result = _auto_vault_or_truncate(
                "x" * 100, config, {"workspace_path": "/tmp/ws"}, "t1", "research"
            )
        assert "Truncated" in result or len(result) <= 200

    def test_above_threshold_vault_success(self):
        from myrm_agent_harness.agent.sub_agents.executor import _auto_vault_or_truncate

        config = MagicMock()
        config.auto_vault_threshold = 10
        config.max_result_tokens = 5000

        mock_vault = MagicMock()
        mock_vault.put.return_value = "vault://abc123"

        with patch("myrm_agent_harness.agent.artifacts.vault.ArtifactVault", return_value=mock_vault):
            result = _auto_vault_or_truncate(
                "x" * 100, config, {"workspace_path": "/tmp/ws"}, "t1", "research"
            )
        assert "vault://abc123" in result


class TestParseHandoverState:
    """Tests for _parse_handover_state helper function."""

    def test_no_handover_tag(self):
        from myrm_agent_harness.agent.sub_agents.executor import _parse_handover_state

        result = _parse_handover_state("just some text without handover", "t1")
        assert result is None

    def test_valid_handover_json(self):
        from myrm_agent_harness.agent.sub_agents.executor import _parse_handover_state

        raw = '''Some result text
<handover>
{"task_completed": ["item1"], "pending_todos": [], "risks_or_notes": [], "relevant_files": []}
</handover>'''

        result = _parse_handover_state(raw, "t1")
        assert result is not None
        assert "item1" in result.task_completed

    def test_handover_with_code_fence(self):
        from myrm_agent_harness.agent.sub_agents.executor import _parse_handover_state

        raw = '''<handover>
```json
{"task_completed": ["done"], "pending_todos": [], "risks_or_notes": [], "relevant_files": []}
```
</handover>'''

        result = _parse_handover_state(raw, "t1")
        assert result is not None

    def test_handover_with_plain_code_fence(self):
        from myrm_agent_harness.agent.sub_agents.executor import _parse_handover_state

        raw = '''<handover>
```
{"task_completed": ["done"], "pending_todos": [], "risks_or_notes": [], "relevant_files": []}
```
</handover>'''

        result = _parse_handover_state(raw, "t1")
        assert result is not None

    def test_invalid_json_returns_none(self):
        from myrm_agent_harness.agent.sub_agents.executor import _parse_handover_state

        raw = "<handover>not json</handover>"
        result = _parse_handover_state(raw, "t1")
        assert result is None


class TestExecuteWithRetry:
    """Tests for retry and error handling in execute method."""

    @pytest.mark.asyncio
    async def test_timeout_retries_then_fails(self, executor, basic_config):
        parent_agent = MagicMock()
        retry_config = SubagentConfig(
            system_prompt="test",
            budget_tokens=10000,
            max_result_tokens=5000,
            timeout_seconds=60,
            max_retries=1,
            retry_backoff_seconds=0,
        )

        async def mock_single_attempt(*args, **kwargs):
            raise TimeoutError("timed out")

        with patch.object(executor, "_run_single_attempt", side_effect=mock_single_attempt):
            result = await executor.run_with_retry(
                task_id="t1", agent_type="research",
                task_description="test task", config=retry_config,
                context={"session_id": "s"}, tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                children_steering={},
            )

        assert not result.success
        assert result.status == SubAgentStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_general_exception_returns_failed(self, executor, basic_config):
        parent_agent = MagicMock()

        async def mock_single_attempt(*args, **kwargs):
            raise RuntimeError("unexpected error")

        with patch.object(executor, "_run_single_attempt", side_effect=mock_single_attempt):
            result = await executor.run_with_retry(
                task_id="t1", agent_type="research",
                task_description="test task", config=basic_config,
                context={"session_id": "s"}, tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=parent_agent, cancel_flags={}, children_agents={},
                children_steering={},
            )

        assert not result.success
        assert result.status == SubAgentStatus.FAILED
        assert "unexpected error" in result.error

