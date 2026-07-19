"""Tests for delegate_task_tool.py: dynamic description, batch reuse, cache, L0 admission.

Covers:
- _build_dynamic_description with display_name rendering
- _cache_key / _get_cached / _put_cache
- create_delegate_task_tool L0 type admission
- _create_batch_delegate_tasks_tool reuse of delegate_tool
- Result cache TTL and eviction
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.types import (
    AgentHandoverState,
    ControlScope,
    DelegateRole,
    MemoryIsolationPolicy,
    SubagentConfig,
    SubAgentResult,
)
from myrm_agent_harness.utils.token_economics.budget_guard import BudgetStatus


def _create_batch_delegate_tasks_tool(
    parent_agent: MagicMock,
    tool_registry_getter: object,
    catalog: object,
    parent_type: str | None = None,
    allowed_types: list[str] | None = None,
    *,
    delegate_tool: object | None = None,
) -> MagicMock:
    """Test adapter for unified batch delegation (replaces removed LLM tool factory)."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
        execute_batch_delegation,
    )
    from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
        create_delegate_task_tool,
    )

    if delegate_tool is None:
        delegate_tool = create_delegate_task_tool(
            parent_agent,
            tool_registry_getter,  # type: ignore[arg-type]
            catalog,  # type: ignore[arg-type]
            parent_type,
            allowed_types,
        )

    batch = MagicMock()
    batch.name = "batch_delegate_tasks_tool"

    async def _invoke(
        payload: dict[str, object] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        data = dict(payload or kwargs)
        return await execute_batch_delegation(
            parent_agent=parent_agent,
            delegate_tool=delegate_tool,  # type: ignore[arg-type]
            catalog=catalog,  # type: ignore[arg-type]
            tasks=data.get("tasks") or [],
            wait=bool(data.get("wait", True)),
            race=bool(data.get("race", False)),
            tournament=bool(data.get("tournament", False)),
            judge_criteria=data.get("judge_criteria"),  # type: ignore[arg-type]
            max_concurrent=data.get("max_concurrent"),  # type: ignore[arg-type]
            parent_type=parent_type,
        )

    batch.ainvoke = _invoke
    batch.coroutine = _invoke
    batch.func = lambda **kwargs: _invoke(**kwargs)
    return batch


def _make_mock_parent(**overrides: object) -> MagicMock:
    """Build a MagicMock parent agent with safe defaults.

    Without explicit config/engine_params, MagicMock auto-creates
    truthy attributes that accidentally activate adversarial
    verification in delegate_task_tool.
    """
    parent = MagicMock()
    parent.config = None
    parent.engine_params = {}
    for k, v in overrides.items():
        setattr(parent, k, v)
    return parent


class TestCache:
    def test_cache_key_deterministic(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _cache_key

        k1 = _cache_key("coder", "write tests", {"file": "a.py"}, session_id="s1")
        k2 = _cache_key("coder", "write tests", {"file": "a.py"}, session_id="s1")
        assert k1 == k2

    def test_cache_key_differs_on_task(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _cache_key

        k1 = _cache_key("coder", "task A", None, session_id="s1")
        k2 = _cache_key("coder", "task B", None, session_id="s1")
        assert k1 != k2

    def test_cache_key_differs_on_session(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _cache_key

        k1 = _cache_key("coder", "task A", None, session_id="s1")
        k2 = _cache_key("coder", "task A", None, session_id="s2")
        assert k1 != k2

    def test_put_and_get(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _get_cached,
            _put_cache,
            _result_cache,
        )

        _result_cache.clear()
        _put_cache("test-key", {"result": "ok"})
        assert _get_cached("test-key") == {"result": "ok"}
        _result_cache.clear()

    def test_expired_entry_not_returned(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _CachedResult,
            _get_cached,
            _result_cache,
        )

        _result_cache.clear()
        _result_cache["old-key"] = _CachedResult({"data": 1}, time.time() - 120)
        assert _get_cached("old-key") is None
        assert "old-key" not in _result_cache
        _result_cache.clear()

    def test_put_evicts_oldest_on_overflow(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _CACHE_MAX_SIZE,
            _get_cached,
            _put_cache,
            _result_cache,
        )

        _result_cache.clear()
        for i in range(_CACHE_MAX_SIZE):
            _put_cache(f"k-{i}", {"i": i})
        assert len(_result_cache) == _CACHE_MAX_SIZE

        _put_cache("overflow", {"new": True})
        assert len(_result_cache) == _CACHE_MAX_SIZE
        assert _get_cached("overflow") == {"new": True}
        _result_cache.clear()


class TestBuildDynamicDescription:
    @pytest.mark.asyncio
    async def test_display_name_in_description(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=["agent-abc"])
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(
                system_prompt="I am a research agent",
                display_name="研究助手",
                description="Performs deep research",
                tools=("web_search", "read_file"),
            )
        )

        desc = await _build_dynamic_description(catalog, allowed_types=None)

        assert "研究助手 (agent-abc)" in desc
        assert "Performs deep research" in desc
        # Tools list is no longer included in the description to save tokens
        assert "web_search" not in desc

    @pytest.mark.asyncio
    async def test_no_display_name_uses_id(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=["coder-001"])
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(
                system_prompt="I write code", display_name="", description="Code writer", tools=()
            )
        )

        desc = await _build_dynamic_description(catalog, allowed_types=None)

        assert "coder-001" in desc
        assert "(coder-001)" not in desc

    @pytest.mark.asyncio
    async def test_allowed_types_filter(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=["a", "b", "c"])
        catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="test", description="desc"))

        desc = await _build_dynamic_description(catalog, allowed_types=["a", "c"])

        assert "- 'a'" in desc
        assert "- 'c'" in desc
        assert "- 'b'" not in desc

    @pytest.mark.asyncio
    async def test_max_50_display(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        ids = [f"agent-{i}" for i in range(55)]
        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=ids)
        catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="test", description="desc"))

        desc = await _build_dynamic_description(catalog, allowed_types=None)

        assert "agent-49" in desc
        assert "agent-50" not in desc
        assert "5 more" in desc

    @pytest.mark.asyncio
    async def test_when_not_to_delegate_section(self):
        """Verify dynamic description includes delegation guidance from SSOT."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=["worker"])
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="worker agent", description="General worker")
        )

        desc = await _build_dynamic_description(catalog, allowed_types=None)

        assert "When to delegate" in desc
        assert "If none apply, execute directly" in desc
        assert "specialized expertise" in desc
        assert "adversarial breadth" in desc
        assert "subagent_control_tool action=list" in desc
        assert "mode=single|batch|parallel" in desc

    @pytest.mark.asyncio
    async def test_system_prompt_fallback_when_no_description(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import _build_dynamic_description

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=["my-agent"])
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(
                system_prompt="A very detailed system prompt for the agent that goes beyond 80 chars in length to test truncation properly",
                description="",
            )
        )

        desc = await _build_dynamic_description(catalog, allowed_types=None)

        assert "A very detailed system prompt" in desc


class TestCreateDelegateTaskTool:
    def test_tool_has_correct_name(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool

        parent = _make_mock_parent()
        catalog = AsyncMock()
        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        assert tool_fn.name == "delegate_task_tool"

    @pytest.mark.asyncio
    async def test_l0_type_admission_blocks(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool

        parent = _make_mock_parent()
        catalog = AsyncMock()
        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog, allowed_types=["coder"])

        result = await tool_fn.coroutine(agent_type="forbidden-type", objective="hack the system")
        assert result["success"] is False
        assert "not allowed" in result["error"]

    @pytest.mark.asyncio
    async def test_unknown_agent_type_returns_error(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool

        parent = _make_mock_parent()
        parent._last_context = {}
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=None)
        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)

        result = await tool_fn.coroutine(agent_type="nonexistent", objective="do something")
        assert result["success"] is False
        assert "not found" in result["error"]


class TestCreateBatchDelegateTool:
    def test_reuses_delegate_tool(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = create_delegate_task_tool(parent, lambda: [], catalog)

        with patch(
            "myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool.create_delegate_task_tool"
        ) as mock_create:
            batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
            mock_create.assert_not_called()

        assert batch.name == "batch_delegate_tasks_tool"

    def test_creates_delegate_when_not_provided(self):
        parent = _make_mock_parent()
        catalog = AsyncMock()
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog)
        assert batch.name == "batch_delegate_tasks_tool"

    @pytest.mark.asyncio
    async def test_batch_propagates_complexity_tier(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        delegate.coroutine = AsyncMock(return_value={"success": True, "result": "ok"})

        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [TaskRequest(agent_type="coder", objective="task", complexity_tier="reasoning")]
        result = await batch.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        delegate.coroutine.assert_awaited_once()
        assert delegate.coroutine.call_args.kwargs["complexity_tier"] == "reasoning"

    @pytest.mark.asyncio
    async def test_empty_tasks_returns_error(self):
        parent = _make_mock_parent()
        catalog = AsyncMock()
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog)

        result = await batch.coroutine(tasks=[], wait=True)
        assert result["success"] is False
        assert "No tasks" in result["error"]


class TestDelegateTaskExecution:
    """Tests for the core delegate_task execution paths (lines 201-259)."""

    @pytest.mark.asyncio
    async def test_successful_spawn_with_subagent_result(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", tools=("web_search"))
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        mock_result = SubAgentResult(task_id="abc", success=True, result="done", agent_type="coder")
        parent = _make_mock_parent()
        parent._last_context = {"session_id": "s1"}
        parent._spawn_child = AsyncMock(return_value=mock_result)

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="coder", objective="write code", wait=True)

        assert result["success"] is True
        assert result["result"] == "done"
        parent._spawn_child.assert_awaited_once()
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_successful_spawn_with_handover_state_formatting(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", tools=("web_search"))
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        mock_result = SubAgentResult(
            task_id="abc",
            success=True,
            result="done",
            agent_type="coder",
            handover_state=AgentHandoverState(task_completed=["A"], pending_todos=["B"]),
        )
        parent = _make_mock_parent()
        parent._last_context = {"session_id": "s1"}
        parent._spawn_child = AsyncMock(return_value=mock_result)

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="coder", objective="write code", wait=True)

        assert result["success"] is True
        # handover_state is now structured in result_dict via to_dict()
        assert result["handover_state"]["task_completed"] == ["A"]
        assert result["handover_state"]["pending_todos"] == ["B"]
        # No redundant text append in result string
        assert "Completed:" not in result["result"]
        parent._spawn_child.assert_awaited_once()
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_spawn_returns_dict_result(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(
            return_value={
                "success": True,
                "result": {"data": "value"},
                "task_id": "t1",
            }
        )

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="worker", objective="do work", wait=True)

        assert result["success"] is True
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_readonly_filters_blocked_tools(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(
            system_prompt="test", tools=("web_search", "write_file", "bash_run_command", "read_file")
        )
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        await tool_fn.coroutine(agent_type="worker", objective="read only", readonly=True)

        call_kwargs = parent._spawn_child.call_args[1]
        spawned_config = call_kwargs["config"]
        assert "write_file" in spawned_config.disallowed_tools
        assert "bash_run_command" in spawned_config.disallowed_tools
        assert "web_search" not in spawned_config.disallowed_tools
        assert "read_file" not in spawned_config.disallowed_tools
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_leaf_scope_sets_zero_depth(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", control_scope=ControlScope.LEAF, max_spawn_depth=5)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        await tool_fn.coroutine(agent_type="leaf", objective="leaf task")

        call_kwargs = parent._spawn_child.call_args[1]
        spawned_config = call_kwargs["config"]
        assert spawned_config.max_spawn_depth == 0
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_orchestrator_role_requires_trusted_control_scope(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", control_scope=ControlScope.LEAF, max_spawn_depth=5)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="leaf", objective="coordinate", role="orchestrator")

        assert result["success"] is False
        assert result["status"] == "policy_denied"
        assert result["reason"] == "role_escalation_denied"
        parent._spawn_child.assert_not_called()
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_orchestrator_role_binds_child_scoped_delegation_contract(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", control_scope=ControlScope.ORCHESTRATOR, max_spawn_depth=2)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent_manager = MagicMock()
        parent_manager.current_depth = 0
        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = parent_manager
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog, allowed_types=["worker", "reviewer"])
        await tool_fn.coroutine(agent_type="worker", objective="coordinate", role="orchestrator")

        call_kwargs = parent._spawn_child.call_args[1]
        spawned_config = call_kwargs["config"]
        assert spawned_config.control_scope == ControlScope.ORCHESTRATOR
        assert spawned_config.delegation_role == DelegateRole.ORCHESTRATOR
        assert spawned_config.delegation_catalog is catalog
        assert spawned_config.delegation_allowed_types == frozenset({"worker", "reviewer"})
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_orchestrator_role_denies_exhausted_spawn_depth(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", control_scope=ControlScope.ORCHESTRATOR, max_spawn_depth=1)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent_manager = MagicMock()
        parent_manager.current_depth = 1
        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = parent_manager
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="coordinator", objective="coordinate", role="orchestrator")

        assert result["success"] is False
        assert result["status"] == "policy_denied"
        assert result["reason"] == "max_spawn_depth_denied"
        parent._spawn_child.assert_not_called()
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_read_only_global_blocks_memory_write_tools(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", memory_isolation=MemoryIsolationPolicy.READ_ONLY_GLOBAL)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        await tool_fn.coroutine(agent_type="reader", objective="read task")

        call_kwargs = parent._spawn_child.call_args[1]
        spawned_config = call_kwargs["config"]
        assert "memory_save_tool" in spawned_config.disallowed_tools
        assert "memory_manage_tool" in spawned_config.disallowed_tools
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_context_propagation(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {
            "session_id": "sess-1",
            "user_id": "usr-1",
            "workspace_binding": "/ws/path",
        }
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": {}})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        await tool_fn.coroutine(agent_type="worker", objective="work", context={"extra": "data"})

        call_kwargs = parent._spawn_child.call_args[1]
        ctx = call_kwargs["context"]
        assert ctx["session_id"] == "sess-1"
        assert ctx["user_id"] == "usr-1"
        assert ctx["workspace_binding"] == "/ws/path"
        assert ctx["extra"] == "data"
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", timeout_seconds=30)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(side_effect=TimeoutError("timed out"))

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="slow", objective="slow task")

        assert result["success"] is False
        assert "Timeout" in result["error"]
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_generic_exception_handling(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(side_effect=RuntimeError("boom"))

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="buggy", objective="fail task")

        assert result["success"] is False
        assert "RuntimeError" in result["error"]
        assert "boom" in result["error"]
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_cached_result_returns_immediately(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _cache_key,
            _put_cache,
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {"session_id": "s1"}
        parent._spawn_child = AsyncMock()

        key = _cache_key("cached-agent", "cached task", None, session_id="s1")
        _put_cache(key, {"cached_data": True})

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="cached-agent", objective="cached task")

        assert result["cached"] is True
        assert result["success"] is True
        parent._spawn_child.assert_not_awaited()
        _result_cache.clear()


class TestBatchDelegateExecution:
    """Tests for batch_delegate_tasks execution paths (lines 320-343)."""

    @pytest.mark.asyncio
    async def test_batch_runs_concurrent_tasks(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value={"success": True, "result": "ok"})

        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="task 1"),
            TaskRequest(agent_type="coder", objective="task 2"),
        ]
        result = await batch.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        assert len(result["results"]) == 2
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_batch_handles_exceptions(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        call_count = 0

        async def _spawn_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first task failed")
            return {"success": True, "result": "ok"}

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(side_effect=_spawn_side_effect)

        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="worker", objective="fail task"),
            TaskRequest(agent_type="worker", objective="ok task"),
        ]
        result = await batch.coroutine(tasks=tasks, wait=True)

        assert result["success"] is False
        assert result["status"] == "partial_success"
        assert result["all_success"] is False
        assert result["completed_count"] == 1
        assert result["failed_count"] == 1
        assert result["failure_reasons"]
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_batch_race_mode_returns_first_winner(self):
        import asyncio

        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}

        async def slow_spawn(*args, **kwargs):
            await asyncio.sleep(0.5)
            return {"success": True, "result": "slow", "task_id": "slow"}

        async def fast_spawn(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"success": True, "result": "fast", "task_id": "fast", "_workspace_sync_back": AsyncMock()}

        # Mock delegate tool coroutine directly to simulate different speeds
        delegate = create_delegate_task_tool(parent, lambda: [], catalog)

        async def mock_delegate_coroutine(agent_type, objective, **kwargs):
            if objective == "slow task":
                return await slow_spawn()
            else:
                return await fast_spawn()

        delegate.coroutine = mock_delegate_coroutine

        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="slow task"),
            TaskRequest(agent_type="coder", objective="fast task"),
        ]

        # Run in race mode
        result = await batch.coroutine(tasks=tasks, wait=True, race=True)

        assert result["success"] is True
        assert result["race_winner"] is True
        assert result["result"]["result"] == "fast"
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_batch_race_mode_syncs_workspace(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}

        mock_sync_back = AsyncMock()

        async def fast_spawn(*args, **kwargs):
            return {"success": True, "result": "fast", "task_id": "fast", "_workspace_sync_back": mock_sync_back}

        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        delegate.coroutine = fast_spawn

        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="fast task"),
        ]

        # Run in race mode
        result = await batch.coroutine(tasks=tasks, wait=True, race=True)

        assert result["success"] is True
        mock_sync_back.assert_awaited_once()
        _result_cache.clear()
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        call_count = 0

        async def _spawn_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first task failed")
            return {"success": True, "result": "ok"}

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(side_effect=_spawn_side_effect)

        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="worker", objective="fail task"),
            TaskRequest(agent_type="worker", objective="ok task"),
        ]
        result = await batch.coroutine(tasks=tasks, wait=True)

        assert result["success"] is False
        assert result["status"] == "partial_success"
        assert result["all_success"] is False
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_race_budget_uses_configured_cost_admission(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test", max_cost_usd=0.2)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        budget_checker = MagicMock()
        budget_checker.get_remaining_budget.return_value = 0.1
        budget_checker.check_budget.return_value = BudgetStatus.EXCEEDED
        token_tracker = MagicMock()
        token_tracker.budget_checker = budget_checker

        parent = _make_mock_parent()
        parent._last_context = {}
        parent.token_tracker = token_tracker

        delegate = create_delegate_task_tool(parent, lambda: [], catalog)
        delegate.coroutine = AsyncMock(return_value={"success": True, "result": "ok"})
        batch = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="task 1"),
            TaskRequest(agent_type="coder", objective="task 2"),
        ]
        result = await batch.coroutine(tasks=tasks, wait=True, race=True)

        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["budget_admission"]["status"] == "downgraded"
        assert result["budget_admission"]["estimated_cost_usd"] == 0.4
        assert result["budget_admission"]["cost_status"] == "configured_max_cost"
        _result_cache.clear()


class TestDelegateTaskNonDictResult:
    """Test delegate_task when _spawn_child returns a non-dict, non-SubAgentResult."""

    @pytest.mark.asyncio
    async def test_spawn_returns_non_dict_non_result(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(return_value="unexpected string result")

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="worker", objective="odd result")

        assert result["success"] is False
        assert "unexpected string result" in result["error"]
        _result_cache.clear()

    @pytest.mark.asyncio
    async def test_spawn_dict_wait_false_no_cache(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _result_cache,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        _result_cache.clear()

        config = SubagentConfig(system_prompt="test")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._spawn_child = AsyncMock(
            return_value={
                "success": True,
                "result": {"data": "value"},
                "task_id": "t1",
            }
        )

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type="worker", objective="no cache test", wait=False)

        assert result["success"] is True
        assert len(_result_cache) == 0
        _result_cache.clear()


class TestUpdateDelegateDescription:
    @pytest.mark.asyncio
    async def test_updates_tool_description(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            update_delegate_task_description,
        )

        tool_mock = MagicMock()
        tool_mock.description = "old"

        catalog = AsyncMock()
        catalog.list_available = AsyncMock(return_value=[])

        await update_delegate_task_description(tool_mock, catalog)

        assert "Delegate tasks" in tool_mock.description


class TestPayloadDeadlock:
    @pytest.mark.asyncio
    async def test_deadlock_prevention(self):
        import hashlib
        import json

        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="test"))

        # Calculate the exact hash to simulate history
        agent_type = "worker"
        objective = "test deadlock"
        context = {"foo": "bar"}

        context_str = json.dumps(context, ensure_ascii=False, indent=2)
        task = objective + f"\n\nAdditional Context Data:\n```json\n{context_str}\n```"

        def _get_hashable_value(v):
            if isinstance(v, dict):
                return {str(k): _get_hashable_value(val) for k, val in v.items()}
            if isinstance(v, (list, tuple)):
                return [_get_hashable_value(val) for val in v]
            if isinstance(v, (int, float, str, bool, type(None))):
                return v
            return str(v)

        hashable_ctx = _get_hashable_value(context) if context else {}
        payload_str = json.dumps(
            {"type": str(agent_type).strip(), "task": str(task).strip(), "role": "leaf", "ctx": hashable_ctx},
            sort_keys=True,
            ensure_ascii=False
        )
        payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

        parent = _make_mock_parent()
        parent._last_context = {
            "subagent_payload_hashes": [payload_hash]
        }
        parent._spawn_child = AsyncMock()

        tool_fn = create_delegate_task_tool(parent, lambda: [], catalog)
        result = await tool_fn.coroutine(agent_type=agent_type, objective=objective, context=context)

        assert result["success"] is False
        assert "Safety interception" in result["error"]
        assert result["task_id"] == "deadlock-prevented"
        parent._spawn_child.assert_not_called()


# ---------------------------------------------------------------------------
# _inject_capacity_signal edge cases
# ---------------------------------------------------------------------------


class TestInjectCapacitySignal:
    def test_injects_capacity_when_manager_available(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _inject_capacity_signal,
        )

        agent = MagicMock()
        snap = MagicMock()
        snap.active_children = 2
        snap.max_children = 5
        snap.remaining_slots = 3
        snap.spawned_descendants = 4
        snap.max_descendants = 20
        snap.remaining_descendants = 16
        agent._subagent_manager.get_capacity_snapshot.return_value = snap

        result = _inject_capacity_signal({"success": True}, agent)
        assert "system_state" in result
        assert result["system_state"]["active_subagents"] == "2/5"
        assert result["system_state"]["remaining_slots"] == 3

    def test_swallows_exception_gracefully(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _inject_capacity_signal,
        )

        agent = MagicMock()
        agent._subagent_manager.get_capacity_snapshot.side_effect = RuntimeError(
            "boom"
        )

        result = _inject_capacity_signal({"success": True}, agent)
        assert result == {"success": True}
        assert "system_state" not in result

    def test_handles_missing_manager(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _inject_capacity_signal,
        )

        agent = MagicMock(spec=[])  # no _subagent_manager attribute

        result = _inject_capacity_signal({"success": True}, agent)
        assert result == {"success": True}


# ---------------------------------------------------------------------------
# _normalize_role edge cases
# ---------------------------------------------------------------------------


class TestNormalizeRole:
    def test_valid_string(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _normalize_role,
        )

        assert _normalize_role("leaf") == DelegateRole.LEAF
        assert _normalize_role("orchestrator") == DelegateRole.ORCHESTRATOR

    def test_enum_passthrough(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _normalize_role,
        )

        assert _normalize_role(DelegateRole.LEAF) == DelegateRole.LEAF
        assert _normalize_role(DelegateRole.ORCHESTRATOR) == DelegateRole.ORCHESTRATOR

    def test_invalid_string_defaults_to_leaf(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            _normalize_role,
        )

        assert _normalize_role("invalid_role") == DelegateRole.LEAF


# ---------------------------------------------------------------------------
# _resolve_model_name
# ---------------------------------------------------------------------------


class TestResolveModelName:
    def test_returns_config_model_first(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _resolve_model_name,
        )

        agent = MagicMock()
        assert _resolve_model_name(agent, "gpt-4") == "gpt-4"

    def test_falls_back_to_llm_model_name(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _resolve_model_name,
        )

        agent = MagicMock()
        agent.llm.model_name = "claude-3"
        assert _resolve_model_name(agent, None) == "claude-3"

    def test_falls_back_to_llm_model(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _resolve_model_name,
        )

        agent = MagicMock()
        agent.llm.model_name = None
        agent.llm.model = "gemini-pro"
        assert _resolve_model_name(agent, None) == "gemini-pro"

    def test_returns_none_when_no_model_found(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _resolve_model_name,
        )

        agent = MagicMock()
        agent.llm = MagicMock(spec=[])
        assert _resolve_model_name(agent, None) is None


# ---------------------------------------------------------------------------
# _estimate_prompt_tokens
# ---------------------------------------------------------------------------


class TestEstimatePromptTokens:
    def test_objective_only(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_prompt_tokens,
        )

        task = MagicMock()
        task.objective = "hello world"
        task.context_files = []
        task.context = None
        tokens = _estimate_prompt_tokens(task)
        assert tokens >= 1

    def test_with_context_files(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_prompt_tokens,
        )

        task = MagicMock()
        task.objective = "test"
        task.context_files = ["a.py", "b.py"]
        task.context = None
        tokens = _estimate_prompt_tokens(task)
        assert tokens >= 1

    def test_with_context_dict(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_prompt_tokens,
        )

        task = MagicMock()
        task.objective = "test"
        task.context_files = []
        task.context = {"key": "value"}
        tokens = _estimate_prompt_tokens(task)
        assert tokens >= 1


# ---------------------------------------------------------------------------
# _get_budget_checker
# ---------------------------------------------------------------------------


class TestGetBudgetChecker:
    def test_returns_token_tracker_budget_checker(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _get_budget_checker,
        )

        agent = MagicMock()
        checker = MagicMock()
        checker.check_budget = MagicMock()
        agent.token_tracker.budget_checker = checker
        assert _get_budget_checker(agent) is checker

    def test_falls_back_to_parent_budget_checker(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _get_budget_checker,
        )

        agent = MagicMock()
        agent.token_tracker = None
        checker = MagicMock()
        checker.check_budget = MagicMock()
        agent.budget_checker = checker
        assert _get_budget_checker(agent) is checker

    def test_returns_none_when_no_checker(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _get_budget_checker,
        )

        agent = MagicMock()
        agent.token_tracker = None
        agent.budget_checker = None
        assert _get_budget_checker(agent) is None


# ---------------------------------------------------------------------------
# _BatchBudgetAdmission
# ---------------------------------------------------------------------------


class TestBatchBudgetAdmission:
    def test_to_dict(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _BatchBudgetAdmission,
        )

        adm = _BatchBudgetAdmission(
            status="admitted",
            reason="within_budget",
            estimated_cost_usd=0.05,
            remaining_budget_usd=1.0,
            cost_status="known",
        )
        d = adm.to_dict()
        assert d["status"] == "admitted"
        assert d["reason"] == "within_budget"
        assert d["estimated_cost_usd"] == 0.05


# ---------------------------------------------------------------------------
# Handover state formatting edge cases
# ---------------------------------------------------------------------------


class TestHandoverStateFormatting:
    @pytest.mark.asyncio
    async def test_handover_with_dict_result(self):
        """When result is a dict, handover_state is in result_dict via to_dict()."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        handover = AgentHandoverState(
            task_completed=["step 1"],
            pending_todos=["step 2"],
            risks_or_notes=["watch out"],
        )
        sub_result = SubAgentResult(
            success=True,
            task_id="t1",
            agent_type="search",
            result={"data": "value"},
            handover_state=handover,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap
        parent._spawn_child = AsyncMock(return_value=sub_result)

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="test")
        )

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        result = await tool.ainvoke(
            {"agent_type": "search", "objective": "test handover dict", "wait": True}
        )
        assert result["success"] is True
        # handover_state is structured data in result_dict, not a text append
        assert result["handover_state"]["task_completed"] == ["step 1"]
        assert result["handover_state"]["risks_or_notes"] == ["watch out"]

    @pytest.mark.asyncio
    async def test_handover_with_none_result(self):
        """When result is None, handover_state is still in result_dict via to_dict()."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        handover = AgentHandoverState(
            task_completed=["step 1"],
            pending_todos=[],
            risks_or_notes=[],
        )
        sub_result = SubAgentResult(
            success=True,
            task_id="t2",
            agent_type="search",
            result=None,
            handover_state=handover,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap
        parent._spawn_child = AsyncMock(return_value=sub_result)

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="test")
        )

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        result = await tool.ainvoke(
            {"agent_type": "search", "objective": "test handover none", "wait": True}
        )
        assert result["success"] is True
        # handover_state is structured data in result_dict, not a text field
        assert result["handover_state"]["task_completed"] == ["step 1"]


# ---------------------------------------------------------------------------
# Context serialization failure
# ---------------------------------------------------------------------------


class TestContextSerialization:
    @pytest.mark.asyncio
    async def test_non_serializable_context_falls_back_to_str(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap

        sub_result = SubAgentResult(
            success=True, task_id="t1", agent_type="search", result="ok"
        )
        parent._spawn_child = AsyncMock(return_value=sub_result)

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="test")
        )

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        # Pass a context with a non-serializable value
        class NonSerializable:
            pass

        result = await tool.ainvoke(
            {
                "agent_type": "search",
                "objective": "test",
                "wait": True,
                "context": {"bad": NonSerializable()},
            }
        )
        # Should not crash, should fall back to str()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# FORMAT_ERROR handling
# ---------------------------------------------------------------------------


class TestFormatErrorHandling:
    @pytest.mark.asyncio
    async def test_format_error_returns_specific_message(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )
        from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap

        format_error = ValueError("Invalid JSON output from LLM")
        parent._spawn_child = AsyncMock(side_effect=format_error)

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="test")
        )

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        with patch(
            "myrm_agent_harness.toolkits.llms.errors.classifier.classify_error",
            return_value=ErrorKind.FORMAT_ERROR,
        ):
            result = await tool.ainvoke(
                {"agent_type": "search", "objective": "test format error", "wait": True}
            )
        assert result["success"] is False
        assert "format validation error" in result["error"]


# ---------------------------------------------------------------------------
# Memory manager reset failure
# ---------------------------------------------------------------------------


class TestMemoryManagerResetFailure:
    @pytest.mark.asyncio
    async def test_reset_failure_is_logged_not_raised(self):
        """If memory manager reset fails, it should log warning, not raise."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap

        sub_result = SubAgentResult(
            success=True, task_id="t1", agent_type="search", result="ok"
        )
        parent._spawn_child = AsyncMock(return_value=sub_result)

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(
            return_value=SubagentConfig(system_prompt="test")
        )

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        with (
            patch(
                "myrm_agent_harness.agent._skill_agent_context.get_memory_manager",
                return_value=MagicMock(),
            ),
            patch(
                "myrm_agent_harness.agent._skill_agent_context._memory_manager_var",
            ) as mock_var,
        ):
            mock_var.set.return_value = "token"
            mock_var.reset.side_effect = RuntimeError("reset failed")
            result = await tool.ainvoke(
                {"agent_type": "search", "objective": "test memory reset", "wait": True}
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _admit_race_budget edge cases
# ---------------------------------------------------------------------------


class TestAdmitRaceBudget:
    @pytest.mark.asyncio
    async def test_unavailable_when_config_none(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _admit_race_budget,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=None)

        tasks = [MagicMock()]
        tasks[0].agent_type = "search"

        result = await _admit_race_budget(
            parent_agent=parent, catalog=catalog, tasks=tasks
        )
        assert result.status == "unavailable"
        assert result.reason == "agent_config_unavailable"

    @pytest.mark.asyncio
    async def test_admitted_with_max_cost(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _admit_race_budget,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        config = SubagentConfig(system_prompt="test", max_cost_usd=0.10)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock()]
        tasks[0].agent_type = "search"

        result = await _admit_race_budget(
            parent_agent=parent, catalog=catalog, tasks=tasks
        )
        assert result.status == "admitted"
        assert result.estimated_cost_usd == 0.10

    @pytest.mark.asyncio
    async def test_downgraded_when_budget_exceeded(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _admit_race_budget,
        )

        checker = MagicMock()
        checker.check_budget.return_value = BudgetStatus.EXCEEDED
        checker.get_remaining_budget.return_value = 0.0

        parent = _make_mock_parent()
        parent.token_tracker = MagicMock()
        parent.token_tracker.budget_checker = checker

        config = SubagentConfig(system_prompt="test", max_cost_usd=0.10)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock()]
        tasks[0].agent_type = "search"

        result = await _admit_race_budget(
            parent_agent=parent, catalog=catalog, tasks=tasks
        )
        assert result.status == "downgraded"
        assert "budget_status_exceeded" in result.reason

    @pytest.mark.asyncio
    async def test_downgraded_when_remaining_budget_insufficient(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _admit_race_budget,
        )

        checker = MagicMock()
        checker.check_budget.return_value = BudgetStatus.OK
        checker.get_remaining_budget.return_value = 0.01

        parent = _make_mock_parent()
        parent.token_tracker = MagicMock()
        parent.token_tracker.budget_checker = checker

        config = SubagentConfig(system_prompt="test", max_cost_usd=1.0)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock()]
        tasks[0].agent_type = "search"

        result = await _admit_race_budget(
            parent_agent=parent, catalog=catalog, tasks=tasks
        )
        assert result.status == "downgraded"
        assert result.reason == "remaining_budget_insufficient"


