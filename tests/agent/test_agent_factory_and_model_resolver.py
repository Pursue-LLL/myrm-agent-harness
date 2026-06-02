"""Tests for AgentFactory Protocol, ModelResolver Protocol, and SubagentConfig extensions.

Covers:
- AgentFactory Protocol conformance
- ModelResolver Protocol conformance
- SubagentConfig.display_name field
- SubagentConfig.model_resolver field
- SubagentConfig.agent_factory field
- resolve_llm() with model_resolver (4-level chain)
- build_child_agent() with agent_factory delegation
- build_child_agent() bare BaseAgent path
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.types import _SUBAGENT_DEFAULT_BLACKLIST, SubagentConfig


class TestSubagentConfigNewFields:
    def test_display_name_default_empty(self):
        cfg = SubagentConfig(system_prompt="test")
        assert cfg.display_name == ""

    def test_display_name_set(self):
        cfg = SubagentConfig(system_prompt="test", display_name="Research Assistant")
        assert cfg.display_name == "Research Assistant"

    def test_model_resolver_default_none(self):
        cfg = SubagentConfig(system_prompt="test")
        assert cfg.model_resolver is None

    def test_agent_factory_default_none(self):
        cfg = SubagentConfig(system_prompt="test")
        assert cfg.agent_factory is None

    def test_model_resolver_set(self):
        resolver = MagicMock()
        cfg = SubagentConfig(system_prompt="test", model_resolver=resolver)
        assert cfg.model_resolver is resolver

    def test_agent_factory_set(self):
        factory = MagicMock()
        cfg = SubagentConfig(system_prompt="test", agent_factory=factory)
        assert cfg.agent_factory is factory

    def test_all_new_fields_together(self):
        resolver = MagicMock()
        factory = MagicMock()
        cfg = SubagentConfig(
            system_prompt="test", display_name="My Agent", model_resolver=resolver, agent_factory=factory
        )
        assert cfg.display_name == "My Agent"
        assert cfg.model_resolver is resolver
        assert cfg.agent_factory is factory

    def test_repr_excludes_model_resolver_and_factory(self):
        resolver = MagicMock()
        factory = MagicMock()
        cfg = SubagentConfig(system_prompt="test", model_resolver=resolver, agent_factory=factory)
        r = repr(cfg)
        assert "model_resolver" not in r
        assert "agent_factory" not in r


class TestModelResolverProtocol:
    def test_has_resolve_method(self):
        class MyResolver:
            async def resolve(self, model_name: str) -> object:
                return MagicMock()

        resolver = MyResolver()
        assert hasattr(resolver, "resolve")
        assert callable(resolver.resolve)

    @pytest.mark.asyncio
    async def test_resolver_called(self):
        mock_llm = MagicMock()

        class MyResolver:
            async def resolve(self, model_name: str) -> object:
                return mock_llm

        resolver = MyResolver()
        result = await resolver.resolve("gpt-4o-mini")
        assert result is mock_llm


class TestAgentFactoryProtocol:
    def test_has_build_method(self):
        class MyFactory:
            async def build(self, config, tools, task_description, parent_agent, current_depth, complexity_tier=None):
                return MagicMock()

        factory = MyFactory()
        assert hasattr(factory, "build")
        assert callable(factory.build)


class TestResolveLlm:
    @pytest.mark.asyncio
    async def test_level1_config_llm_wins(self):
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm

        mock_llm = MagicMock()
        config = SubagentConfig(system_prompt="test", llm=mock_llm)
        parent = MagicMock()

        result = await resolve_llm(config, parent)
        assert result is mock_llm

    @pytest.mark.asyncio
    async def test_level2_model_resolver_resolves(self):
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm

        resolved_llm = MagicMock()
        resolver = AsyncMock()
        resolver.resolve.return_value = resolved_llm

        config = SubagentConfig(system_prompt="test", model="gpt-4o-mini", model_resolver=resolver)
        parent = MagicMock()

        result = await resolve_llm(config, parent)
        assert result is resolved_llm
        resolver.resolve.assert_awaited_once_with("gpt-4o-mini")

    @pytest.mark.asyncio
    async def test_level2_model_resolver_fails_falls_to_parent(self):
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm

        resolver = AsyncMock()
        resolver.resolve.side_effect = ValueError("Model not found")

        parent_llm = MagicMock()
        config = SubagentConfig(system_prompt="test", model="nonexistent-model", model_resolver=resolver)
        parent = MagicMock()
        parent.llm = parent_llm

        result = await resolve_llm(config, parent)
        assert result is parent_llm

    @pytest.mark.asyncio
    async def test_level3_model_without_resolver_falls_to_parent(self):
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm

        parent_llm = MagicMock()
        config = SubagentConfig(system_prompt="test", model="gpt-4o-mini")
        parent = MagicMock()
        parent.llm = parent_llm

        result = await resolve_llm(config, parent)
        assert result is parent_llm

    @pytest.mark.asyncio
    async def test_level4_no_model_no_llm_falls_to_parent(self):
        from myrm_agent_harness.agent.sub_agents.builder import resolve_llm

        parent_llm = MagicMock()
        config = SubagentConfig(system_prompt="test")
        parent = MagicMock()
        parent.llm = parent_llm

        result = await resolve_llm(config, parent)
        assert result is parent_llm


class TestBuildChildAgent:
    @pytest.mark.asyncio
    async def test_agent_factory_delegation(self):
        from myrm_agent_harness.agent.sub_agents.builder import build_child_agent

        mock_child = MagicMock()
        mock_child._subagent_manager = MagicMock()
        mock_child._subagent_manager._current_depth = 0

        factory = AsyncMock()
        factory.build.return_value = mock_child

        config = SubagentConfig(system_prompt="test", agent_factory=factory)
        parent = MagicMock()

        result = await build_child_agent(config, [], "do something", parent, 1)

        factory.build.assert_awaited_once_with(
            config=config,
            tools=[],
            task_description="do something",
            parent_agent=parent,
            current_depth=1,
            complexity_tier=None,
        )
        assert result is mock_child
        mock_child._subagent_manager.inherit_runtime_limits.assert_called_once()
        assert mock_child._subagent_manager.inherit_runtime_limits.call_args[1]["current_depth"] == 2

    @pytest.mark.asyncio
    async def test_agent_factory_build_error_propagates(self):
        from myrm_agent_harness.agent.sub_agents.builder import build_child_agent

        factory = AsyncMock()
        factory.build.side_effect = RuntimeError("factory init failed")

        config = SubagentConfig(system_prompt="test", agent_factory=factory)
        parent = MagicMock()

        with pytest.raises(RuntimeError, match="factory init failed"):
            await build_child_agent(config, [], "task", parent, 0)

    @pytest.mark.asyncio
    async def test_bare_base_agent_path(self):
        from myrm_agent_harness.agent.sub_agents.builder import build_child_agent

        parent_llm = MagicMock()
        parent = MagicMock()
        parent.llm = parent_llm
        parent.executor = MagicMock()
        parent.config = MagicMock()
        parent.config.recursion_limit = 100

        config = SubagentConfig(system_prompt="test system", max_turns=10)

        with patch("myrm_agent_harness.agent.base_agent.BaseAgent") as mock_base_agent_cls:
            mock_instance = MagicMock()
            mock_instance._subagent_manager = MagicMock()
            mock_instance._subagent_manager._current_depth = 0
            mock_base_agent_cls.return_value = mock_instance

            result = await build_child_agent(config, [], "task desc", parent, 0)

            assert result is mock_instance
            mock_base_agent_cls.assert_called_once()
            call_kwargs = mock_base_agent_cls.call_args[1]
            assert "task desc" not in call_kwargs["system_prompt"]
            assert "test system" in call_kwargs["system_prompt"]
            mock_instance._subagent_manager.inherit_runtime_limits.assert_called_once()
            assert mock_instance._subagent_manager.inherit_runtime_limits.call_args[1]["current_depth"] == 1


class TestFilterTools:
    def test_l1_blacklist_applied(self):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tools = []
        for name in ["web_search", "read_file", *list(_SUBAGENT_DEFAULT_BLACKLIST)[:2]]:
            t = MagicMock()
            t.name = name
            tools.append(t)

        config = SubagentConfig(system_prompt="test")
        filtered = filter_tools(config, tools)
        filtered_names = {t.name for t in filtered}

        for blocked in _SUBAGENT_DEFAULT_BLACKLIST:
            assert blocked not in filtered_names

    def test_l2_allowlist_filter(self):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tools = []
        for name in ["web_search", "read_file", "write_file"]:
            t = MagicMock()
            t.name = name
            tools.append(t)

        config = SubagentConfig(system_prompt="test", tools=("web_search"))
        filtered = filter_tools(config, tools)
        assert len(filtered) == 1
        assert filtered[0].name == "web_search"

    def test_l2_blocklist_filter(self):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        tools = []
        for name in ["web_search", "read_file", "write_file"]:
            t = MagicMock()
            t.name = name
            tools.append(t)

        config = SubagentConfig(system_prompt="test", disallowed_tools=frozenset({"write_file"}))
        filtered = filter_tools(config, tools)
        filtered_names = {t.name for t in filtered}
        assert "write_file" not in filtered_names
        assert "web_search" in filtered_names

    def test_empty_parent_tools(self):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools

        config = SubagentConfig(system_prompt="test")
        filtered = filter_tools(config, [])
        assert filtered == []


class TestTruncateResult:
    def test_no_truncation_when_within_limit(self):
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        text = "short text"
        assert truncate_result(text, 1000) == text

    def test_truncation_at_limit(self):
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        text = "x" * 1000
        result = truncate_result(text, 10)
        assert len(result) < len(text)
        assert "Truncated" in result

    def test_no_limit_returns_full_text(self):
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        text = "x" * 10000
        assert truncate_result(text, None) == text

    def test_empty_text(self):
        from myrm_agent_harness.agent.sub_agents.builder import truncate_result

        assert truncate_result("", 100) == ""


class TestMergeChildStats:
    def test_merge_token_usage(self):
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker, TokenUsage

        parent_tracker = TokenTracker()
        parent_tracker.usage.prompt_tokens = 100
        parent_tracker.usage.completion_tokens = 50

        child_stats = MagicMock()
        child_usage = TokenUsage()
        child_usage.prompt_tokens = 200
        child_usage.completion_tokens = 100
        child_stats.token_usage = child_usage
        child_stats.model_usage = None
        child_stats.cost_usd = 0.05
        child_stats.cost_status = "actual"

        merge_child_stats(parent_tracker, child_stats)

        assert parent_tracker.usage.prompt_tokens == 300
        assert parent_tracker.usage.completion_tokens == 150
        assert parent_tracker.total_cost_usd == 0.05
        assert parent_tracker.cost_status == "actual"

    def test_merge_skipped_for_non_tracker(self):
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats

        merge_child_stats("not a tracker", MagicMock())

    def test_merge_skipped_for_non_usage(self):
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

        parent_tracker = TokenTracker()
        child_stats = MagicMock()
        child_stats.token_usage = "not a TokenUsage"
        merge_child_stats(parent_tracker, child_stats)

    def test_merge_model_usage(self):
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker, TokenUsage

        parent_tracker = TokenTracker()

        child_usage = TokenUsage()
        child_usage.prompt_tokens = 50
        child_stats = MagicMock()
        child_stats.token_usage = child_usage
        child_stats.model_usage = {
            "gpt-4o": {
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "total_tokens": 80,
                "cost_usd": 0.01,
            }
        }
        child_stats.cost_usd = 0.01
        child_stats.cost_status = "actual"

        merge_child_stats(parent_tracker, child_stats)

        assert "gpt-4o" in parent_tracker.model_usage
        assert parent_tracker.model_usage["gpt-4o"].prompt_tokens == 50
        assert parent_tracker.model_cost["gpt-4o"] == 0.01

    def test_merge_model_usage_non_dict_data_skipped(self):
        from myrm_agent_harness.agent.sub_agents.builder import merge_child_stats
        from myrm_agent_harness.utils.token_economics.tracker import TokenTracker, TokenUsage

        parent_tracker = TokenTracker()

        child_usage = TokenUsage()
        child_stats = MagicMock()
        child_stats.token_usage = child_usage
        child_stats.model_usage = {"weird-model": "not-a-dict"}
        child_stats.cost_usd = 0.0
        child_stats.cost_status = "unknown"

        merge_child_stats(parent_tracker, child_stats)
        assert "weird-model" in parent_tracker.model_usage
        assert parent_tracker.model_usage["weird-model"].prompt_tokens == 0


class TestFilterToolsMissing:
    def test_missing_tools_warning(self):
        from myrm_agent_harness.agent.sub_agents.builder import filter_tools
        from myrm_agent_harness.agent.sub_agents.types import SubagentConfig

        tools = []
        for name in ["web_search", "read_file"]:
            t = MagicMock()
            t.name = name
            tools.append(t)

        config = SubagentConfig(system_prompt="test", tools=("web_search", "nonexistent_tool", "another_missing"))
        filtered = filter_tools(config, tools)
        assert len(filtered) == 1
        assert filtered[0].name == "web_search"
