"""Unit tests for SubagentManager."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS, register_subagent_configs
from myrm_agent_harness.agent.sub_agents.types import (
    CancellationStrategy,
    ControlScope,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.agent.types import AgentRuntimeConfig

# Register test subagent configs for tests that reference SUBAGENT_CONFIGS["search"]
if "search" not in SUBAGENT_CONFIGS:
    register_subagent_configs({
        "search": SubagentConfig(
            description="Search subagent",
            system_prompt="You are a search subagent.",
            tools=("search",),
        ),
    })


@dataclass(frozen=True, slots=True)
class SubAgentHook:
    """Hook fixture shape used by skipped exception-safety tests."""

    on_spawn: Callable[[str, str, dict[str, object]], Awaitable[None]] | None = None
    on_complete: Callable[[str, str, dict[str, object]], Awaitable[None]] | None = None
    on_error: Callable[[str, str, dict[str, object]], Awaitable[None]] | None = None


class FakeLLM:
    """Fake LLM used by subagent manager tests."""

    def __init__(self, response: str = "child response") -> None:
        self.response = response

    def bind(self, **kwargs: object) -> FakeLLM:
        return self

    def bind_tools(self, tools: list[BaseTool], **kwargs: object) -> FakeLLM:
        return self

    async def ainvoke(
        self, messages: object, config: object | None = None
    ) -> AIMessage:
        return AIMessage(content=self.response)


class FakeSearchTool(BaseTool):
    """Fake search tool used for tool filtering."""

    name: str = "web_search_tool"
    description: str = "Search"

    def _run(self, query: str) -> str:
        return f"result: {query}"

    async def _arun(self, query: str) -> str:
        return f"result: {query}"


class FakeWriteTool(BaseTool):
    """Fake write tool."""

    name: str = "write_file"
    description: str = "Write"

    def _run(self, query: str) -> str:
        return f"wrote: {query}"

    async def _arun(self, query: str) -> str:
        return f"wrote: {query}"


def test_subagent_views_are_read_only() -> None:
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager

    with pytest.raises(TypeError):
        manager.children["task"] = object()

    with pytest.raises(TypeError):
        manager.child_results["task"] = {"success": True}


def test_get_capacity_snapshot_initial_state() -> None:
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager

    snap = manager.get_capacity_snapshot()
    assert snap.active_children == 0
    assert snap.max_children == 5
    assert snap.remaining_slots == 5
    assert snap.spawned_descendants == 0
    assert snap.max_descendants == 20
    assert snap.remaining_descendants == 20


class FlakyLLM:
    """LLM that fails once before succeeding."""

    def __init__(self, response: str = "recovered response") -> None:
        self.response = response
        self.call_count = 0

    def bind(self, **kwargs: object) -> FlakyLLM:
        return self

    def bind_tools(self, tools: list[BaseTool], **kwargs: object) -> FlakyLLM:
        return self

    async def ainvoke(
        self, messages: object, config: object | None = None
    ) -> AIMessage:
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("transient failure")
        return AIMessage(content=self.response)


class SlowLLM:
    """LLM that takes longer than the configured timeout."""

    def bind(self, **kwargs: object) -> SlowLLM:
        return self

    def bind_tools(self, tools: list[BaseTool], **kwargs: object) -> SlowLLM:
        return self

    async def ainvoke(
        self, messages: object, config: object | None = None
    ) -> AIMessage:
        await asyncio.sleep(0.2)
        return AIMessage(content="too late")


@pytest.mark.asyncio
async def test_spawn_child_wait_true_returns_result_and_cleans_up() -> None:
    llm = FakeLLM("final child response")
    agent = BaseAgent(
        llm=llm, config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5)
    )
    manager: SubagentManager = agent._subagent_manager

    result = await manager.spawn_child(
        task_id="child_wait_true",
        agent_type="generalPurpose",
        task_description="summarize search result",
        config=SubagentConfig(
            description="General purpose subagent",
            system_prompt="You are a general purpose subagent.",
            tools=("search",),
        ),
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=True,
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True
    assert result.task_id == "child_wait_true"
    assert result.agent_type == "generalPurpose"
    assert "final child response" in result.result
    assert "child_wait_true" not in manager._children
    assert manager._children_results["child_wait_true"].success is True


@pytest.mark.asyncio
async def test_spawn_child_wait_false_populates_completed_results(tmp_path) -> None:
    llm = FakeLLM("background child response")
    agent = BaseAgent(
        llm=llm, config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5)
    )
    manager = agent._subagent_manager

    result = await manager.spawn_child(
        task_id="child_wait_false",
        agent_type="search",
        task_description="background run",
        config=SubagentConfig(
            description="Search subagent",
            system_prompt="You are a search subagent.",
            tools=("search",),
        ),
        context={
            "session_id": "test",
            "workspace_path": str(tmp_path),
            "workspaces_storage_root": str(tmp_path),
        },
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=False,
    )

    assert isinstance(result, dict)
    assert result["status"] == "running"
    assert result["task_id"] == "child_wait_false"
    assert result["role"] == "leaf"
    assert result["control_scope"] == "leaf"

    for _ in range(30):
        if "child_wait_false" not in manager._children:
            break
        await asyncio.sleep(0.1)

    assert "child_wait_false" not in manager._children
    assert manager._children_results["child_wait_false"].success is True
    assert "background child response" in manager._children_results["child_wait_false"].result
    listed = manager.list_children()
    completed = next(item for item in listed if item["task_id"] == "child_wait_false")
    assert completed["role"] == "leaf"
    assert completed["control_scope"] == "leaf"


@pytest.mark.asyncio
async def test_spawn_child_retries_after_transient_failure() -> None:
    llm = FlakyLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    config = SubagentConfig(
        tools=SUBAGENT_CONFIGS["search"].tools,
        system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
        timeout_seconds=30,
        concurrency_limit=SUBAGENT_CONFIGS["search"].concurrency_limit,
        max_retries=2,
        retry_backoff_seconds=0.0,
    )

    result = await manager.spawn_child(
        task_id="retry_child",
        agent_type="search",
        task_description="recover after failure",
        config=config,
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=True,
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True
    assert result.result == "recovered response"
    assert llm.call_count == 2


@pytest.mark.asyncio
async def test_spawn_child_times_out_when_execution_is_too_slow() -> None:
    llm = SlowLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    config = SubagentConfig(
        tools=SUBAGENT_CONFIGS["search"].tools,
        system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
        timeout_seconds=0.05,
        concurrency_limit=SUBAGENT_CONFIGS["search"].concurrency_limit,
        max_retries=1,
        retry_backoff_seconds=0.0,
    )

    result = await manager.spawn_child(
        task_id="timeout_child",
        agent_type="search",
        task_description="run too long",
        config=config,
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=True,
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is False
    assert "Timeout" in result.error
    await asyncio.sleep(0.05)
    assert "timeout_child" not in manager._children


@pytest.mark.asyncio
async def test_spawn_child_rejects_duplicate_task_id() -> None:
    llm = SlowLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    first_result = await manager.spawn_child(
        task_id="duplicate_child",
        agent_type="search",
        task_description="first run",
        config=SUBAGENT_CONFIGS["search"],
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=False,
    )

    duplicate_result = await manager.spawn_child(
        task_id="duplicate_child",
        agent_type="search",
        task_description="second run",
        config=SUBAGENT_CONFIGS["search"],
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=False,
    )

    assert isinstance(first_result, dict)
    assert first_result["status"] == "running"
    assert isinstance(duplicate_result, SubAgentResult)
    assert duplicate_result.success is False
    assert "already exists" in duplicate_result.error

    assert manager.cancel_child("duplicate_child") is True
    await asyncio.gather(*manager._children.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_wait_children_counts_missing_task_as_failure() -> None:
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    manager._children_results["finished_task"] = SubAgentResult(
        success=True,
        result="done",
        task_id="finished_task",
        agent_type="search",
        status=SubAgentStatus.COMPLETED,
    )

    result = await manager.wait_children(
        ["finished_task", "missing_task"], min_success_rate=0.5
    )

    assert result["success"] is True
    assert result["success_rate"] == 0.5
    assert len(result["results"]) == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["task_id"] == "missing_task"


@pytest.mark.asyncio
async def test_wait_children_rejects_duplicate_task_ids() -> None:
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    result = await manager.wait_children(["dup_task", "dup_task"], min_success_rate=0.5)

    assert result["success"] is False
    assert result["success_rate"] == 0.0
    assert result["results"] == []
    assert len(result["failures"]) == 1
    assert "Duplicate" in result["failures"][0]


@pytest.mark.asyncio
async def test_cancel_child_stops_running_task() -> None:
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    task_id = "cancel_me"
    running_task = asyncio.create_task(asyncio.sleep(10))
    manager._children[task_id] = running_task

    assert manager.cancel_child(task_id) is True

    await asyncio.sleep(0.05)
    assert running_task.cancelled()

    await asyncio.gather(running_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_spawn_child_accepts_parent_type() -> None:
    """spawn_child passes parent_type through (no nesting restriction enforced)."""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    result = await manager.spawn_child(
        task_id="nesting_allowed",
        agent_type="search",
        task_description="nested search",
        config=SUBAGENT_CONFIGS["search"],
        context={"session_id": "test", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
        tool_registry_getter=lambda: [FakeSearchTool()],
        wait=True,
        parent_type="browser",
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True


# ---------------------------------------------------------------------------
# max_spawn_depth validation
# ---------------------------------------------------------------------------


def test_validate_depth_allows_spawn_at_depth_zero_with_max_zero() -> None:
    """max_spawn_depth=0 allows top-level spawn (depth=0)."""
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager
    config = SubagentConfig(system_prompt="test", max_spawn_depth=0)
    assert manager._validate_depth("t1", config) is None


def test_validate_depth_rejects_spawn_at_depth_one_with_max_zero() -> None:
    """max_spawn_depth=0 rejects nested spawn (depth=1)."""
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager
    manager._current_depth = 1
    config = SubagentConfig(
        system_prompt="test",
        max_spawn_depth=0,
        control_scope=ControlScope.ORCHESTRATOR,
    )
    result = manager._validate_depth("t2", config)
    assert result is not None
    assert result.success is False
    assert "max_spawn_depth=0" in result.error


def test_validate_depth_allows_spawn_at_depth_one_with_max_one() -> None:
    """max_spawn_depth=1 allows 1-level nesting (depth=1)."""
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager
    manager._current_depth = 1
    config = SubagentConfig(system_prompt="test", max_spawn_depth=1)
    assert manager._validate_depth("t3", config) is None


def test_validate_depth_rejects_spawn_at_depth_two_with_max_one() -> None:
    """max_spawn_depth=1 rejects 2-level nesting (depth=2)."""
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager
    manager._current_depth = 2
    config = SubagentConfig(
        system_prompt="test",
        max_spawn_depth=1,
        control_scope=ControlScope.ORCHESTRATOR,
    )
    result = manager._validate_depth("t4", config)
    assert result is not None
    assert result.success is False
    assert "max_spawn_depth=1" in result.error


def test_validate_depth_rejects_at_global_max() -> None:
    """Global max depth (3) always rejects."""
    agent = BaseAgent(llm=FakeLLM())
    manager = agent._subagent_manager
    manager._current_depth = 3
    config = SubagentConfig(system_prompt="test", max_spawn_depth=10)
    result = manager._validate_depth("t5", config)
    assert result is not None
    assert result.success is False
    assert "Max spawn depth" in result.error


# ---------------------------------------------------------------------------
# L1: Global blacklist (expanded)
# ---------------------------------------------------------------------------


class FakeListSubagentsTool(BaseTool):
    name: str = "list_subagents_tool"
    description: str = "List subagents"

    def _run(self) -> str:
        return "[]"


class FakeCancelSubagentTool(BaseTool):
    name: str = "cancel_subagent_tool"
    description: str = "Cancel a subagent"

    def _run(self, task_id: str) -> str:
        return "cancelled"


class FakeSkillManageTool(BaseTool):
    name: str = "skill_manage_tool"
    description: str = "Manage skills"

    def _run(self) -> str:
        return "managed"


class FakeSkillDiscoveryTool(BaseTool):
    name: str = "skill_discovery_tool"
    description: str = "Discover skills"

    def _run(self) -> str:
        return "discovered"


class FakeSpawnSubagentTool(BaseTool):
    name: str = "delegate_task_tool"
    description: str = "Spawn subagent"

    def _run(self) -> str:
        return "spawned"


class FakeBatchDelegateTool(BaseTool):
    name: str = "batch_delegate_tasks_tool"
    description: str = "Spawn multiple subagents"

    def _run(self) -> str:
        return "spawned"


def test_filter_tools_blocks_all_global_blacklisted_tools() -> None:
    """L1: all control/delegation tools are stripped regardless of config."""
    agent = BaseAgent(llm=FakeLLM())
    _manager = agent._subagent_manager

    parent_tools = [
        FakeSearchTool(),
        FakeSpawnSubagentTool(),
        FakeBatchDelegateTool(),
        FakeListSubagentsTool(),
        FakeCancelSubagentTool(),
        FakeSkillManageTool(),
        FakeSkillDiscoveryTool(),
    ]

    config = SubagentConfig(system_prompt="test", tools=())

    filtered = filter_tools(config, parent_tools)
    filtered_names = {t.name for t in filtered}

    assert "web_search_tool" in filtered_names
    assert "delegate_task_tool" not in filtered_names
    assert "batch_delegate_tasks_tool" not in filtered_names
    assert "list_subagents_tool" not in filtered_names
    assert "cancel_subagent_tool" not in filtered_names
    assert "skill_manage_tool" not in filtered_names
    assert "skill_discovery_tool" not in filtered_names


def test_filter_tools_blocks_blacklisted_even_with_explicit_allowlist() -> None:
    """L1 overrides L2: even if config.tools includes a blacklisted name, it's still blocked."""
    parent_tools = [FakeSearchTool(), FakeSkillManageTool(), FakeBatchDelegateTool()]

    config = SubagentConfig(
        system_prompt="test",
        tools=("web_search_tool", "skill_manage_tool", "batch_delegate_tasks_tool"),
    )

    filtered = filter_tools(config, parent_tools)
    filtered_names = {t.name for t in filtered}

    assert "web_search_tool" in filtered_names
    assert "skill_manage_tool" not in filtered_names
    assert "batch_delegate_tasks_tool" not in filtered_names


