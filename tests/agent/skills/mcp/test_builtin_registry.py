"""PTC builtin_registry unit tests.

Covers:
- BuiltinToolRegistry register/dispatch/query/description generation
- Default registry excludes web tools (native + PTC stubs cover web)
- Duplicate registration warning
- Unknown tool KeyError
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skills.mcp.builtin_registry import (
    BUILTIN_SKILL_NAME,
    BuiltinToolEntry,
    BuiltinToolRegistry,
)


class TestBuiltinToolRegistry:
    """BuiltinToolRegistry core behavior."""

    def test_register_and_has_tool(self) -> None:
        registry = BuiltinToolRegistry()
        handler = AsyncMock(return_value="ok")
        registry.register("test_tool", handler, "desc", {"x": "int"})
        assert registry.has_tool("test_tool")
        assert not registry.has_tool("nonexistent")

    @pytest.mark.asyncio
    async def test_dispatch_calls_handler(self) -> None:
        registry = BuiltinToolRegistry()
        handler = AsyncMock(return_value={"key": "value"})
        registry.register("my_tool", handler, "desc", {"a": "str"})

        result = await registry.dispatch("my_tool", {"a": "hello"}, trace_id="abc")
        handler.assert_awaited_once_with({"a": "hello"})
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_raises_key_error(self) -> None:
        registry = BuiltinToolRegistry()
        with pytest.raises(KeyError, match="not found"):
            await registry.dispatch("nonexistent", {})

    def test_tool_names_sorted(self) -> None:
        registry = BuiltinToolRegistry()
        for name in ["zebra", "alpha", "mid"]:
            registry.register(name, AsyncMock(), "d", {})
        assert registry.tool_names == ["alpha", "mid", "zebra"]

    def test_get_ptc_description_empty(self) -> None:
        registry = BuiltinToolRegistry()
        assert registry.get_ptc_description() == ""

    def test_get_ptc_description_contains_tool(self) -> None:
        registry = BuiltinToolRegistry()
        registry.register("demo", AsyncMock(), "A demo tool", {"q": "str"}, return_type="list")
        desc = registry.get_ptc_description()
        assert "myrm_tools.demo" in desc
        assert "PTC" in desc

    def test_overwrite_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        registry = BuiltinToolRegistry()
        registry.register("dup", AsyncMock(), "first", {})
        with caplog.at_level("WARNING"):
            registry.register("dup", AsyncMock(), "second", {})
        assert "already registered" in caplog.text


class TestBuiltinSkillName:
    def test_value(self) -> None:
        assert BUILTIN_SKILL_NAME == "__builtin__"


class TestBuiltinToolEntry:
    def test_frozen(self) -> None:
        entry = BuiltinToolEntry(handler=AsyncMock(), description="d", parameters={})
        with pytest.raises(AttributeError):
            entry.description = "new"  # type: ignore[misc]

    def test_default_return_type(self) -> None:
        entry = BuiltinToolEntry(handler=AsyncMock(), description="d", parameters={})
        assert entry.return_type == "str"


class TestGetBuiltinToolRegistry:
    """get_builtin_tool_registry lazy init and default tool registration."""

    def test_registers_ptc_only_default_tools(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        registry = mod.get_builtin_tool_registry()
        expected = {"session_store", "session_load", "session_keys", "notify"}
        assert set(registry.tool_names) == expected
        mod._registry = None

    def test_default_ptc_description_excludes_web_tools(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        registry = mod.get_builtin_tool_registry()
        desc = registry.get_ptc_description()
        assert "myrm_tools.web_search" not in desc
        assert "myrm_tools.web_fetch" not in desc
        assert "myrm_tools.session_store" in desc
        assert "myrm_tools.notify" in desc
        mod._registry = None

    def test_singleton_behavior(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.builtin_registry as mod

        mod._registry = None
        r1 = mod.get_builtin_tool_registry()
        r2 = mod.get_builtin_tool_registry()
        assert r1 is r2
        mod._registry = None