# ---------------------------------------------------------------------------
# Policy denial event emission
# ---------------------------------------------------------------------------


class TestPolicyDenial:
    @pytest.mark.asyncio
    async def test_orchestrator_role_escalation_denied(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0

        catalog = AsyncMock()
        # Config with LEAF scope - cannot be used as ORCHESTRATOR
        config = SubagentConfig(
            system_prompt="test",
            control_scope=ControlScope.LEAF,
        )
        catalog.resolve = AsyncMock(return_value=config)

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        result = await tool.ainvoke(
            {
                "agent_type": "search",
                "objective": "test",
                "wait": False,
                "role": "orchestrator",
            }
        )
        assert result["success"] is False
        assert "not allowed to run as an orchestrator" in result["error"]


# ---------------------------------------------------------------------------
# Batch empty tasks
# ---------------------------------------------------------------------------


class TestBatchEmptyTasks:
    @pytest.mark.asyncio
    async def test_empty_tasks_returns_error(self):
        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap

        catalog = AsyncMock()
        tool = _create_batch_delegate_tasks_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        result = await tool.ainvoke({"tasks": [], "wait": True})
        assert result["success"] is False
        assert "No tasks" in result["error"]


# ---------------------------------------------------------------------------
# Readonly mode with context
# ---------------------------------------------------------------------------


class TestReadonlyMode:
    @pytest.mark.asyncio
    async def test_readonly_appends_hint_to_system_prompt(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            create_delegate_task_tool,
        )

        parent = _make_mock_parent()
        parent._last_context = {}
        parent._subagent_manager = MagicMock()
        parent._subagent_manager.current_depth = 0
        snap = MagicMock()
        snap.active_children = 0
        snap.max_children = 5
        snap.remaining_slots = 5
        snap.spawned_descendants = 0
        snap.max_descendants = 20
        snap.remaining_descendants = 20
        parent._subagent_manager.get_capacity_snapshot.return_value = snap

        sub_result = SubAgentResult(
            success=True, task_id="t1", agent_type="search", result="ok"
        )
        parent._spawn_child = AsyncMock(return_value=sub_result)

        config = SubagentConfig(system_prompt="You are helpful.")
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tool = create_delegate_task_tool(
            parent_agent=parent,
            tool_registry_getter=lambda: [],
            catalog=catalog,
        )

        await tool.ainvoke(
            {
                "agent_type": "search",
                "objective": "test readonly mode",
                "wait": True,
                "readonly": True,
            }
        )

        # Verify spawn_child was called with readonly hint in system_prompt
        call_kwargs = parent._spawn_child.call_args
        passed_config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert "READONLY MODE" in passed_config.system_prompt


# ---------------------------------------------------------------------------
# _estimate_batch_cost
# ---------------------------------------------------------------------------


class TestEstimateBatchCost:
    @pytest.mark.asyncio
    async def test_returns_admitted_with_configured_max_cost(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        config = SubagentConfig(system_prompt="test", max_cost_usd=0.25)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="coder"), MagicMock(agent_type="coder")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "admitted"
        assert result.reason == "cost_estimated"
        assert result.estimated_cost_usd == 0.50
        assert result.cost_status == "configured_max_cost"

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_agent_config_missing(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=None)

        tasks = [MagicMock(agent_type="nonexistent")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "unavailable"
        assert result.reason == "agent_config_unavailable"

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_budget_tokens_unconfigured(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        config = SubagentConfig(system_prompt="test", budget_tokens=None, max_cost_usd=None)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="worker")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "unavailable"
        assert result.reason == "task_budget_unconfigured"

    @pytest.mark.asyncio
    async def test_includes_remaining_budget(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        checker = MagicMock()
        checker.get_remaining_budget.return_value = 5.0

        parent = _make_mock_parent()
        parent.token_tracker = MagicMock()
        parent.token_tracker.budget_checker = checker

        config = SubagentConfig(system_prompt="test", max_cost_usd=0.10)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="coder")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "admitted"
        assert result.remaining_budget_usd == 5.0
        assert result.estimated_cost_usd == 0.10

    @pytest.mark.asyncio
    async def test_does_not_make_policy_decisions(self):
        """_estimate_batch_cost must NOT downgrade — that's _admit_race_budget's job."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        checker = MagicMock()
        checker.get_remaining_budget.return_value = 0.01
        checker.check_budget.return_value = BudgetStatus.EXCEEDED

        parent = _make_mock_parent()
        parent.token_tracker = MagicMock()
        parent.token_tracker.budget_checker = checker

        config = SubagentConfig(system_prompt="test", max_cost_usd=10.0)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="expensive")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "admitted"
        assert result.estimated_cost_usd == 10.0
        assert result.remaining_budget_usd == 0.01


# ---------------------------------------------------------------------------
# Batch cost approval interrupt
# ---------------------------------------------------------------------------


class TestBatchCostApproval:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_triggers_interrupt_when_cost_exceeds_threshold(
        self, mock_estimate, mock_interrupt, mock_runner
    ):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted",
            reason="cost_estimated",
            estimated_cost_usd=1.50,
            remaining_budget_usd=10.0,
            cost_status="configured_max_cost",
        )
        mock_interrupt.return_value = {"approved": True}
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="task 1"),
            TaskRequest(agent_type="coder", objective="task 2"),
        ]
        await tool.coroutine(tasks=tasks, wait=True)

        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args[0][0]
        assert payload["action_type"] == "batch_cost_approval"
        assert payload["estimated_cost_usd"] == 1.50
        assert payload["task_count"] == 2

    @pytest.mark.asyncio
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_user_rejection_stops_execution(self, mock_estimate, mock_interrupt):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted",
            reason="cost_estimated",
            estimated_cost_usd=2.00,
        )
        mock_interrupt.return_value = {"approved": False}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="expensive 1"),
            TaskRequest(agent_type="coder", objective="expensive 2"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is False
        assert result["status"] == "user_rejected"
        assert result["reason"] == "batch_cost_rejected_by_user"
        assert result["estimated_cost_usd"] == 2.00

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_skips_approval_when_cost_below_threshold(self, mock_estimate, mock_runner):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted",
            reason="cost_estimated",
            estimated_cost_usd=0.10,
        )
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="cheap 1"),
            TaskRequest(agent_type="coder", objective="cheap 2"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        mock_runner.assert_called_once()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_skips_approval_when_estimation_unavailable(self, mock_estimate, mock_runner):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="unavailable",
            reason="model_cost_unavailable",
        )
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)

        tasks = [
            TaskRequest(agent_type="coder", objective="task 1"),
            TaskRequest(agent_type="coder", objective="task 2"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        mock_runner.assert_called_once()


# ---------------------------------------------------------------------------
# Batch cost approval edge cases
# ---------------------------------------------------------------------------


class TestBatchCostApprovalEdgeCases:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_list_decision_approved(self, mock_estimate, mock_interrupt, mock_runner):
        """Decision returned as list [{"approved": True}] should proceed."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted", reason="cost_estimated",
            estimated_cost_usd=1.00, cost_status="configured_max_cost",
        )
        mock_interrupt.return_value = [{"approved": True}]
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="a"),
            TaskRequest(agent_type="coder", objective="b"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        mock_interrupt.assert_called_once()

    @pytest.mark.asyncio
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_list_decision_rejected(self, mock_estimate, mock_interrupt):
        """Decision returned as list [{"approved": False}] should reject."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted", reason="cost_estimated",
            estimated_cost_usd=2.00,
        )
        mock_interrupt.return_value = [{"approved": False}]

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="a"),
            TaskRequest(agent_type="coder", objective="b"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is False
        assert result["status"] == "user_rejected"

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_single_task_skips_cost_check(self, mock_estimate, mock_runner):
        """A single task should skip cost approval entirely."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [TaskRequest(agent_type="coder", objective="solo")]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        mock_estimate.assert_not_called()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_cost_estimation_exception_proceeds(self, mock_estimate, mock_runner):
        """If _estimate_batch_cost throws, execution continues without approval."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.side_effect = RuntimeError("network error")
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="a"),
            TaskRequest(agent_type="coder", objective="b"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True
        mock_runner.assert_called_once()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_remaining_budget_none_in_payload(self, mock_estimate, mock_interrupt, mock_runner):
        """When remaining_budget_usd is None, payload should have null."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted", reason="cost_estimated",
            estimated_cost_usd=0.80, remaining_budget_usd=None,
        )
        mock_interrupt.return_value = {"approved": True}
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="a"),
            TaskRequest(agent_type="coder", objective="b"),
        ]
        await tool.coroutine(tasks=tasks, wait=True)

        payload = mock_interrupt.call_args[0][0]
        assert payload["remaining_budget_usd"] is None

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("langgraph.types.interrupt")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_tournament_flag_in_interrupt_payload(self, mock_estimate, mock_interrupt, mock_runner):
        """Tournament mode should be reflected in interrupt payload."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="admitted", reason="cost_estimated",
            estimated_cost_usd=1.00,
        )
        mock_interrupt.return_value = {"approved": True}
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="t1"),
            TaskRequest(agent_type="coder", objective="t2"),
        ]
        await tool.coroutine(tasks=tasks, wait=True, tournament=True)

        payload = mock_interrupt.call_args[0][0]
        assert payload["tournament"] is True
        assert payload["race"] is False


# ---------------------------------------------------------------------------
# Batch size exceeded
# ---------------------------------------------------------------------------


class TestBatchSizeExceeded:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_exceeds_default_max_batch(self, mock_estimate):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _DEFAULT_MAX_BATCH_TASKS,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective=f"task {i}")
            for i in range(_DEFAULT_MAX_BATCH_TASKS + 1)
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is False
        assert result["status"] == "budget_exceeded"
        assert result["reason"] == "batch_size_exceeded"
        mock_estimate.assert_not_called()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_custom_max_batch_from_parent_config(self, mock_estimate, mock_runner):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_estimate.return_value = _BatchBudgetAdmission(
            status="unavailable", reason="skip",
        )
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        parent_cfg = SubagentConfig(system_prompt="test", max_batch_size=10)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=parent_cfg)
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(
            parent, lambda: [], catalog, parent_type="orchestrator", delegate_tool=delegate,
        )
        tasks = [
            TaskRequest(agent_type="coder", objective=f"task {i}") for i in range(8)
        ]
        result = await tool.coroutine(tasks=tasks, wait=True)

        assert result["success"] is True


# ---------------------------------------------------------------------------
# _estimate_batch_cost edge cases (budget_tokens path)
# ---------------------------------------------------------------------------


class TestEstimateBatchCostBudgetTokensPath:
    @pytest.mark.asyncio
    async def test_budget_tokens_with_known_cost(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None
        parent.llm = MagicMock()
        parent.llm.model_name = "gpt-4"

        config = SubagentConfig(system_prompt="test", budget_tokens=10000, max_cost_usd=None, model=None)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="coder", objective="hello world", context_files=[], context=None)]

        with patch(
            "myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget.compute_cost_by_tokens"
        ) as mock_cost:
            mock_result = MagicMock()
            mock_result.is_known = True
            mock_result.usd = 0.05
            mock_result.status = MagicMock()
            mock_result.status.value = "estimated"
            mock_cost.return_value = mock_result

            result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "admitted"
        assert result.estimated_cost_usd == 0.05
        assert result.cost_status == "estimated"

    @pytest.mark.asyncio
    async def test_budget_tokens_with_unknown_model_cost(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None
        parent.llm = MagicMock()
        parent.llm.model_name = "unknown-model-xyz"

        config = SubagentConfig(system_prompt="test", budget_tokens=5000, max_cost_usd=None, model=None)
        catalog = AsyncMock()
        catalog.resolve = AsyncMock(return_value=config)

        tasks = [MagicMock(agent_type="worker", objective="x", context_files=[], context=None)]

        with patch(
            "myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget.compute_cost_by_tokens"
        ) as mock_cost:
            mock_result = MagicMock()
            mock_result.is_known = False
            mock_cost.return_value = mock_result

            result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "unavailable"
        assert result.reason == "model_cost_unavailable"

    @pytest.mark.asyncio
    async def test_mixed_agent_types_accumulates_costs(self):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_budget import (
            _estimate_batch_cost,
        )

        parent = _make_mock_parent()
        parent.token_tracker = None
        parent.budget_checker = None

        config_a = SubagentConfig(system_prompt="test", max_cost_usd=0.10)
        config_b = SubagentConfig(system_prompt="test", max_cost_usd=0.30)
        catalog = AsyncMock()

        async def resolve(agent_type):
            return config_a if agent_type == "a" else config_b

        catalog.resolve = AsyncMock(side_effect=resolve)

        tasks = [MagicMock(agent_type="a"), MagicMock(agent_type="b"), MagicMock(agent_type="a")]

        result = await _estimate_batch_cost(parent_agent=parent, catalog=catalog, tasks=tasks)

        assert result.status == "admitted"
        assert result.estimated_cost_usd == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Tournament bracket edge cases
# ---------------------------------------------------------------------------


class TestTournamentBracketEdgeCases:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_no_successful_candidates(self, mock_merge):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        parent = _make_mock_parent()
        results = [
            {"task_id": "1", "result": "fail", "success": False},
            {"task_id": "2", "result": "fail", "success": False},
        ]

        result = await _run_tournament_bracket(parent, results, "criteria")

        assert result["success"] is False
        assert "No successful tasks" in result["error"]
        mock_merge.assert_not_called()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_single_successful_candidate_wins(self, mock_merge):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        mock_merge.return_value = {}
        parent = _make_mock_parent()
        results = [
            {"task_id": "1", "result": "only winner", "success": True},
            {"task_id": "2", "result": "fail", "success": False},
        ]

        result = await _run_tournament_bracket(parent, results, "criteria")

        assert result["success"] is True
        assert result["tournament_winner"] is True
        assert result["result"]["result"] == "only winner"
        parent.llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_judge_picks_candidate_b(self, mock_merge):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        mock_merge.return_value = {}
        parent = _make_mock_parent()
        mock_response = MagicMock()
        mock_response.content = "B\nCandidate B is much better."
        parent.llm.ainvoke = AsyncMock(return_value=mock_response)

        results = [
            {"task_id": "1", "result": "Output A", "success": True},
            {"task_id": "2", "result": "Output B", "success": True},
        ]

        result = await _run_tournament_bracket(parent, results, "Best output")

        assert result["success"] is True
        assert result["result"]["result"] == "Output B"

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_judge_error_falls_back_to_candidate_a(self, mock_merge):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        mock_merge.return_value = {}
        parent = _make_mock_parent()
        parent.llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))

        results = [
            {"task_id": "1", "result": "Output A", "success": True},
            {"task_id": "2", "result": "Output B", "success": True},
        ]

        result = await _run_tournament_bracket(parent, results, "Best output")

        assert result["success"] is True
        assert result["result"]["result"] == "Output A"

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_no_llm_on_parent_falls_back_to_first(self, mock_merge):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        mock_merge.return_value = {}
        parent = MagicMock(spec=[])

        results = [
            {"task_id": "1", "result": "Output A", "success": True},
            {"task_id": "2", "result": "Output B", "success": True},
        ]

        result = await _run_tournament_bracket(parent, results, "Best output")

        assert result["success"] is True
        assert result["result"]["result"] == "Output A"

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.workspace_coordination.batch_merge.merge_batch_workspace_sync_backs")
    async def test_three_candidates_bracket(self, mock_merge):
        """Odd number of candidates: one gets a bye to next round."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _run_tournament_bracket,
        )

        mock_merge.return_value = {}
        parent = _make_mock_parent()

        call_count = 0

        async def mock_ainvoke(messages):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.content = "B"
            return mock_resp

        parent.llm.ainvoke = mock_ainvoke

        results = [
            {"task_id": "1", "result": "A", "success": True},
            {"task_id": "2", "result": "B", "success": True},
            {"task_id": "3", "result": "C", "success": True},
        ]

        result = await _run_tournament_bracket(parent, results, "Best")

        assert result["success"] is True
        assert result["tournament_winner"] is True
        assert call_count >= 2