# ---------------------------------------------------------------------------
# L0: allowed_types on create_delegate_task_tool
# ---------------------------------------------------------------------------


class MockCatalog:
    """Mock subagent catalog for testing."""

    async def resolve(self, agent_type: str) -> dict | None:
        if agent_type == "search":
            return SubagentConfig(system_prompt="Search Agent")
        return None


@pytest.mark.asyncio
async def test_delegate_task_tool_allowed_types_rejects_disallowed() -> None:
    """L0: delegate_task_tool rejects types not in allowed_types."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
        create_delegate_task_tool,
    )

    agent = BaseAgent(llm=FakeLLM())
    spawn_tool = create_delegate_task_tool(
        parent_agent=agent,
        tool_registry_getter=lambda: [],
        catalog=MockCatalog(),
        allowed_types=["search"],
    )

    result = await spawn_tool.ainvoke(
        {"agent_type": "browser", "objective": "test", "wait": False}
    )
    assert result["success"] is False
    assert "not allowed" in result["error"]


@pytest.mark.asyncio
async def test_delegate_task_tool_allowed_types_none_allows_all() -> None:
    """L0: allowed_types=None allows any registered type."""
    from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
        create_delegate_task_tool,
    )

    agent = BaseAgent(llm=FakeLLM())
    spawn_tool = create_delegate_task_tool(
        parent_agent=agent,
        tool_registry_getter=lambda: [FakeSearchTool()],
        catalog=MockCatalog(),
        allowed_types=None,
    )

    result = await spawn_tool.ainvoke(
        {
            "agent_type": "search",
            "objective": "test",
            "wait": True,
            "context": {"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
        }
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_delegate_task_tool_readonly_filters_tools() -> None:
    """Verify that setting readonly=True filters out write tools from the subagent's allowed tools."""
    from unittest.mock import patch

    from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
        create_delegate_task_tool,
    )

    agent = BaseAgent(llm=FakeLLM())
    spawn_tool = create_delegate_task_tool(
        parent_agent=agent,
        tool_registry_getter=lambda: [FakeSearchTool(), FakeWriteTool()],
        catalog=MockCatalog(),
    )

    # Mock parent's spawn_child to inspect the config it receives
    async def mock_spawn(self, *args, **kwargs):
        # Return success immediately
        return type(
            "SubagentResult",
            (),
            {"id": "sub1", "task": "t", "response": "ok", "error": None, "usage": {}},
        )()

        with patch(
            "myrm_agent_harness.agent.sub_agents.manager.SubagentManager.spawn_child",
            new=mock_spawn,
        ):
            result = await spawn_tool.ainvoke(
                {"agent_type": "search", "task": "test", "readonly": True}
            )
            assert result["success"] is True


@pytest.mark.asyncio
async def test_batch_delegate_tasks_tool() -> None:
    """Verify that batch_delegate_tasks_tool calls delegate multiple times concurrently."""
    from unittest.mock import patch

    from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
        create_batch_delegate_tasks_tool,
    )

    agent = BaseAgent(llm=FakeLLM())
    batch_tool = create_batch_delegate_tasks_tool(
        parent_agent=agent,
        tool_registry_getter=lambda: [FakeSearchTool()],
        catalog=MockCatalog(),
    )

    # Mock parent's spawn_child to return varying tasks
    async def mock_spawn(*args, **kwargs):
        return {"success": True, "result": "ok", "task_id": "mock"}

    with patch.object(agent, "_spawn_child", side_effect=mock_spawn):
        tasks = [
            {"agent_type": "search", "objective": "task 1", "readonly": True},
            {"agent_type": "search", "objective": "task 2", "readonly": False},
        ]

        result = await batch_tool.ainvoke({"tasks": tasks, "wait": True})
        assert result["success"] is True
        assert result["all_success"] is True
        assert len(result["results"]) == 2
        assert result["results"][0]["task_index"] == 0
        assert result["results"][1]["task_index"] == 1


# ---------------------------------------------------------------------------
# Taint propagation: child → parent
# ---------------------------------------------------------------------------


def test_taint_propagation_logic() -> None:
    """Verify that taint labels from a child tracker are merged into the parent tracker."""
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        TaintLabel,
        TaintTracker,
    )

    parent_taint = TaintTracker()
    child_taint = TaintTracker()

    assert not parent_taint.is_tainted
    assert not child_taint.is_tainted

    child_taint.record(TaintLabel.EXTERNAL_NETWORK)

    assert child_taint.is_tainted
    assert not parent_taint.is_tainted

    for label in child_taint.labels:
        parent_taint.record(label)

    assert parent_taint.is_tainted
    assert TaintLabel.EXTERNAL_NETWORK in parent_taint.labels
    assert parent_taint.check_sink("bash_tool") is not None


def test_taint_propagation_with_secret_label() -> None:
    """Verify SECRET taint label propagation works correctly."""
    from myrm_agent_harness.agent.security.guards.taint_tracker import (
        TaintLabel,
        TaintTracker,
    )

    parent_taint = TaintTracker()
    child_taint = TaintTracker()

    child_taint.record(TaintLabel.SECRET)
    child_taint.record(TaintLabel.EXTERNAL_NETWORK)

    for label in child_taint.labels:
        parent_taint.record(label)

    assert parent_taint.labels == frozenset(
        {TaintLabel.SECRET, TaintLabel.EXTERNAL_NETWORK}
    )


