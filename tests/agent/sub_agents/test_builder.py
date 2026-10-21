"""Tests for sub_agents/builder.py — tool filtering, result truncation, stats merge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.agent.sub_agents.builder import (
    build_child_agent,
    build_standalone_agent,
    filter_tools,
    merge_child_stats,
    resolve_llm,
    truncate_result,
)
from myrm_agent_harness.agent.sub_agents.spawn_prep import apply_readonly_to_config
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, WorkspacePolicy
from myrm_agent_harness.core.security.tool_registry import evict_skill_safety_metadata
from myrm_agent_harness.toolkits.mcp.tool_processing import prefix_tool_names, register_tool_annotations


def _make_tool(name: str) -> BaseTool:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# filter_tools
# ---------------------------------------------------------------------------


class TestFilterTools:
    def test_no_filter(self):
        tools = [_make_tool("read_file"), _make_tool("write_file")]
        cfg = SubagentConfig(system_prompt="s")
        result = filter_tools(cfg, tools)
        assert len(result) == 2

    def test_l1_default_blacklist_blocks(self):
        tools = [
            _make_tool("delegate_task_tool"),
            _make_tool("batch_delegate_tasks_tool"),
            _make_tool("read_file"),
        ]
        cfg = SubagentConfig(system_prompt="s")
        result = filter_tools(cfg, tools)
        names = [t.name for t in result]
        assert "delegate_task_tool" not in names
        assert "batch_delegate_tasks_tool" not in names
        assert "read_file" in names

    def test_l1_blocks_ask_question_tool(self):
        tools = [_make_tool("ask_question_tool"), _make_tool("read_file")]
        cfg = SubagentConfig(system_prompt="s")
        result = filter_tools(cfg, tools)
        names = [t.name for t in result]
        assert "ask_question_tool" not in names
        assert "read_file" in names

    def test_l1_ask_question_cannot_be_allowlisted(self):
        tools = [_make_tool("ask_question_tool"), _make_tool("read_file")]
        cfg = SubagentConfig(system_prompt="s", tools=("ask_question_tool", "read_file"))
        result = filter_tools(cfg, tools)
        names = [t.name for t in result]
        assert "ask_question_tool" not in names
        assert "read_file" in names

    def test_l2_allowlist(self):
        tools = [_make_tool("read_file"), _make_tool("write_file"), _make_tool("bash")]
        cfg = SubagentConfig(system_prompt="s", tools=("read_file", "bash"))
        result = filter_tools(cfg, tools)
        names = [t.name for t in result]
        assert "read_file" in names
        assert "bash" in names
        assert "write_file" not in names

    def test_l2_disallowed_tools(self):
        tools = [_make_tool("read_file"), _make_tool("dangerous")]
        cfg = SubagentConfig(system_prompt="s", disallowed_tools=frozenset({"dangerous"}))
        result = filter_tools(cfg, tools)
        names = [t.name for t in result]
        assert "dangerous" not in names
        assert "read_file" in names

    def test_l2_allowlist_missing_tool_warns(self):
        tools = [_make_tool("read_file")]
        cfg = SubagentConfig(system_prompt="s", tools=("read_file", "nonexistent"))
        result = filter_tools(cfg, tools)
        assert len(result) == 1

    def test_empty_parent_tools(self):
        cfg = SubagentConfig(system_prompt="s")
        result = filter_tools(cfg, [])
        assert result == []


# ---------------------------------------------------------------------------
# filter_tools — READ_ONLY_SANDBOX drops MCP tools not annotated read-only
# ---------------------------------------------------------------------------

_MCP_SERVER = "ro_filter_server"


def _mcp_tools_as_loaded() -> list[BaseTool]:
    """MCP tools shaped as ``toolkits/mcp/agent.py`` produces them: prefixed name, raw annotations, then registered."""
    raw = {
        "get_pull_request": {"readOnlyHint": True},
        "create_issue_comment": {"readOnlyHint": False},
        "list_issues": {},  # server declared no annotations
        "web_lookup": {"readOnlyHint": True, "openWorldHint": True},
    }
    tools: list[BaseTool] = [
        StructuredTool.from_function(func=lambda: "ok", name=name, description=name, metadata=dict(meta))
        for name, meta in raw.items()
    ]
    prefix_tool_names(tools, _MCP_SERVER)
    register_tool_annotations(tools, _MCP_SERVER)
    return tools


@pytest.fixture
def mcp_tools():
    tools = _mcp_tools_as_loaded()
    yield tools
    evict_skill_safety_metadata(f"mcp_{_MCP_SERVER}_skill")


class TestFilterToolsReadOnlyMcp:
    def _names(self, cfg: SubagentConfig, tools: list[BaseTool]) -> set[str]:
        return {t.name for t in filter_tools(cfg, tools)}

    def test_read_only_sandbox_keeps_only_annotated_read_only_mcp_tools(self, mcp_tools):
        cfg = SubagentConfig(system_prompt="s", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)
        assert self._names(cfg, mcp_tools) == {
            f"mcp__{_MCP_SERVER}__get_pull_request",
            f"mcp__{_MCP_SERVER}__web_lookup",
        }

    def test_writable_policy_keeps_every_mcp_tool(self, mcp_tools):
        cfg = SubagentConfig(system_prompt="s", workspace_policy=WorkspacePolicy.ISOLATED_COPY)
        assert self._names(cfg, mcp_tools) == {t.name for t in mcp_tools}

    def test_read_only_sandbox_leaves_native_tools_to_the_name_lists(self, mcp_tools):
        native = _make_tool("file_read_tool")
        cfg = SubagentConfig(system_prompt="s", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)
        assert "file_read_tool" in self._names(cfg, [native, *mcp_tools])

    def test_allowlisted_side_effect_mcp_tool_is_still_dropped(self, mcp_tools):
        allowed = (f"mcp__{_MCP_SERVER}__create_issue_comment", f"mcp__{_MCP_SERVER}__get_pull_request")
        cfg = SubagentConfig(system_prompt="s", tools=allowed, workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)
        assert self._names(cfg, mcp_tools) == {f"mcp__{_MCP_SERVER}__get_pull_request"}

    def test_apply_readonly_to_config_yields_the_same_filtering(self, mcp_tools):
        cfg = apply_readonly_to_config(SubagentConfig(system_prompt="s"), readonly=True)
        names = self._names(cfg, [_make_tool("file_write_tool"), _make_tool("file_read_tool"), *mcp_tools])
        assert names == {
            "file_read_tool",
            f"mcp__{_MCP_SERVER}__get_pull_request",
            f"mcp__{_MCP_SERVER}__web_lookup",
        }


# ---------------------------------------------------------------------------
# truncate_result
# ---------------------------------------------------------------------------


class TestTruncateResult:
    def test_no_limit(self):
        assert truncate_result("hello", None) == "hello"

    def test_empty_text(self):
        assert truncate_result("", 100) == ""

    def test_within_limit(self):
        assert truncate_result("short", 100) == "short"

    def test_exceeds_limit(self):
        text = "a" * 500
        result = truncate_result(text, 10)
        assert len(result) < len(text)
        assert "Truncated" in result
        assert "10 token" in result

    def test_exact_limit(self):
        text = "a" * 40
        result = truncate_result(text, 10)
        assert result == text


# ---------------------------------------------------------------------------
# merge_child_stats
# ---------------------------------------------------------------------------


class TestMergeChildStats:
    def test_non_tracker_parent_noop(self):
        merge_child_stats("not_a_tracker", MagicMock())

    def test_non_token_usage_child_noop(self):
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent = TokenTracker()
        child_stats = MagicMock(spec=[])
        merge_child_stats(parent, child_stats)

    def test_merges_basic_fields(self):
        from myrm_agent_harness.utils.token_economics.tracker import (
            TokenTracker,
            TokenUsage,
        )

        parent = TokenTracker()
        parent.usage.prompt_tokens = 10
        parent.usage.completion_tokens = 5

        child_usage = TokenUsage()
        child_usage.prompt_tokens = 20
        child_usage.completion_tokens = 15

        child_stats = MagicMock()
        child_stats.token_usage = child_usage
        child_stats.model_usage = None
        child_stats.cost_usd = 0.5
        child_stats.cost_status = "actual"

        merge_child_stats(parent, child_stats)
        assert parent.usage.prompt_tokens == 30
        assert parent.usage.completion_tokens == 20
        assert parent.total_cost_usd == 0.5
        assert parent.cost_status == "actual"

    def test_merges_model_usage_dict(self):
        from myrm_agent_harness.utils.token_economics.tracker import (
            TokenTracker,
            TokenUsage,
        )

        parent = TokenTracker()
        child_usage = TokenUsage()
        child_stats = MagicMock()
        child_stats.token_usage = child_usage
        child_stats.model_usage = {"gpt-4": {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.1}}
        child_stats.cost_usd = 0.1
        child_stats.cost_status = "estimated"

        merge_child_stats(parent, child_stats)
        assert "gpt-4" in parent.model_usage
        assert parent.model_usage["gpt-4"].prompt_tokens == 100
        assert parent.model_cost.get("gpt-4") == 0.1


# ---------------------------------------------------------------------------
# resolve_llm
# ---------------------------------------------------------------------------


class TestResolveLlm:
    @pytest.mark.asyncio
    async def test_config_llm_override(self):
        llm_obj = MagicMock()
        cfg = SubagentConfig(system_prompt="s", llm=llm_obj)
        parent = MagicMock()
        result = await resolve_llm(cfg, parent)
        assert result is llm_obj

    @pytest.mark.asyncio
    async def test_model_resolver_success(self):
        resolved_llm = MagicMock()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=resolved_llm)
        cfg = SubagentConfig(system_prompt="s", model="gpt-4", model_resolver=resolver)
        parent = MagicMock()
        result = await resolve_llm(cfg, parent)
        assert result is resolved_llm

    @pytest.mark.asyncio
    async def test_model_resolver_failure_falls_back(self):
        resolver = MagicMock()
        resolver.resolve = AsyncMock(side_effect=RuntimeError("fail"))
        parent_llm = MagicMock()
        cfg = SubagentConfig(system_prompt="s", model="gpt-4", model_resolver=resolver)
        parent = MagicMock()
        parent.llm = parent_llm
        result = await resolve_llm(cfg, parent)
        assert result is parent_llm

    @pytest.mark.asyncio
    async def test_model_without_resolver(self):
        parent_llm = MagicMock()
        cfg = SubagentConfig(system_prompt="s", model="gpt-4")
        parent = MagicMock()
        parent.llm = parent_llm
        result = await resolve_llm(cfg, parent)
        assert result is parent_llm

    @pytest.mark.asyncio
    async def test_no_model_no_llm(self):
        parent_llm = MagicMock()
        cfg = SubagentConfig(system_prompt="s")
        parent = MagicMock()
        parent.llm = parent_llm
        result = await resolve_llm(cfg, parent)
        assert result is parent_llm

    @pytest.mark.asyncio
    async def test_no_model_with_resolver_triggers_auto_routing(self):
        """When config.model is None but model_resolver exists, resolver is called with 'default'."""
        resolved_llm = MagicMock()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=resolved_llm)
        cfg = SubagentConfig(system_prompt="s", model_resolver=resolver)
        parent = MagicMock()
        result = await resolve_llm(cfg, parent, task_description="search for pricing info")
        assert result is resolved_llm
        resolver.resolve.assert_awaited_once_with(
            "default",
            complexity_tier=None,
            task_description="search for pricing info",
        )

    @pytest.mark.asyncio
    async def test_resolver_receives_complexity_tier(self):
        """Verify complexity_tier is passed through to resolver."""
        resolved_llm = MagicMock()
        resolver = MagicMock()
        resolver.resolve = AsyncMock(return_value=resolved_llm)
        cfg = SubagentConfig(system_prompt="s", model="gpt-4", model_resolver=resolver)
        parent = MagicMock()
        result = await resolve_llm(cfg, parent, complexity_tier="simple")
        assert result is resolved_llm
        resolver.resolve.assert_awaited_once_with(
            "gpt-4",
            complexity_tier="simple",
            task_description=None,
        )


# ---------------------------------------------------------------------------
# build_child_agent / build_standalone_agent
# ---------------------------------------------------------------------------


class TestBuildAgents:
    @pytest.mark.asyncio
    async def test_build_child_agent_bare(self):
        cfg = SubagentConfig(system_prompt="child prompt", max_turns=10, timeout_seconds=60)
        parent = MagicMock()
        parent.llm = MagicMock()
        parent.executor = MagicMock()
        parent.config = MagicMock(recursion_limit=50)

        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_agent:
            mock_child = MagicMock()
            mock_child._subagent_manager.inherit_runtime_limits = MagicMock()
            mock_agent.return_value = mock_child
            await build_child_agent(cfg, [], "do something", parent, 0)
            assert mock_agent.called
            call_kwargs = mock_agent.call_args[1]
            assert "child prompt" in call_kwargs["system_prompt"]
            assert call_kwargs["config"].recursion_limit == 20  # max_turns * 2
            mock_child._subagent_manager.inherit_runtime_limits.assert_called_once()
            assert mock_child._subagent_manager.inherit_runtime_limits.call_args[1]["current_depth"] == 1

    @pytest.mark.asyncio
    async def test_build_child_agent_recursion_limit_independent_of_parent(self):
        """Child recursion budget is driven by max_turns alone — never capped by a lower parent limit."""
        cfg = SubagentConfig(system_prompt="child prompt", max_turns=40)
        parent = MagicMock()
        parent.llm = MagicMock()
        parent.executor = MagicMock()
        parent.config = MagicMock(recursion_limit=20)

        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_agent:
            mock_child = MagicMock()
            mock_child._subagent_manager.inherit_runtime_limits = MagicMock()
            mock_agent.return_value = mock_child
            await build_child_agent(cfg, [], "do something", parent, 0)
            call_kwargs = mock_agent.call_args[1]
            assert call_kwargs["config"].recursion_limit == 80  # max_turns * 2, parent ignored

    @pytest.mark.asyncio
    async def test_build_child_agent_with_factory(self):
        factory = MagicMock()
        mock_child = MagicMock()
        mock_child._subagent_manager.inherit_runtime_limits = MagicMock()
        factory.build = AsyncMock(return_value=mock_child)
        cfg = SubagentConfig(system_prompt="s", agent_factory=factory)
        parent = MagicMock()
        await build_child_agent(cfg, [], "task", parent, 2)
        factory.build.assert_awaited_once()
        mock_child._subagent_manager.inherit_runtime_limits.assert_called_once()
        assert mock_child._subagent_manager.inherit_runtime_limits.call_args[1]["current_depth"] == 3

    def test_build_standalone_agent(self):
        cfg = SubagentConfig(system_prompt="standalone", max_turns=5, timeout_seconds=30)
        llm = MagicMock()
        MagicMock()
        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_agent:
            mock_agent.return_value = MagicMock()
            build_standalone_agent(llm, cfg, [], "do standalone")
            call_kwargs = mock_agent.call_args[1]
            assert "standalone" in call_kwargs["system_prompt"]

    def test_build_standalone_no_task(self):
        cfg = SubagentConfig(system_prompt="bare")
        llm = MagicMock()
        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_agent:
            mock_agent.return_value = MagicMock()
            build_standalone_agent(llm, cfg, [], "")
            call_kwargs = mock_agent.call_args[1]
            assert call_kwargs["system_prompt"].startswith("bare")


class TestBuilderForkMode:
    @pytest.mark.asyncio
    async def test_build_child_agent_fork_mode_nullifies_system_prompt(self):
        cfg = SubagentConfig(system_prompt="child prompt", context_mode="fork")
        parent = MagicMock()
        parent.llm = MagicMock()
        parent.executor = MagicMock()
        parent.config = MagicMock(recursion_limit=50)

        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_agent:
            mock_child = MagicMock()
            mock_child._subagent_manager._current_depth = 0
            mock_agent.return_value = mock_child
            await build_child_agent(cfg, [], "do something", parent, 0)
            assert mock_agent.called
            call_kwargs = mock_agent.call_args[1]
            assert call_kwargs["system_prompt"] == ""
