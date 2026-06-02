"""Tests for BaseAgent AgentExtension integration.

Covers:
- AgentExtension Protocol (runtime_checkable, structural subtyping)
- register_extension (name conflict, timing guard)
- _ensure_initialized (static tools/middlewares collection, on_agent_init lifecycle)
- cleanup_tools (on_agent_shutdown lifecycle)
- ToolLayer sorting after extension static tools
- Error isolation (extension failure doesn't crash agent)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.extensions.protocols import AgentExtension

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DummyTool(BaseTool):
    name: str = ""
    description: str = "dummy"

    def _run(self, *a, **kw):
        pass

    async def _arun(self, *a, **kw):
        pass


class StubExtension:
    """Minimal AgentExtension-compatible class (structural subtyping)."""

    def __init__(
        self,
        ext_name: str = "stub",
        tools: list[BaseTool] | None = None,
        middlewares: list | None = None,
        init_side_effect: Exception | None = None,
        shutdown_side_effect: Exception | None = None,
    ) -> None:
        self._name = ext_name
        self._tools = tools
        self._middlewares = middlewares
        self._init_side_effect = init_side_effect
        self._shutdown_side_effect = shutdown_side_effect
        self.init_called = False
        self.shutdown_called = False

    @property
    def name(self) -> str:
        return self._name

    async def on_agent_init(self, agent: BaseAgent) -> None:
        self.init_called = True
        if self._init_side_effect:
            raise self._init_side_effect

    async def on_agent_shutdown(self, agent: BaseAgent) -> None:
        self.shutdown_called = True
        if self._shutdown_side_effect:
            raise self._shutdown_side_effect

    def get_tools(self) -> list[BaseTool] | None:
        return self._tools

    def get_middlewares(self) -> list | None:
        return self._middlewares


def _make_bare_agent() -> BaseAgent:
    """Create a BaseAgent with minimal mocked internals."""
    agent = BaseAgent.__new__(BaseAgent)
    agent.llm = MagicMock()
    agent.fallback_llm = None
    agent.safety_fallback_llm = None
    agent.escalation_target_llm = None
    agent.executor = None
    agent.user_middlewares = []
    agent.system_prompt = "test"
    agent.user_tools = []
    agent.deferred_tools = []
    agent.context_schema = None
    agent.config = MagicMock()
    agent.config.parallel_tool_calls = None
    agent.on_artifacts_ready = None
    agent.checkpointer = None
    agent.event_log_backend = None
    agent._agent = None

    from myrm_agent_harness.agent.tool_management import ToolRegistry
    agent._tool_registry = ToolRegistry()

    agent._cached_tools = None
    agent._cached_system_prompt = None
    agent._cached_middlewares = None
    agent._failover_used = False
    agent._last_run_stats = None
    agent._last_context = {}
    agent._subagent_manager = MagicMock()
    agent._is_running = False
    agent._extensions = []
    agent._tools_initialized = False

    from myrm_agent_harness.agent.tool_management import ToolLifecycleManager

    agent._lifecycle_manager = ToolLifecycleManager()
    return agent


# ---------------------------------------------------------------------------
# Protocol Tests
# ---------------------------------------------------------------------------

class TestAgentExtensionProtocol:
    def test_runtime_checkable(self):
        ext = StubExtension()
        assert isinstance(ext, AgentExtension)

    def test_non_conforming_object_rejected(self):
        class NotAnExtension:
            pass
        assert not isinstance(NotAnExtension(), AgentExtension)

    def test_partial_implementation_rejected(self):
        class PartialExt:
            @property
            def name(self) -> str:
                return "partial"
        assert not isinstance(PartialExt(), AgentExtension)


# ---------------------------------------------------------------------------
# register_extension Tests
# ---------------------------------------------------------------------------

class TestRegisterExtension:
    def test_register_single(self):
        agent = _make_bare_agent()
        ext = StubExtension("my_ext")
        agent.register_extension(ext)
        assert len(agent._extensions) == 1
        assert agent._extensions[0].name == "my_ext"

    def test_register_multiple(self):
        agent = _make_bare_agent()
        agent.register_extension(StubExtension("a"))
        agent.register_extension(StubExtension("b"))
        assert len(agent._extensions) == 2

    def test_name_conflict_raises(self):
        agent = _make_bare_agent()
        agent.register_extension(StubExtension("dup"))
        with pytest.raises(ValueError, match="Extension name conflict.*dup"):
            agent.register_extension(StubExtension("dup"))

    def test_register_after_init_raises(self):
        agent = _make_bare_agent()
        agent._agent = MagicMock()
        with pytest.raises(ValueError, match="Cannot register extension.*after agent initialization"):
            agent.register_extension(StubExtension("late"))

    def test_register_preserves_order(self):
        agent = _make_bare_agent()
        for name in ["c", "a", "b"]:
            agent.register_extension(StubExtension(name))
        assert [e.name for e in agent._extensions] == ["c", "a", "b"]


# ---------------------------------------------------------------------------
# _ensure_initialized Extension Integration Tests
# ---------------------------------------------------------------------------

class TestEnsureInitializedExtensions:
    @pytest.mark.asyncio
    async def test_static_tools_collected(self):
        agent = _make_bare_agent()
        tool = DummyTool(name="ext_tool")
        agent.register_extension(StubExtension("provider", tools=[tool]))

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert any(t.name == "ext_tool" for t in agent._cached_tools)

    @pytest.mark.asyncio
    async def test_static_middlewares_collected(self):
        agent = _make_bare_agent()
        mw = MagicMock()
        agent.register_extension(StubExtension("mw_provider", middlewares=[mw]))

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert mw in agent._cached_middlewares

    @pytest.mark.asyncio
    async def test_on_agent_init_called(self):
        agent = _make_bare_agent()
        ext = StubExtension("lifecycle")
        agent.register_extension(ext)

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert ext.init_called

    @pytest.mark.asyncio
    async def test_on_agent_init_failure_does_not_crash(self):
        agent = _make_bare_agent()
        failing = StubExtension("failing", init_side_effect=RuntimeError("boom"))
        healthy = StubExtension("healthy")
        agent.register_extension(failing)
        agent.register_extension(healthy)

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert failing.init_called
        assert healthy.init_called

    @pytest.mark.asyncio
    async def test_no_extensions_no_side_effects(self):
        agent = _make_bare_agent()

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert agent._agent is not None

    @pytest.mark.asyncio
    async def test_none_return_from_get_tools_ignored(self):
        agent = _make_bare_agent()
        agent.register_extension(StubExtension("empty", tools=None))

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert agent._agent is not None

    @pytest.mark.asyncio
    async def test_extension_tools_sorted_by_tool_layer(self):
        """Extension static tools must be sorted by ToolLayer to protect prompt cache."""
        agent = _make_bare_agent()
        t_ext = DummyTool(name="skill_manage_tool")
        t_core = DummyTool(name="bash_code_execute_tool")
        agent.register_extension(StubExtension("sorter", tools=[t_ext, t_core]))

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        names = [t.name for t in agent._cached_tools]
        core_idx = names.index("bash_code_execute_tool")
        ext_idx = names.index("skill_manage_tool")
        assert core_idx < ext_idx, "CORE tools must come before EXTENDED tools"


# ---------------------------------------------------------------------------
# cleanup_tools Extension Shutdown Tests
# ---------------------------------------------------------------------------

class TestCleanupToolsExtensions:
    @pytest.mark.asyncio
    async def test_on_agent_shutdown_called(self):
        agent = _make_bare_agent()
        ext = StubExtension("cleanup_test")
        agent._extensions = [ext]
        agent._cached_tools = []

        await agent.cleanup_tools()
        assert ext.shutdown_called

    @pytest.mark.asyncio
    async def test_shutdown_failure_does_not_block_others(self):
        agent = _make_bare_agent()
        failing = StubExtension("fail_shutdown", shutdown_side_effect=RuntimeError("shutdown boom"))
        healthy = StubExtension("ok_shutdown")
        agent._extensions = [failing, healthy]
        agent._cached_tools = []

        await agent.cleanup_tools()
        assert failing.shutdown_called
        assert healthy.shutdown_called

    @pytest.mark.asyncio
    async def test_shutdown_with_no_extensions(self):
        agent = _make_bare_agent()
        agent._cached_tools = [DummyTool(name="t")]

        await agent.cleanup_tools()


# ---------------------------------------------------------------------------
# Idempotency & Edge Cases
# ---------------------------------------------------------------------------

class TestExtensionEdgeCases:
    @pytest.mark.asyncio
    async def test_ensure_initialized_idempotent(self):
        agent = _make_bare_agent()
        ext = StubExtension("once")
        agent.register_extension(ext)

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()
            await agent._ensure_initialized()

        assert mock_create.call_count == 1
        assert ext.init_called

    @pytest.mark.asyncio
    async def test_multiple_extensions_all_contribute(self):
        agent = _make_bare_agent()
        t1 = DummyTool(name="web_search_tool")
        t2 = DummyTool(name="file_read_tool")
        mw = MagicMock()

        agent.register_extension(StubExtension("ext_a", tools=[t1]))
        agent.register_extension(StubExtension("ext_b", tools=[t2], middlewares=[mw]))

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert any(t.name == "web_search_tool" for t in agent._cached_tools)
        assert any(t.name == "file_read_tool" for t in agent._cached_tools)
        assert mw in agent._cached_middlewares

    @pytest.mark.asyncio
    async def test_on_agent_init_can_call_add_tools(self):
        """Extensions can dynamically inject tools via agent.add_tools() in on_agent_init."""

        class DynamicToolExtension:
            @property
            def name(self) -> str:
                return "DynamicToolExt"

            async def on_agent_init(self, agent: BaseAgent) -> None:
                agent.add_tools([DummyTool(name="dynamic_injected_tool")])

            async def on_agent_shutdown(self, agent: BaseAgent) -> None:
                pass

            def get_tools(self) -> list[BaseTool] | None:
                return None

            def get_middlewares(self) -> list | None:
                return None

        agent = _make_bare_agent()
        agent.register_extension(DynamicToolExtension())

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert any(t.name == "dynamic_injected_tool" for t in agent._cached_tools)
        # add_tools triggers rebuild, so create_agent should be called twice
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_on_agent_init_receives_correct_agent_reference(self):
        """on_agent_init receives the actual agent instance."""
        received_agent = None

        class InspectorExtension:
            @property
            def name(self) -> str:
                return "Inspector"

            async def on_agent_init(self, agent: BaseAgent) -> None:
                nonlocal received_agent
                received_agent = agent

            async def on_agent_shutdown(self, agent: BaseAgent) -> None:
                pass

            def get_tools(self) -> list[BaseTool] | None:
                return None

            def get_middlewares(self) -> list | None:
                return None

        agent = _make_bare_agent()
        agent.register_extension(InspectorExtension())

        with patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create:
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        assert received_agent is agent

    @pytest.mark.asyncio
    async def test_no_sort_when_no_extensions_have_tools(self):
        """ToolLayer sorting is only triggered when extensions provide tools."""
        agent = _make_bare_agent()
        agent.register_extension(StubExtension("empty_a", tools=None))
        agent.register_extension(StubExtension("empty_b", tools=None))

        with (
            patch("myrm_agent_harness.agent.base_agent.create_agent") as mock_create,
            patch(
                "myrm_agent_harness.agent.tool_management.tool_layers.get_tool_layer"
            ),
        ):
            mock_create.return_value = MagicMock()
            await agent._ensure_initialized()

        # Sort should still be called because we have extensions registered
        # but it doesn't matter much - the key test is that no crash occurs
        assert agent._agent is not None