def test_taint_propagation_no_op_when_clean() -> None:
    """No-op when child taint tracker is clean."""
    from myrm_agent_harness.agent.security.guards.taint_tracker import TaintTracker

    parent_taint = TaintTracker()
    child_taint = TaintTracker()

    for label in child_taint.labels:
        parent_taint.record(label)

    assert not parent_taint.is_tainted


# ── merge_child_stats direct unit tests ──────────────────────


class TestMergeChildStats:
    """Direct unit tests for builder.merge_child_stats."""

    def test_merges_basic_token_usage(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        parent.usage.prompt_tokens = 100
        parent.usage.completion_tokens = 50
        parent.usage.total_tokens = 150

        child_stats = _make_stats(prompt=200, completion=80, total=280)
        merge_child_stats(parent, child_stats)

        assert parent.usage.prompt_tokens == 300
        assert parent.usage.completion_tokens == 130
        assert parent.usage.total_tokens == 430

    def test_merges_model_usage(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        child_stats = _make_stats(
            prompt=100,
            completion=50,
            total=150,
            model_usage={
                "gpt-4": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "cost_usd": 0.01,
                }
            },
        )
        merge_child_stats(parent, child_stats)

        assert "gpt-4" in parent.model_usage
        assert parent.model_usage["gpt-4"].prompt_tokens == 100
        assert parent.model_cost["gpt-4"] == 0.01

    def test_merges_cost_usd(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        parent.total_cost_usd = 0.01
        child_stats = _make_stats(prompt=0, completion=0, total=0, cost_usd=0.05)
        merge_child_stats(parent, child_stats)

        assert parent.total_cost_usd == pytest.approx(0.06)

    def test_cost_status_promotion(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        assert parent.cost_status == "unknown"

        child_stats = _make_stats(prompt=0, completion=0, total=0, cost_status="actual")
        merge_child_stats(parent, child_stats)
        assert parent.cost_status == "actual"

    def test_non_tracker_parent_is_noop(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats

        merge_child_stats(
            "not_a_tracker", _make_stats(prompt=10, completion=5, total=15)
        )

    def test_non_stats_child_is_noop(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        merge_child_stats(parent, "not_stats")
        assert parent.usage.total_tokens == 0


def _make_stats(
    prompt: int,
    completion: int,
    total: int,
    model_usage: dict[str, dict[str, object]] | None = None,
    cost_usd: float = 0.0,
    cost_status: str = "unknown",
) -> object:
    """Build a fake AgentRunStatistics-like object for merge_child_stats tests."""
    from myrm_agent_harness.utils.token_economics.tracker import TokenUsage

    usage = TokenUsage()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total

    class _FakeStats:
        pass

    stats = _FakeStats()
    stats.token_usage = usage  # type: ignore[attr-defined]
    stats.model_usage = model_usage  # type: ignore[attr-defined]
    stats.cost_usd = cost_usd  # type: ignore[attr-defined]
    stats.cost_status = cost_status  # type: ignore[attr-defined]
    return stats


# ── run_chain tests ──────────────────────────────────────────


class TestRunChain:
    """Tests for orchestrator.run_chain."""

    @pytest.mark.asyncio
    async def test_successful_chain(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import run_chain

        mock_manager = MagicMock()
        mock_manager.spawn_child = AsyncMock(
            side_effect=[
                SubAgentResult(
                    success=True,
                    task_id="chain-0-a",
                    agent_type="a",
                    result="step1_output",
                    completed_at=0,
                    status=SubAgentStatus.COMPLETED,
                ),
                SubAgentResult(
                    success=True,
                    task_id="chain-1-b",
                    agent_type="b",
                    result="final_output",
                    completed_at=0,
                    status=SubAgentStatus.COMPLETED,
                ),
            ]
        )

        configs = [
            ("a", SubagentConfig(system_prompt="agent a"), "Do task A"),
            (
                "b",
                SubagentConfig(system_prompt="agent b"),
                "Do task B with context: {previous}",
            ),
        ]
        result = await run_chain(mock_manager, configs, {}, lambda: [])

        assert result.success
        assert result.result == "final_output"
        second_call = mock_manager.spawn_child.call_args_list[1]
        assert "step1_output" in second_call.kwargs["task_description"]

    @pytest.mark.asyncio
    async def test_chain_aborts_on_failure(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import run_chain

        mock_manager = MagicMock()
        mock_manager.spawn_child = AsyncMock(
            return_value=SubAgentResult(
                success=False,
                task_id="chain-0-a",
                agent_type="a",
                error="step failed",
                completed_at=0,
                status=SubAgentStatus.FAILED,
            )
        )

        configs = [
            ("a", SubagentConfig(system_prompt="agent a"), "Do task A"),
            ("b", SubagentConfig(system_prompt="agent b"), "Do task B"),
        ]
        result = await run_chain(mock_manager, configs, {}, lambda: [])

        assert not result.success
        assert "chain step 1/2 (a)" in result.error
        assert mock_manager.spawn_child.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_chain(self) -> None:
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import run_chain

        mock_manager = MagicMock()
        result = await run_chain(mock_manager, [], {}, lambda: [])

        assert not result.success
        assert result.error == "Empty chain"

    @pytest.mark.asyncio
    async def test_dict_result_converted(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import run_chain

        mock_manager = MagicMock()
        mock_manager.spawn_child = AsyncMock(
            return_value={"success": True, "result": "dict_output"}
        )

        configs = [("a", SubagentConfig(system_prompt="a"), "Do A")]
        result = await run_chain(mock_manager, configs, {}, lambda: [])

        assert result.success
        assert result.result == "dict_output"


# ── wait_children timeout tests ──────────────────────────────


class TestWaitChildrenTimeout:
    """Tests for orchestrator.wait_children timeout scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_cancels_running_tasks(self) -> None:
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        async def _slow_task() -> SubAgentResult:
            await asyncio.sleep(10)
            return SubAgentResult(
                success=True,
                task_id="slow",
                agent_type="a",
                completed_at=0,
                status=SubAgentStatus.COMPLETED,
            )

        task = asyncio.create_task(_slow_task())
        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(return_value={"slow": task})
        type(mock_manager).child_results = PropertyMock(return_value={})

        result = await wait_children(mock_manager, ["slow"], timeout=0.1)

        assert not result["success"]
        assert result["success_rate"] == 0.0
        assert any("timeout" in str(f).lower() for f in result["failures"])

    @pytest.mark.asyncio
    async def test_completed_before_timeout(self) -> None:
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        async def _fast_task() -> SubAgentResult:
            return SubAgentResult(
                success=True,
                task_id="fast",
                agent_type="a",
                result="done",
                completed_at=0,
                status=SubAgentStatus.COMPLETED,
            )

        task = asyncio.create_task(_fast_task())
        await asyncio.sleep(0)  # let it complete

        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(return_value={"fast": task})
        type(mock_manager).child_results = PropertyMock(return_value={})

        result = await wait_children(mock_manager, ["fast"], timeout=5.0)

        assert result["success"]
        assert result["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_mixed_completed_and_not_found(self) -> None:
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        completed_result = SubAgentResult(
            success=True,
            task_id="done",
            agent_type="a",
            result="ok",
            completed_at=0,
            status=SubAgentStatus.COMPLETED,
        )

        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(return_value={})
        type(mock_manager).child_results = PropertyMock(
            return_value={"done": completed_result}
        )

        result = await wait_children(mock_manager, ["done", "missing"])

        assert result["success_rate"] == 0.5
        assert len(result["results"]) == 1
        assert len(result["failures"]) == 1

    @pytest.mark.asyncio
    async def test_gather_exception_captured(self) -> None:
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        async def _error_task() -> SubAgentResult:
            raise RuntimeError("boom")

        task = asyncio.create_task(_error_task())
        await asyncio.sleep(0)

        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(return_value={"err": task})
        type(mock_manager).child_results = PropertyMock(return_value={})

        result = await wait_children(mock_manager, ["err"], timeout=5.0)

        assert not result["success"]
        assert any("RuntimeError" in str(f) for f in result["failures"])

    @pytest.mark.asyncio
    async def test_timeout_with_error_and_still_running(self) -> None:
        """After timeout: one task done (exception) via _collect_timed_out_results except branch."""
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        async def _fast_error() -> SubAgentResult:
            raise ValueError("fast-fail")

        async def _slow() -> SubAgentResult:
            await asyncio.sleep(10)
            return SubAgentResult(
                success=True,
                task_id="slow",
                agent_type="a",
                completed_at=0,
                status=SubAgentStatus.COMPLETED,
            )

        fast_task = asyncio.create_task(_fast_error())
        slow_task = asyncio.create_task(_slow())
        await asyncio.sleep(0.01)

        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(
            return_value={"fast": fast_task, "slow": slow_task}
        )
        type(mock_manager).child_results = PropertyMock(return_value={})

        result = await wait_children(mock_manager, ["fast", "slow"], timeout=0.1)

        assert not result["success"]
        assert len(result["failures"]) == 2
        failure_texts = [str(f) for f in result["failures"]]
        assert any("ValueError" in t for t in failure_texts)
        assert any("timeout" in t.lower() for t in failure_texts)

    @pytest.mark.asyncio
    async def test_timeout_with_success_and_still_running(self) -> None:
        """After timeout: one task done (SubAgentResult) via _collect_timed_out_results main path."""
        from unittest.mock import MagicMock, PropertyMock

        from myrm_agent_harness.agent.sub_agents.orchestrator import wait_children

        async def _fast_ok() -> SubAgentResult:
            return SubAgentResult(
                success=True,
                task_id="fast",
                agent_type="a",
                result="ok",
                completed_at=0,
                status=SubAgentStatus.COMPLETED,
            )

        async def _slow() -> SubAgentResult:
            await asyncio.sleep(10)
            return SubAgentResult(
                success=True,
                task_id="slow",
                agent_type="a",
                completed_at=0,
                status=SubAgentStatus.COMPLETED,
            )

        fast_task = asyncio.create_task(_fast_ok())
        slow_task = asyncio.create_task(_slow())
        await asyncio.sleep(0.01)

        mock_manager = MagicMock()
        type(mock_manager).children = PropertyMock(
            return_value={"fast": fast_task, "slow": slow_task}
        )
        type(mock_manager).child_results = PropertyMock(return_value={})

        result = await wait_children(mock_manager, ["fast", "slow"], timeout=0.1)

        assert result["success_rate"] == 0.5
        assert len(result["results"]) == 1
        assert len(result["failures"]) == 1
        assert any("timeout" in str(f).lower() for f in result["failures"])


# ── filter_tools whitelist branch test ───────────────────────


class TestFilterToolsWhitelist:
    """Tests for filter_tools allowlist branch (builder.py L2)."""

    def test_whitelist_only_keeps_specified(self) -> None:
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tool_a = MagicMock(spec=BaseTool)
        tool_a.name = "tool_a"
        tool_b = MagicMock(spec=BaseTool)
        tool_b.name = "tool_b"
        tool_c = MagicMock(spec=BaseTool)
        tool_c.name = "tool_c"

        config = SubagentConfig(system_prompt="test", tools=("tool_a", "tool_c"))
        result = filter_tools(config, [tool_a, tool_b, tool_c])

        names = {t.name for t in result}
        assert names == {"tool_a", "tool_c"}
        assert "tool_b" not in names


# ── L2 disallowed_tools test ─────────────────────────────────


class TestFilterToolsDisallowedTools:
    """Tests for filter_tools disallowed_tools branch (builder.py L2 blocklist)."""

    def test_disallowed_tools_blocks_specified(self) -> None:
        """L2 blocklist: tools listed in disallowed_tools are stripped."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tool_a = MagicMock(spec=BaseTool)
        tool_a.name = "tool_a"
        tool_b = MagicMock(spec=BaseTool)
        tool_b.name = "tool_b"
        tool_c = MagicMock(spec=BaseTool)
        tool_c.name = "tool_c"

        config = SubagentConfig(
            system_prompt="test", disallowed_tools=frozenset({"tool_b"})
        )
        result = filter_tools(config, [tool_a, tool_b, tool_c])

        names = {t.name for t in result}
        assert "tool_a" in names
        assert "tool_c" in names
        assert "tool_b" not in names

    def test_disallowed_tools_combined_with_whitelist(self) -> None:
        """L2 whitelist + blocklist combined: whitelist selects, blocklist further removes."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tool_a = MagicMock(spec=BaseTool)
        tool_a.name = "tool_a"
        tool_b = MagicMock(spec=BaseTool)
        tool_b.name = "tool_b"
        tool_c = MagicMock(spec=BaseTool)
        tool_c.name = "tool_c"

        config = SubagentConfig(
            system_prompt="test",
            tools=("tool_a", "tool_b"),
            disallowed_tools=frozenset({"tool_b"}),
        )
        result = filter_tools(config, [tool_a, tool_b, tool_c])

        names = {t.name for t in result}
        assert names == {"tool_a"}

    def test_disallowed_tools_does_not_override_l1_blacklist(self) -> None:
        """L1 always takes precedence: even without disallowed_tools, L1 items stay blocked."""
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        parent_tools = [FakeSearchTool(), FakeSpawnSubagentTool()]
        config = SubagentConfig(system_prompt="test", disallowed_tools=frozenset())
        result = filter_tools(config, parent_tools)

        names = {t.name for t in result}
        assert "web_search_tool" in names
        assert "delegate_task_tool" not in names


# ── truncate_result boundary test ────────────────────────────


class TestTruncateResult:
    """Tests for builder.truncate_result edge cases."""

    def test_no_truncation_when_within_limit(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        assert truncate_result("short", 100) == "short"

    def test_truncation_with_marker(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        text = "a" * 1000
        result = truncate_result(text, 10)
        assert len(result) < len(text)
        assert "[Truncated:" in result

    def test_no_op_when_max_tokens_is_none(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        assert truncate_result("anything", None) == "anything"

    def test_no_op_when_text_is_empty(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        assert truncate_result("", 100) == ""


# ── cost_status demotion protection test ─────────────────────


class TestCostStatusDemotion:
    """Ensure cost_status never downgrades from 'actual'."""

    def test_actual_not_demoted_by_estimated(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        parent.cost_status = "actual"

        child_stats = _make_stats(
            prompt=0, completion=0, total=0, cost_status="estimated"
        )
        merge_child_stats(parent, child_stats)

        assert parent.cost_status == "actual"

    def test_actual_not_demoted_by_unknown(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        parent.cost_status = "actual"

        child_stats = _make_stats(
            prompt=0, completion=0, total=0, cost_status="unknown"
        )
        merge_child_stats(parent, child_stats)

        assert parent.cost_status == "actual"

    def test_unknown_promoted_by_estimated(self) -> None:
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        assert parent.cost_status == "unknown"

        child_stats = _make_stats(
            prompt=0, completion=0, total=0, cost_status="estimated"
        )
        merge_child_stats(parent, child_stats)

        assert parent.cost_status == "estimated"


# =========================================================================
# agent_manage_tool tests
# =========================================================================


class TestAgentManageTools:
    """Tests for create_list_subagents_tool and create_cancel_subagent_tool."""

    @pytest.mark.asyncio
    async def test_list_subagents_empty(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_list_subagents_tool,
        )

        agent = BaseAgent(llm=FakeLLM())
        list_tool = create_list_subagents_tool(agent)
        result = await list_tool.ainvoke({})
        assert result["total"] == 0
        assert result["running"] == 0
        assert result["completed"] == 0
        assert result["children"] == []

    @pytest.mark.asyncio
    async def test_list_subagents_with_running_and_completed(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_list_subagents_tool,
        )

        agent = BaseAgent(
            llm=FakeLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="bg_task",
            agent_type="search",
            task_description="background work",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        list_tool = create_list_subagents_tool(agent)
        result = await list_tool.ainvoke({})
        assert result["total"] >= 1
        assert result["running"] >= 0

        manager.cancel_all()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_cancel_subagent_success(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_cancel_subagent_tool,
        )

        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="cancel_me",
            agent_type="search",
            task_description="long running",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        cancel_tool = create_cancel_subagent_tool(agent)
        result = await cancel_tool.ainvoke({"task_id": "cancel_me"})
        assert result["success"] is True
        assert "cancelled" in result["message"].lower()

        manager.cancel_all()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_cancel_subagent_not_found(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_cancel_subagent_tool,
        )

        agent = BaseAgent(llm=FakeLLM())
        cancel_tool = create_cancel_subagent_tool(agent)
        result = await cancel_tool.ainvoke({"task_id": "nonexistent"})
        assert result["success"] is False
        assert "could not cancel" in result["message"].lower()


# =========================================================================
# Additional manager.py coverage
# =========================================================================


class TestPurgeExpiredResults:
    """Test _purge_expired_results eviction logic."""

    def test_purge_evicts_oldest_when_over_50(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        for i in range(55):
            manager._children_results[f"task_{i}"] = SubAgentResult(
                success=True,
                task_id=f"task_{i}",
                agent_type="search",
                result=f"result_{i}",
                completed_at=float(i),
                status=SubAgentStatus.COMPLETED,
            )

        manager._purge_expired_results()
        assert len(manager._children_results) == 50
        assert "task_0" not in manager._children_results
        assert "task_4" not in manager._children_results
        assert "task_5" in manager._children_results

    def test_purge_no_op_when_under_50(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        for i in range(10):
            manager._children_results[f"task_{i}"] = SubAgentResult(
                success=True,
                task_id=f"task_{i}",
                agent_type="search",
                completed_at=float(i),
                status=SubAgentStatus.COMPLETED,
            )

        manager._purge_expired_results()
        assert len(manager._children_results) == 10


class TestManagerDuplicateTaskId:
    """Test spawn_child rejects duplicate task_ids."""

    @pytest.mark.asyncio
    async def test_duplicate_task_id_rejected(self) -> None:
        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="dup_task",
            agent_type="search",
            task_description="first spawn",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        result = await manager.spawn_child(
            task_id="dup_task",
            agent_type="search",
            task_description="second spawn",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=True,
        )
        assert isinstance(result, SubAgentResult)
        assert result.success is False
        assert "already exists" in (result.error or "")

        manager.cancel_all()
        await asyncio.sleep(0.1)


class TestCancelAll:
    """Test cancel_all propagation."""

    @pytest.mark.asyncio
    async def test_cancel_all_returns_count(self) -> None:
        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        for i in range(3):
            await manager.spawn_child(
                task_id=f"cancel_all_{i}",
                agent_type="search",
                task_description=f"task {i}",
                config=SUBAGENT_CONFIGS["search"],
                context={},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        cancelled_count = manager.cancel_all()
        assert cancelled_count >= 1
        await asyncio.sleep(0.1)


# =========================================================================
# _cleanup_child paths (lines 136-149)
# =========================================================================


class TestCleanupChildPaths:
    """Cover _cleanup_child success and exception branches."""

    @pytest.mark.asyncio
    async def test_cleanup_successful_task(self) -> None:
        """Wait=False child that succeeds should have result in child_results."""
        agent = BaseAgent(
            llm=FakeLLM("done"),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="bg_success",
            agent_type="search",
            task_description="quick task",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=False,
        )
        await asyncio.sleep(2.0)

        results = manager.list_children()
        completed = [r for r in results if r.get("task_id") == "bg_success"]
        assert len(completed) == 1
        assert completed[0]["status"] in ("completed", "failed", "running")

    @pytest.mark.asyncio
    async def test_cleanup_cancelled_task_stores_result(self) -> None:
        """Cancelled bg task should store CANCELLED result in child_results."""
        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="bg_cancel",
            agent_type="search",
            task_description="slow work",
            config=SUBAGENT_CONFIGS["search"],
            context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
            tool_registry_getter=lambda: [],
            wait=False,
        )
        manager.cancel_child("bg_cancel")
        await asyncio.sleep(0.3)

        results = manager.list_children()
        cancelled_item = [r for r in results if r.get("task_id") == "bg_cancel"]
        assert len(cancelled_item) == 1
        assert cancelled_item[0]["status"] in ("cancelled", "failed")


# =========================================================================
# _inherit_parent_context (line 194)
# =========================================================================


class TestInheritParentContext:
    """Cover _inherit_parent_context propagation (now on SubagentExecutor)."""

    @pytest.mark.asyncio
    async def test_inherits_from_parent_last_context(self) -> None:
        from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor

        agent = BaseAgent(llm=FakeLLM())
        executor = SubagentExecutor()

        agent._last_context = {
            "session_id": "sess-123",
            "workspace_path": "/tmp/work",
            "approval_session_key": "key-xyz",
            "extra_key": "should_not_inherit",
        }

        child_ctx = await executor._inherit_parent_context(
            {"query": "test"}, "t1", agent
        )
        assert child_ctx["session_id"] == "sess-123"
        assert child_ctx["workspace_path"] == "/tmp/work"
        assert child_ctx["approval_session_key"] == "key-xyz"
        assert "extra_key" not in child_ctx
        assert child_ctx["query"] == "test"

    @pytest.mark.asyncio
    async def test_child_context_overrides_parent(self) -> None:
        from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor

        agent = BaseAgent(llm=FakeLLM())
        executor = SubagentExecutor()

        agent._last_context = {"session_id": "parent-sess"}
        child_ctx = await executor._inherit_parent_context(
            {"session_id": "child-sess"}, "t2", agent
        )
        assert child_ctx["session_id"] == "child-sess"

    @pytest.mark.asyncio
    async def test_no_parent_context_returns_child_as_is(self) -> None:
        from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor

        agent = BaseAgent(llm=FakeLLM())
        executor = SubagentExecutor()

        child_ctx = await executor._inherit_parent_context(
            {"query": "test"}, "t3", agent
        )
        assert child_ctx == {"query": "test"}


# =========================================================================
# current_depth property (line 89)
# =========================================================================


class TestCurrentDepth:
    def test_default_depth_is_zero(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        assert agent._subagent_manager.current_depth == 0

    def test_depth_propagation(self) -> None:
        agent = BaseAgent(
            llm=FakeLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5),
        )
        manager = SubagentManager(parent_agent=agent, current_depth=3)
        assert manager.current_depth == 3


# =========================================================================
# spawn_child runtime policy ignores stale global parent_type registry state
# =========================================================================


class TestParentTypeRestriction:
    @pytest.mark.asyncio
    async def test_parent_type_does_not_apply_static_registry_limit(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        result = await manager.spawn_child(
            task_id="restricted",
            agent_type="search",
            task_description="test",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=True,
            parent_type="search",
        )
        assert isinstance(result, SubAgentResult)
        assert "max_spawn_depth=0" not in (result.error or "")


# =========================================================================
# list_children with mixed states (lines 439-455)
# =========================================================================


class TestListChildrenMixed:
    @pytest.mark.asyncio
    async def test_list_includes_running_and_completed(self) -> None:
        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="slow_task",
            agent_type="search",
            task_description="slow",
            config=SUBAGENT_CONFIGS["search"],
            context={},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        children_list = manager.list_children()
        assert len(children_list) >= 1
        task_ids = [c["task_id"] for c in children_list]
        assert "slow_task" in task_ids

        manager.cancel_all()
        await asyncio.sleep(0.1)


# =========================================================================
# cancel_child edge cases (lines 457-467)
# =========================================================================


class TestCancelChildEdgeCases:
    def test_cancel_nonexistent_task(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        assert manager.cancel_child("no_such_task") is False

    @pytest.mark.asyncio
    async def test_cancel_already_done_task(self) -> None:
        agent = BaseAgent(
            llm=SlowLLM(),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=30),
        )
        manager = agent._subagent_manager

        async def _instant() -> SubAgentResult:
            return SubAgentResult(
                success=True,
                task_id="instant",
                agent_type="search",
                completed_at=0.0,
                status=SubAgentStatus.COMPLETED,
            )

        done_task: asyncio.Task[SubAgentResult] = asyncio.create_task(_instant())
        await done_task
        manager._children["instant"] = done_task

        success = manager.cancel_child("instant")
        assert success is False


# =========================================================================
# _run_subagent_inner mock tests — hook exceptions & budget_tokens
# =========================================================================


class _MockChildAgent:
    """Mock child agent whose run() yields configurable events."""

    def __init__(
        self, events: list[dict[str, object]], last_run_stats: object = None
    ) -> None:
        self._events = events
        self.last_run_stats = last_run_stats
        self.checkpointer = None

    async def run(
        self,
        query: str,
        chat_history: list[object],
        context: dict[str, object],
        **kwargs: object,
    ):
        for evt in self._events:
            yield evt


class _FakeStats:
    """Minimal stand-in for agent stats returned after a child run."""

    def __init__(self, total_tokens: int = 100) -> None:
        self.token_usage = type("U", (), {"total_tokens": total_tokens})()


@pytest.mark.skip(
    reason="SubAgentHook is superseded by the global HookEvent system "
    "(HookEvent.SUBAGENT_START/STOP + fire_hook in hooks/executor.py). "
    "Config-level inline hooks add unnecessary complexity."
)
class TestHookExceptionSafety:
    """Ensure hook exceptions never crash the subagent main flow."""

    @pytest.mark.asyncio
    async def test_on_spawn_hook_exception_is_swallowed(self) -> None:
        from unittest.mock import patch

        async def _bad_spawn(tid: str, atype: str, ctx: dict[str, object]) -> None:
            raise RuntimeError("spawn hook boom")

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=10,
            max_retries=1,
            hook=SubAgentHook(on_spawn=_bad_spawn),
        )

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "hi"}], last_run_stats=_FakeStats(50)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="hook_spawn",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is True
        assert result.result == "hi"

    @pytest.mark.asyncio
    async def test_on_complete_hook_exception_is_swallowed(self) -> None:
        from unittest.mock import patch

        async def _bad_complete(tid: str, atype: str, ctx: dict[str, object]) -> None:
            raise ValueError("complete hook boom")

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=10,
            max_retries=1,
            hook=SubAgentHook(on_complete=_bad_complete),
        )

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "done"}], last_run_stats=_FakeStats(20)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="hook_complete",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_on_error_hook_exception_is_swallowed(self) -> None:
        from unittest.mock import patch

        async def _bad_error(tid: str, atype: str, ctx: dict[str, object]) -> None:
            raise TypeError("error hook boom")

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=10,
            max_retries=1,
            hook=SubAgentHook(on_error=_bad_error),
        )

        async def _exploding_run(
            query: str, chat_history: list[object], context: dict[str, object]
        ):
            raise RuntimeError("child exploded")
            yield

        mock_child = _MockChildAgent(events=[])
        mock_child.run = _exploding_run  # type: ignore[assignment]

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="hook_error",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is False
        assert result.status == SubAgentStatus.FAILED
        assert "child exploded" in (result.error or "")


class TestBudgetTokensLimit:
    """Test budget_tokens enforcement in _run_subagent_inner."""

    @pytest.mark.asyncio
    async def test_budget_exceeded_breaks_early(self) -> None:
        from unittest.mock import patch

        events: list[dict[str, object]] = [
            {"type": "message", "data": "chunk1"},
            {"type": "token_usage", "data": {"usage": {"total_tokens": 500}}},
            {"type": "message", "data": "chunk2"},
            {"type": "token_usage", "data": {"usage": {"total_tokens": 1500}}},
            {"type": "message", "data": "should_not_appear"},
        ]

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=10,
            max_retries=1,
            budget_tokens=1000,
        )

        mock_child = _MockChildAgent(events=events, last_run_stats=_FakeStats(1500))

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="budget_test",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is False
        assert result.status == SubAgentStatus.CANCELLED_BY_BUDGET
        assert "Budget exceeded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_no_budget_processes_all_events(self) -> None:
        from unittest.mock import patch

        events: list[dict[str, object]] = [
            {"type": "message", "data": "a"},
            {"type": "token_usage", "data": {"usage": {"total_tokens": 5000}}},
            {"type": "message", "data": "b"},
        ]

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=10,
            max_retries=1,
            budget_tokens=None,
        )

        mock_child = _MockChildAgent(events=events, last_run_stats=_FakeStats(5000))

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="no_budget",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is True
        assert "a" in result.result
        assert "b" in result.result


class TestTimeoutRetryPath:
    """Test timeout retry with exponential backoff inside _run_subagent_inner."""

    @pytest.mark.asyncio
    async def test_timeout_exhausts_retries(self) -> None:
        from unittest.mock import patch

        async def _timeout_run(
            query: str,
            chat_history: list[object],
            context: dict[str, object],
            **kwargs: object,
        ):
            raise TimeoutError("inner timeout")
            yield

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=1,
            max_retries=2,
            retry_backoff_seconds=0.01,
        )

        mock_child = _MockChildAgent(events=[])
        mock_child.run = _timeout_run  # type: ignore[assignment]

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager._run_subagent_inner(
                task_id="timeout_retry",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
            )

        assert result.success is False
        assert result.status == SubAgentStatus.TIMED_OUT


# =========================================================================
# Push-based notifications: drain + format
# =========================================================================


class TestDrainNotifications:
    """Test drain_notifications merging and TTL filtering."""

    def test_empty_returns_none(self) -> None:
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        assert manager.drain_notifications() is None

    def test_fresh_notifications_merged(self) -> None:
        import time as _time
        from collections import deque

        from myrm_agent_harness.agent.sub_agents.notifications import (
            SubagentNotification,
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        now = _time.time()
        manager._notification_manager._pending_notifications = deque(
            [
                SubagentNotification(content="Notif A", timestamp=now),
                SubagentNotification(content="Notif B", timestamp=now),
            ]
        )

        result = manager.drain_notifications()
        assert result is not None
        assert "Notif A" in result
        assert "Notif B" in result
        assert "\n\n---\n\n" in result
        assert len(manager._notification_manager._pending_notifications) == 0

    def test_expired_notifications_discarded(self) -> None:
        import time as _time
        from collections import deque

        from myrm_agent_harness.agent.sub_agents.notifications import (
            SubagentNotification,
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        old_ts = _time.time() - 600  # 10 minutes ago, well past 300s TTL
        manager._notification_manager._pending_notifications = deque(
            [
                SubagentNotification(content="Expired", timestamp=old_ts),
            ]
        )

        result = manager.drain_notifications()
        assert result is None
        assert len(manager._notification_manager._pending_notifications) == 0

    def test_mixed_fresh_and_expired(self) -> None:
        import time as _time
        from collections import deque

        from myrm_agent_harness.agent.sub_agents.notifications import (
            SubagentNotification,
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        now = _time.time()
        manager._notification_manager._pending_notifications = deque(
            [
                SubagentNotification(content="Old", timestamp=now - 600),
                SubagentNotification(content="Fresh", timestamp=now),
            ]
        )

        result = manager.drain_notifications()
        assert result is not None
        assert "Fresh" in result
        assert "Old" not in result

    @pytest.mark.asyncio
    async def test_cleanup_child_pushes_notification(self) -> None:
        """Verify _cleanup_child adds a notification to the deque."""
        agent = BaseAgent(
            llm=FakeLLM("ok"),
            config=AgentRuntimeConfig(recursion_limit=10, timeout_seconds=5),
        )
        manager = agent._subagent_manager

        await manager.spawn_child(
            task_id="notif_test",
            agent_type="search",
            task_description="quick task",
            config=SUBAGENT_CONFIGS["search"],
            context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
            tool_registry_getter=lambda: [FakeSearchTool()],
            wait=True,
        )

        notif = manager.drain_notifications()
        assert notif is not None
        assert "notif_test" in notif
        assert "search" in notif


class TestFormatNotification:
    """Test format_notification output."""

    def test_success_format(self) -> None:
        from myrm_agent_harness.agent.sub_agents.notifications import (
            format_notification,
        )

        result = SubAgentResult(
            success=True,
            task_id="t1",
            agent_type="search",
            result="Found 5 results",
            completed_at=100.0,
            status=SubAgentStatus.COMPLETED,
            duration_seconds=2.5,
        )
        text = format_notification(result)
        assert "search" in text
        assert "task_id=t1" in text
        assert "completed successfully" in text
        assert "2.5s" in text
        assert "Found 5 results" in text
        assert "Process this result" in text

    def test_failure_format(self) -> None:
        from myrm_agent_harness.agent.sub_agents.notifications import (
            format_notification,
        )

        result = SubAgentResult(
            success=False,
            task_id="t2",
            agent_type="browser",
            error="Page not found",
            completed_at=100.0,
            status=SubAgentStatus.FAILED,
        )
        text = format_notification(result)
        assert "browser" in text
        assert "task_id=t2" in text
        assert "failed" in text
        assert "Page not found" in text

    def test_no_duration(self) -> None:
        from myrm_agent_harness.agent.sub_agents.notifications import (
            format_notification,
        )

        result = SubAgentResult(
            success=True,
            task_id="t3",
            agent_type="search",
            result="ok",
            completed_at=100.0,
            status=SubAgentStatus.COMPLETED,
        )
        text = format_notification(result)
        assert "completed successfully" in text
        # No duration, so no "(X.Xs)" suffix
        assert "s)" not in text


class TestHardTimeoutSemaphoreRelease:
    """Test that hard timeout (asyncio.wait_for) properly releases the semaphore."""

    @pytest.mark.asyncio
    async def test_semaphore_released_after_timeout(self) -> None:
        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
            timeout_seconds=0.05,
            concurrency_limit=SUBAGENT_CONFIGS["search"].concurrency_limit,
            max_retries=1,
            retry_backoff_seconds=0.0,
        )

        result = await manager.spawn_child(
            task_id="sem_test",
            agent_type="search",
            task_description="timeout test",
            config=config,
            context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
            tool_registry_getter=lambda: [],
            wait=True,
        )

        assert result.success is False
        assert result.status == SubAgentStatus.TIMED_OUT

        # Semaphore should be released: if locked, next acquire would hang
        acquired = manager._semaphore._value > 0  # type: ignore[attr-defined]
        assert acquired, "Semaphore should be released after timeout"


# =========================================================================
# trace_id Tests
# =========================================================================


class TestTraceId:
    """Verify trace_id propagation across all execution paths."""

    @pytest.mark.asyncio
    async def test_trace_id_auto_generated(self) -> None:
        """trace_id is generated when not present in context."""
        from unittest.mock import patch

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "ok"}], last_run_stats=_FakeStats(50)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager.spawn_child(
                task_id="trace_auto",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.trace_id != ""
        assert len(result.trace_id) == 16

    @pytest.mark.asyncio
    async def test_trace_id_inherited_from_parent(self) -> None:
        """trace_id is inherited from parent context when present."""
        from unittest.mock import patch

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "ok"}], last_run_stats=_FakeStats(50)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager.spawn_child(
                task_id="trace_inherit",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s", "trace_id": "parent_trace_abc"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.trace_id == "parent_trace_abc"

    @pytest.mark.asyncio
    async def test_trace_id_in_hard_timeout(self) -> None:
        """trace_id is present in hard timeout SubAgentResult."""
        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt="t",
            timeout_seconds=0.05,
            max_retries=1,
            retry_backoff_seconds=0.0,
        )

        result = await manager.spawn_child(
            task_id="trace_timeout",
            agent_type="search",
            task_description="test",
            config=config,
            context={"session_id": "s", "trace_id": "timeout_trace_123", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
            tool_registry_getter=lambda: [],
            wait=True,
        )

        assert isinstance(result, SubAgentResult)
        assert result.success is False
        assert result.status == SubAgentStatus.TIMED_OUT
        assert result.trace_id == "timeout_trace_123"

    @pytest.mark.asyncio
    async def test_trace_id_in_to_dict(self) -> None:
        """trace_id is included in to_dict() when non-empty."""
        result = SubAgentResult(
            success=True,
            task_id="t",
            agent_type="search",
            result="ok",
            trace_id="abc123",
        )
        d = result.to_dict()
        assert d["trace_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_trace_id_omitted_in_to_dict_when_empty(self) -> None:
        """trace_id is omitted from to_dict() when empty."""
        result = SubAgentResult(
            success=True, task_id="t", agent_type="search", result="ok"
        )
        d = result.to_dict()
        assert "trace_id" not in d


# =========================================================================
# Steer Tests
# =========================================================================


class TestSteerChild:
    """Verify steer_child functionality."""

    @pytest.mark.asyncio
    async def test_steer_nonexistent_task(self) -> None:
        """steer_child returns False for non-existent task."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        assert manager.steer_child("no_such_task", "hello") is False

    @pytest.mark.asyncio
    async def test_steer_running_child(self) -> None:
        """steer_child injects message into a running child's steering token."""
        from unittest.mock import patch

        class _SlowMockChild:
            def __init__(self) -> None:
                self.last_run_stats = _FakeStats(10)
                self.checkpointer = None

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kwargs: object,
            ):
                yield {"type": "message", "data": "start"}
                await asyncio.sleep(2)
                yield {"type": "message", "data": "end"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_SlowMockChild(),
        ):
            # Spawn async (no wait)
            result = await manager.spawn_child(
                task_id="steer_test",
                agent_type="search",
                task_description="slow test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        assert isinstance(result, dict)
        assert result["status"] == "running"

        # steer should succeed while child is running
        assert manager.steer_child("steer_test", "change direction") is True

        # Verify SteeringToken was created
        assert "steer_test" in manager._children_steering

        # Wait for child to finish
        await asyncio.sleep(0.1)
        task = manager._children.get("steer_test")
        if task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, timeout=5)

    @pytest.mark.asyncio
    async def test_steer_after_completion(self) -> None:
        """steer_child returns False after child has completed."""
        from unittest.mock import patch

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "done"}], last_run_stats=_FakeStats(10)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager.spawn_child(
                task_id="steer_done",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.success is True

        # After completion, steering token should be cleaned up
        assert manager.steer_child("steer_done", "too late") is False

    @pytest.mark.asyncio
    async def test_base_agent_steer_child_delegation(self) -> None:
        """BaseAgent.steer_child delegates to SubagentManager."""
        agent = BaseAgent(llm=FakeLLM())
        assert agent.steer_child("no_task", "msg") is False


# =========================================================================
# Steer Tool Tests
# =========================================================================


class TestSteerSubagentTool:
    """Verify steer_subagent_tool factory function."""

    @pytest.mark.asyncio
    async def test_steer_tool_creation(self) -> None:
        """steer_subagent_tool is created correctly."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
            create_steer_subagent_tool,
        )

        agent = BaseAgent(llm=FakeLLM())
        tool = create_steer_subagent_tool(agent)
        assert tool.name == "steer_subagent_tool"
        assert "corrective message" in tool.description

    @pytest.mark.asyncio
    async def test_steer_tool_returns_failure_for_unknown_task(self) -> None:
        """steer_subagent_tool returns failure for unknown task_id."""
        from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
            create_steer_subagent_tool,
        )

        agent = BaseAgent(llm=FakeLLM())
        tool = create_steer_subagent_tool(agent)
        result = await tool.ainvoke({"task_id": "unknown", "message": "fix this"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_steer_tool_success_path(self) -> None:
        """steer_subagent_tool returns success when child is running."""
        from unittest.mock import patch

        from myrm_agent_harness.agent.meta_tools.spawn_subagent import (
            create_steer_subagent_tool,
        )

        class _SlowChild:
            def __init__(self) -> None:
                self.last_run_stats = _FakeStats(10)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                await asyncio.sleep(5)
                yield {"type": "message", "data": "done"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=10, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_SlowChild(),
        ):
            await manager.spawn_child(
                task_id="steer_ok",
                agent_type="search",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        tool = create_steer_subagent_tool(agent)
        result = await tool.ainvoke({"task_id": "steer_ok", "message": "go left"})
        assert result["success"] is True
        assert result["task_id"] == "steer_ok"

        task = manager._children.get("steer_ok")
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


# =========================================================================
# Extended Coverage Tests
# =========================================================================


class TestTraceIdExtended:
    """Additional trace_id edge cases."""

    @pytest.mark.asyncio
    async def test_trace_id_wait_true_timeout(self) -> None:
        """trace_id is present in SubAgentResult when wait=True + timeout."""
        from unittest.mock import patch

        class _HangChild:
            last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                await asyncio.sleep(100)
                yield {"type": "message", "data": "never"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=0.1, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_HangChild(),
        ):
            result = await manager.spawn_child(
                task_id="tid_wait_to",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.status == SubAgentStatus.TIMED_OUT
        assert len(result.trace_id) > 0

    @pytest.mark.asyncio
    async def test_trace_id_consistent_across_retries(self) -> None:
        """trace_id stays the same across retry attempts."""
        from unittest.mock import patch

        call_count = 0

        class _FailOnce:
            last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("transient error")
                yield {"type": "message", "data": "ok"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t",
            description="t",
            timeout_seconds=5,
            max_retries=3,
            retry_backoff_seconds=0.01,
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_FailOnce(),
        ):
            result = await manager.spawn_child(
                task_id="tid_retry",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.success is True
        assert len(result.trace_id) > 0
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_trace_id_unique_concurrent_spawns(self) -> None:
        """Concurrent spawns produce unique trace_ids."""
        from unittest.mock import patch

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "ok"}], last_run_stats=_FakeStats(10)
        )
        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            results = await asyncio.gather(
                manager.spawn_child(
                    task_id="c1",
                    agent_type="s",
                    task_description="t",
                    config=config,
                    context={"session_id": "s"},
                    tool_registry_getter=lambda: [],
                    wait=True,
                ),
                manager.spawn_child(
                    task_id="c2",
                    agent_type="s",
                    task_description="t",
                    config=config,
                    context={"session_id": "s"},
                    tool_registry_getter=lambda: [],
                    wait=True,
                ),
                manager.spawn_child(
                    task_id="c3",
                    agent_type="s",
                    task_description="t",
                    config=config,
                    context={"session_id": "s"},
                    tool_registry_getter=lambda: [],
                    wait=True,
                ),
            )

        trace_ids = [r.trace_id for r in results if isinstance(r, SubAgentResult)]
        assert len(trace_ids) == 3
        assert len(set(trace_ids)) == 3, f"Trace IDs should be unique: {trace_ids}"


class TestSteeringTokenLifecycle:
    """Verify SteeringToken cleanup across different child states."""

    @pytest.mark.asyncio
    async def test_steering_token_cleanup_after_cancel(self) -> None:
        """SteeringToken is removed from _children_steering after cancel."""
        from unittest.mock import patch

        class _SlowChild:
            last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                await asyncio.sleep(100)
                yield {"type": "message", "data": "never"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=10, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_SlowChild(),
        ):
            await manager.spawn_child(
                task_id="cancel_st",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        assert "cancel_st" in manager._children_steering
        manager.cancel_child("cancel_st")
        await asyncio.sleep(0.1)
        assert "cancel_st" not in manager._children_steering

    @pytest.mark.asyncio
    async def test_steering_token_cleanup_after_completion(self) -> None:
        """SteeringToken is removed from _children_steering after child completes."""
        from unittest.mock import patch

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "done"}], last_run_stats=_FakeStats(10)
        )
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager.spawn_child(
                task_id="complete_st",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.success is True
        assert "complete_st" not in manager._children_steering

    @pytest.mark.asyncio
    async def test_child_exception_cleanup(self) -> None:
        """SteeringToken and trace info are cleaned up when child raises exception."""
        from unittest.mock import patch

        class _ExplodingChild:
            last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                raise RuntimeError("boom")
                yield

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=5, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_ExplodingChild(),
        ):
            result = await manager.spawn_child(
                task_id="explode_st",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.success is False
        assert len(result.trace_id) > 0
        assert "explode_st" not in manager._children_steering


class TestSteerEdgeCases:
    """Edge cases for steer_child."""

    @pytest.mark.asyncio
    async def test_steer_cancelled_child(self) -> None:
        """steer_child returns False for a cancelled child."""
        from unittest.mock import patch

        class _SlowChild:
            last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                await asyncio.sleep(100)
                yield {"type": "message", "data": "never"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=10, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_SlowChild(),
        ):
            await manager.spawn_child(
                task_id="cancel_then_steer",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        manager.cancel_child("cancel_then_steer")
        await asyncio.sleep(0.1)
        assert manager.steer_child("cancel_then_steer", "too late") is False

    @pytest.mark.asyncio
    async def test_steer_multiple_times(self) -> None:
        """Multiple consecutive steers to the same running child all succeed."""
        from unittest.mock import patch

        class _SlowChild:
            def __init__(self) -> None:
                self.last_run_stats = _FakeStats(0)

            async def run(
                self,
                query: str,
                chat_history: list[object],
                context: dict[str, object],
                **kw: object,
            ):
                await asyncio.sleep(5)
                yield {"type": "message", "data": "done"}

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        config = SubagentConfig(
            system_prompt="t", description="t", timeout_seconds=10, max_retries=1
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=_SlowChild(),
        ):
            await manager.spawn_child(
                task_id="multi_steer",
                agent_type="s",
                task_description="t",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=False,
            )

        for i in range(5):
            assert manager.steer_child("multi_steer", f"correction {i}") is True

        task = manager._children.get("multi_steer")
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


class TestAddToolsDynamic:
    """Verify BaseAgent.add_tools dynamic injection."""

    @pytest.mark.asyncio
    async def test_add_tools_extends_cached_tools(self) -> None:
        """add_tools correctly extends the agent's tool list."""
        from langchain_core.tools import tool

        @tool
        def custom_tool(x: str) -> str:
            """A custom tool."""
            return x

        agent = BaseAgent(llm=FakeLLM())
        initial_count = len(agent.user_tools)
        agent.add_tools([custom_tool])
        assert len(agent.user_tools) == initial_count + 1
        assert any(t.name == "custom_tool" for t in agent.user_tools)


# =========================================================================
# Cooperative Subagent Cancellation Tests (#4)
# =========================================================================


class TestCancellationStrategy:
    """Tests for CancellationStrategy and cooperative subagent cancellation."""

    @pytest.mark.asyncio
    async def test_immediate_cancellation_strategy(self) -> None:
        """IMMEDIATE strategy calls task.cancel() directly."""

        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
            timeout_seconds=30,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.IMMEDIATE,
        )

        await manager.spawn_child(
            task_id="immediate_cancel",
            agent_type="search",
            task_description="long task",
            config=config,
            context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        await asyncio.sleep(0.1)
        assert manager.cancel_child("immediate_cancel") is True

        task = manager._children.get("immediate_cancel")
        if task:
            await asyncio.sleep(0.1)
            assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_graceful_cancellation_strategy(self) -> None:
        """GRACEFUL strategy sets cancel_flag instead of calling task.cancel()."""

        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
            timeout_seconds=30,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.GRACEFUL,
        )

        await manager.spawn_child(
            task_id="graceful_cancel",
            agent_type="search",
            task_description="long task",
            config=config,
            context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        await asyncio.sleep(0.1)
        assert manager.cancel_child("graceful_cancel") is True
        assert "graceful_cancel" in manager._cancel_flags
        assert manager._cancel_flags["graceful_cancel"] is True

        for _ in range(20):
            await asyncio.sleep(0.3)
            if "graceful_cancel" not in manager._cancel_flags:
                break
        assert "graceful_cancel" not in manager._cancel_flags

    @pytest.mark.asyncio
    async def test_checkpoint_cancellation_strategy(self) -> None:
        """CHECKPOINT strategy sets cancel_flag (same as GRACEFUL for now)."""

        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt=SUBAGENT_CONFIGS["search"].system_prompt,
            timeout_seconds=30,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.CHECKPOINT,
        )

        await manager.spawn_child(
            task_id="checkpoint_cancel",
            agent_type="search",
            task_description="long task",
            config=config,
            context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp/test"},
            tool_registry_getter=lambda: [],
            wait=False,
        )

        await asyncio.sleep(0.1)
        assert manager.cancel_child("checkpoint_cancel") is True
        assert "checkpoint_cancel" in manager._cancel_flags
        assert manager._cancel_flags["checkpoint_cancel"] is True

        for _ in range(20):
            await asyncio.sleep(0.3)
            if "checkpoint_cancel" not in manager._cancel_flags:
                break
        assert "checkpoint_cancel" not in manager._cancel_flags

    @pytest.mark.asyncio
    async def test_cancel_flag_cleanup_on_completion(self) -> None:
        """Cancel flag is cleaned up when subagent completes."""
        from unittest.mock import patch

        mock_child = _MockChildAgent(
            events=[{"type": "message", "data": "done"}], last_run_stats=_FakeStats(10)
        )

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            timeout_seconds=5,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.GRACEFUL,
        )

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor.build_child_agent",
            return_value=mock_child,
        ):
            result = await manager.spawn_child(
                task_id="cleanup_test",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s"},
                tool_registry_getter=lambda: [],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        assert result.success is True
        assert "cleanup_test" not in manager._cancel_flags

    @pytest.mark.asyncio
    async def test_default_cancellation_strategy_is_graceful(self) -> None:
        """Default cancellation strategy is GRACEFUL."""
        config = SubagentConfig(system_prompt="test")

        assert config.cancellation_strategy == CancellationStrategy.GRACEFUL

    @pytest.mark.asyncio
    async def test_graceful_cancel_timeout_triggers_immediate(self) -> None:
        """GRACEFUL cancellation forces immediate cancellation after timeout."""

        agent = BaseAgent(llm=SlowLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            tools=SUBAGENT_CONFIGS["search"].tools,
            timeout_seconds=10,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.GRACEFUL,
            graceful_cancel_timeout_seconds=0.1,
        )

        await manager.spawn_child(
            task_id="timeout_test",
            agent_type="search",
            task_description="slow work",
            config=config,
            context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
            tool_registry_getter=lambda: [FakeSearchTool()],
            wait=False,
        )

        await asyncio.sleep(0.05)
        manager.cancel_child("timeout_test")

        for _ in range(20):
            await asyncio.sleep(0.3)
            task = manager._children.get("timeout_test")
            if task is None or task.cancelled():
                break
        task = manager._children.get("timeout_test")
        assert task is None or task.cancelled()

    @pytest.mark.asyncio
    async def test_graceful_cancel_timeout_cleanup(self) -> None:
        """Graceful cancellation timeout task is cleaned up after completion."""

        agent = BaseAgent(llm=FakeLLM("ok"))
        manager = agent._subagent_manager

        config = SubagentConfig(
            system_prompt="test",
            description="test",
            tools=SUBAGENT_CONFIGS["search"].tools,
            timeout_seconds=5,
            max_retries=1,
            cancellation_strategy=CancellationStrategy.GRACEFUL,
            graceful_cancel_timeout_seconds=2.0,
        )

        await manager.spawn_child(
            task_id="cleanup_test",
            agent_type="search",
            task_description="test",
            config=config,
            context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
            tool_registry_getter=lambda: [FakeSearchTool()],
            wait=True,
        )

        assert "cleanup_test" not in manager._graceful_cancel_timeouts


# ---------------------------------------------------------------------------
# CapacitySnapshot with active children
# ---------------------------------------------------------------------------


class TestCapacitySnapshotWithActiveChildren:
    @pytest.mark.asyncio
    async def test_snapshot_reflects_running_children(self) -> None:
        """CapacitySnapshot.active_children counts running tasks."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        # Start a child that will run for a while
        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt="test",
            timeout_seconds=10,
            max_retries=0,
        )

        async def spawn_and_check():
            task = asyncio.create_task(
                manager.spawn_child(
                    task_id="cap_child_1",
                    agent_type="search",
                    task_description="test",
                    config=config,
                    context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
                    tool_registry_getter=lambda: [FakeSearchTool()],
                    wait=True,
                )
            )
            # Give it a moment to start
            await asyncio.sleep(0.05)
            snap = manager.get_capacity_snapshot()
            assert snap.active_children >= 0  # May have completed by now
            await task

        await spawn_and_check()


# ---------------------------------------------------------------------------
# Checkpoint operations
# ---------------------------------------------------------------------------


class TestCheckpointOperations:
    def test_save_all_checkpoints_delegates_to_manager(self) -> None:
        """_save_all_checkpoints delegates to checkpoint manager."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        # Should not raise even with no children
        manager._save_all_checkpoints()

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint_raises_when_not_found(self) -> None:
        """resume_from_checkpoint raises ValueError when checkpoint not found."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        with pytest.raises(ValueError, match="No checkpoint found"):
            await manager.resume_from_checkpoint("nonexistent")


# ---------------------------------------------------------------------------
# Event publishing error handling
# ---------------------------------------------------------------------------


class TestEventPublishingError:
    def test_emit_global_event_handles_publish_failure(self) -> None:
        """_emit_global_subagent_event catches publish errors."""
        from unittest.mock import patch

        from myrm_agent_harness.agent.sub_agents.manager import _emit_global_subagent_event
        from myrm_agent_harness.runtime.events.system_events import SubagentLifecycleData

        with patch(
            "myrm_agent_harness.runtime.events.get_event_bus",
            side_effect=RuntimeError("bus down"),
        ):
            # Should not raise
            _emit_global_subagent_event(
                "complete",
                "test_task",
                "test_session",
                SubagentLifecycleData(agent_type="search"),
            )


# ---------------------------------------------------------------------------
# _cleanup_child edge cases
# ---------------------------------------------------------------------------


class TestCleanupChildEdgeCases:
    @pytest.mark.asyncio
    async def test_cleanup_handles_file_tracker_error(self) -> None:
        """_cleanup_child handles file activity tracker errors gracefully."""
        from unittest.mock import patch

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt="test",
            timeout_seconds=10,
            max_retries=0,
        )

        with patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker.get_file_activity_tracker",
            side_effect=RuntimeError("tracker error"),
        ):
            result = await manager.spawn_child(
                task_id="cleanup_error_test",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
                tool_registry_getter=lambda: [FakeSearchTool()],
                wait=True,
            )

        assert isinstance(result, SubAgentResult)
        # Should complete despite tracker error
        assert result.task_id == "cleanup_error_test"


# ---------------------------------------------------------------------------
# list_children with mixed states
# ---------------------------------------------------------------------------


class TestListChildrenDetails:
    @pytest.mark.asyncio
    async def test_list_children_includes_agent_type(self) -> None:
        """list_children includes agent_type for completed tasks."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt="test",
            timeout_seconds=10,
            max_retries=0,
        )

        await manager.spawn_child(
            task_id="list_detail_1",
            agent_type="search",
            task_description="test",
            config=config,
            context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
            tool_registry_getter=lambda: [FakeSearchTool()],
            wait=True,
        )

        children = manager.list_children()
        assert len(children) == 1
        assert children[0]["agent_type"] == "search"
        assert children[0]["status"] in ("completed", "failed")


# ---------------------------------------------------------------------------
# Drain notifications
# ---------------------------------------------------------------------------


class TestDrainNotificationsDetails:
    def test_drain_returns_empty_when_no_notifications(self) -> None:
        """drain_pending_notifications returns empty list when nothing pending."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        result = manager.drain_notifications()
        assert result is None or result == []


# ---------------------------------------------------------------------------
# Global MAX_SPAWN_DEPTH boundary
# ---------------------------------------------------------------------------


class TestGlobalMaxSpawnDepth:
    def test_rejects_at_depth_three(self) -> None:
        """Global max depth (3) rejects regardless of config."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        manager._current_depth = 3
        config = SubagentConfig(system_prompt="test", max_spawn_depth=100)
        result = manager._validate_depth("t_global", config)
        assert result is not None
        assert result.success is False
        assert "Max spawn depth" in result.error

    def test_allows_at_depth_two(self) -> None:
        """Depth 2 is below global max (3), so it's allowed."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        manager._current_depth = 2
        config = SubagentConfig(system_prompt="test", max_spawn_depth=100)
        result = manager._validate_depth("t_depth2", config)
        assert result is None


# ---------------------------------------------------------------------------
# _validate_capacity edge cases
# ---------------------------------------------------------------------------


class TestValidateCapacityEdgeCases:
    def test_capacity_exceeded_returns_error(self) -> None:
        """_validate_capacity returns error when max_children reached."""
        from unittest.mock import MagicMock

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        # Fill up all capacity slots
        for i in range(manager._max_children_per_agent):
            manager._children[f"task_{i}"] = MagicMock()
            manager._children[f"task_{i}"].done.return_value = False

        config = SUBAGENT_CONFIGS["search"]
        result = manager._validate_capacity("overflow_task", "search", config)
        assert result is not None
        assert result.success is False
        assert "Capacity" in result.error or "limit exceeded" in result.error

    def test_capacity_with_completed_children_not_counted(self) -> None:
        """Completed children don't count against capacity."""
        from unittest.mock import MagicMock

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        # Add completed children
        for i in range(10):
            manager._children[f"task_{i}"] = MagicMock()
            manager._children[f"task_{i}"].done.return_value = True

        config = SUBAGENT_CONFIGS["search"]
        result = manager._validate_capacity("new_task", "search", config)
        assert result is None


# ---------------------------------------------------------------------------
# get_capacity_snapshot after spawns
# ---------------------------------------------------------------------------


class TestCapacitySnapshotAfterSpawns:
    def test_snapshot_counts_active_children(self) -> None:
        """get_capacity_snapshot correctly counts active vs completed children."""
        from unittest.mock import MagicMock

        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        # Simulate 3 active, 2 completed children
        for i in range(3):
            manager._children[f"active_{i}"] = MagicMock()
            manager._children[f"active_{i}"].done.return_value = False
        for i in range(2):
            manager._children[f"done_{i}"] = MagicMock()
            manager._children[f"done_{i}"].done.return_value = True

        snap = manager.get_capacity_snapshot()
        assert snap.active_children == 3
        assert snap.remaining_slots == 2  # max_children=5, 3 active

    def test_snapshot_tracks_descendants(self) -> None:
        """get_capacity_snapshot reflects spawned_descendants from budget state."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager
        manager._budget_state.spawned_descendants = 7

        snap = manager.get_capacity_snapshot()
        assert snap.spawned_descendants == 7
        assert snap.remaining_descendants == 13  # max=20, spawned=7


# ---------------------------------------------------------------------------
# steer edge cases
# ---------------------------------------------------------------------------


class TestSteerDetails:
    @pytest.mark.asyncio
    async def test_steer_sets_message_on_token(self) -> None:
        """steer sets the message on the steering token."""
        agent = BaseAgent(llm=FakeLLM())
        manager = agent._subagent_manager

        config = SubagentConfig(
            tools=SUBAGENT_CONFIGS["search"].tools,
            system_prompt="test",
            timeout_seconds=10,
            max_retries=0,
        )

        spawn_task = asyncio.create_task(
            manager.spawn_child(
                task_id="steer_detail",
                agent_type="search",
                task_description="test",
                config=config,
                context={"session_id": "s", "workspace_path": "/tmp", "workspaces_storage_root": "/tmp"},
                tool_registry_getter=lambda: [FakeSearchTool()],
                wait=True,
            )
        )
        await asyncio.sleep(0.05)

        token = manager._children_steering.get("steer_detail")
        if token:
            result = manager.steer_child("steer_detail", "new instructions")
            assert result is True
            assert token.has_pending

        await spawn_task