# ---------------------------------------------------------------------------
# Race mode budget admission exception handling
# ---------------------------------------------------------------------------


class TestRaceModeBudgetException:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.parallel.runner.run_parallel_task_requests")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._admit_race_budget")
    @patch("myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch._estimate_batch_cost")
    async def test_budget_exception_creates_unavailable_admission(
        self, mock_estimate, mock_admit, mock_runner
    ):
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            _BatchBudgetAdmission,
        )
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import (
            TaskRequest,
        )

        mock_admit.side_effect = RuntimeError("budget check crashed")
        mock_estimate.return_value = _BatchBudgetAdmission(
            status="unavailable", reason="skip",
        )
        mock_runner.return_value = {"success": True, "results": []}

        parent = _make_mock_parent()
        catalog = AsyncMock()
        delegate = MagicMock()

        tool = _create_batch_delegate_tasks_tool(parent, lambda: [], catalog, delegate_tool=delegate)
        tasks = [
            TaskRequest(agent_type="coder", objective="a"),
            TaskRequest(agent_type="coder", objective="b"),
        ]
        result = await tool.coroutine(tasks=tasks, wait=True, race=True)

        assert result["success"] is True
        mock_runner.assert_called_once()


# ---------------------------------------------------------------------------
# _batch_summary
# ---------------------------------------------------------------------------


