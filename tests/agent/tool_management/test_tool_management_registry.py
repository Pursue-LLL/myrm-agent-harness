"""Tests for agent.tool_management.registry — ToolRegistry resolve/snapshot pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry, _extract_summary, _safe_extract_schema
from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSnapshot, ToolSource


def _make_tool(name: str, description: str = "desc", schema: type[BaseModel] | None = None) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    if schema is not None:
        tool.args_schema = schema
    else:
        tool.args_schema = None
    return tool


class TestExtractSummary:
    def test_single_line(self) -> None:
        assert _extract_summary("Hello world") == "Hello world"

    def test_multiline_takes_first_nonempty(self) -> None:
        assert _extract_summary("\n\n  First line  \nSecond") == "First line"

    def test_truncates_long_line(self) -> None:
        long = "x" * 200
        result = _extract_summary(long, max_len=10)
        assert result == "x" * 10 + "..."

    def test_empty_string(self) -> None:
        assert _extract_summary("") == ""

    def test_only_whitespace(self) -> None:
        assert _extract_summary("   \n  \n  ") == ""


class TestSafeExtractSchema:
    def test_no_schema(self) -> None:
        tool = MagicMock(spec=[])
        assert _safe_extract_schema(tool) is None

    def test_schema_none(self) -> None:
        tool = MagicMock()
        tool.args_schema = None
        assert _safe_extract_schema(tool) is None

    def test_valid_schema(self) -> None:
        class MySchema(BaseModel):
            query: str

        tool = MagicMock()
        tool.args_schema = MySchema
        result = _safe_extract_schema(tool)
        assert isinstance(result, dict)
        assert "properties" in result

    def test_schema_raises(self) -> None:
        tool = MagicMock()
        tool.args_schema = MagicMock()
        tool.args_schema.model_json_schema.side_effect = RuntimeError("boom")
        assert _safe_extract_schema(tool) is None


class TestToolRegistryRegister:
    def test_register_single(self) -> None:
        reg = ToolRegistry()
        tool = _make_tool("t1")
        reg.register(tool, source=ToolSource.META)
        assert reg.entry_count == 1

    def test_register_many(self) -> None:
        reg = ToolRegistry()
        tools = [_make_tool(f"t{i}") for i in range(5)]
        reg.register_many(tools, source=ToolSource.USER)
        assert reg.entry_count == 5

    def test_register_with_provider(self) -> None:
        reg = ToolRegistry()
        tool = _make_tool("t1")
        reg.register(tool, source=ToolSource.USER, provider="skill:web_search")
        entries = reg.entries_by_source()
        assert ToolSource.USER in entries

    def test_register_with_explicit_layer(self) -> None:
        reg = ToolRegistry()
        tool = _make_tool("t1")
        reg.register(tool, source=ToolSource.META, layer=ToolLayer.CORE)
        resolved = reg.resolve()
        assert len(resolved) == 1


class TestToolRegistryResolve:
    def test_dedup_meta_wins_over_user(self) -> None:
        reg = ToolRegistry()
        user_tool = _make_tool("search", description="user version")
        meta_tool = _make_tool("search", description="meta version")
        reg.register(user_tool, source=ToolSource.USER)
        reg.register(meta_tool, source=ToolSource.META)
        resolved = reg.resolve()
        assert len(resolved) == 1
        assert resolved[0].description == "meta version"

    def test_dedup_user_wins_over_middleware(self) -> None:
        reg = ToolRegistry()
        mw_tool = _make_tool("search", description="middleware version")
        user_tool = _make_tool("search", description="user version")
        reg.register(mw_tool, source=ToolSource.MIDDLEWARE)
        reg.register(user_tool, source=ToolSource.USER)
        resolved = reg.resolve()
        assert len(resolved) == 1
        assert resolved[0].description == "user version"

    def test_sort_by_layer_then_name(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("z_tool"), source=ToolSource.META, layer=ToolLayer.EXTENDED)
        reg.register(_make_tool("a_tool"), source=ToolSource.META, layer=ToolLayer.CORE)
        reg.register(_make_tool("m_tool"), source=ToolSource.META, layer=ToolLayer.COMMON)
        resolved = reg.resolve()
        names = [t.name for t in resolved]
        assert names == ["a_tool", "m_tool", "z_tool"]

    def test_empty_registry(self) -> None:
        reg = ToolRegistry()
        assert reg.resolve() == []


class TestToolRegistrySnapshot:
    def test_snapshot_returns_tool_snapshots(self) -> None:
        reg = ToolRegistry()
        reg.register(
            _make_tool("search", "Search the web\nDetailed description"), source=ToolSource.META, provider="builtin"
        )
        snaps = reg.snapshot()
        assert len(snaps) == 1
        s = snaps[0]
        assert isinstance(s, ToolSnapshot)
        assert s.name == "search"
        assert s.summary == "Search the web"
        assert s.source == "meta"
        assert s.provider == "builtin"

    def test_snapshot_with_schema(self) -> None:
        class QuerySchema(BaseModel):
            query: str
            limit: int = 10

        tool = _make_tool("search", "desc")
        tool.args_schema = QuerySchema
        reg = ToolRegistry()
        reg.register(tool, source=ToolSource.USER)
        snaps = reg.snapshot()
        assert snaps[0].parameters_schema is not None
        assert "properties" in snaps[0].parameters_schema

    def test_snapshot_deduplicates(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("t1"), source=ToolSource.MIDDLEWARE)
        reg.register(_make_tool("t1"), source=ToolSource.META)
        snaps = reg.snapshot()
        assert len(snaps) == 1

    def test_snapshot_empty(self) -> None:
        reg = ToolRegistry()
        assert reg.snapshot() == []

    def test_snapshot_includes_builtin_tool_id(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("cron_manage_tool", "Manage cron jobs"), source=ToolSource.USER)
        snaps = reg.snapshot()
        assert len(snaps) == 1
        assert snaps[0].builtin_tool_id == "cron"


class TestToolRegistryDiagnostics:
    def test_entries_by_source(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("a"), source=ToolSource.META)
        reg.register(_make_tool("b"), source=ToolSource.USER)
        reg.register(_make_tool("c"), source=ToolSource.META)
        result = reg.entries_by_source()
        assert set(result[ToolSource.META]) == {"a", "c"}
        assert result[ToolSource.USER] == ["b"]

    def test_entry_count(self) -> None:
        reg = ToolRegistry()
        assert reg.entry_count == 0
        reg.register(_make_tool("a"), source=ToolSource.META)
        assert reg.entry_count == 1


class TestToolLayerFunctions:
    def test_get_tool_layer_registered(self) -> None:
        from myrm_agent_harness.agent.tool_management.tool_layers import get_tool_layer

        assert get_tool_layer("file_read_tool") == ToolLayer.CORE
        assert get_tool_layer("web_search_tool") == ToolLayer.COMMON
        assert get_tool_layer("skill_select_tool") == ToolLayer.EXTENDED

    def test_get_tool_layer_unregistered_defaults_extended(self) -> None:
        from myrm_agent_harness.agent.tool_management.tool_layers import get_tool_layer

        assert get_tool_layer("mcp_github_tool") == ToolLayer.EXTENDED

    def test_register_tool_layer(self) -> None:
        from myrm_agent_harness.agent.tool_management.tool_layers import (
            _TOOL_LAYERS,
            get_tool_layer,
            register_tool_layer,
        )

        key = "_test_custom_tool"
        register_tool_layer(key, ToolLayer.COMMON)
        try:
            assert get_tool_layer(key) == ToolLayer.COMMON
        finally:
            _TOOL_LAYERS.pop(key, None)

    def test_default_layer_in_resolve(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("unknown_mcp_tool"), source=ToolSource.META)
        entries = reg._resolve_entries()
        assert entries[0].layer == ToolLayer.EXTENDED

    def test_alphabetical_ordering_within_layer(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("c_tool"), source=ToolSource.META, layer=ToolLayer.EXTENDED)
        reg.register(_make_tool("a_tool"), source=ToolSource.META, layer=ToolLayer.EXTENDED)
        reg.register(_make_tool("b_tool"), source=ToolSource.META, layer=ToolLayer.EXTENDED)
        resolved = reg.resolve()
        names = [t.name for t in resolved]
        assert names == ["a_tool", "b_tool", "c_tool"]

    def test_cache_stability_core_unaffected_by_extended(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("file_read_tool"), source=ToolSource.META, layer=ToolLayer.CORE)
        reg.register(_make_tool("bash_code_execute_tool"), source=ToolSource.META, layer=ToolLayer.CORE)
        reg.register(_make_tool("mcp_tool_a"), source=ToolSource.META, layer=ToolLayer.EXTENDED)

        resolved = reg.resolve()
        names = [t.name for t in resolved]
        assert names[:2] == ["bash_code_execute_tool", "file_read_tool"]
        assert names[2] == "mcp_tool_a"

    def test_memory_tools_sorted_before_web_search_in_common(self) -> None:
        from myrm_agent_harness.agent.tool_management.tool_layers import get_tool_layer

        for memory_tool in ("memory_manage_tool", "memory_recall_tool", "memory_save_tool"):
            assert get_tool_layer(memory_tool) == ToolLayer.COMMON

        reg = ToolRegistry()
        for name in (
            "web_search_tool",
            "memory_recall_tool",
            "file_read_tool",
            "memory_save_tool",
            "bash_code_execute_tool",
            "memory_manage_tool",
        ):
            reg.register(_make_tool(name), source=ToolSource.USER)
        names = [tool.name for tool in reg.resolve()]

        assert names[:2] == ["bash_code_execute_tool", "file_read_tool"]
        memory_block = ["memory_manage_tool", "memory_recall_tool", "memory_save_tool"]
        assert names[2:5] == memory_block
        assert names[5] == "web_search_tool"

    def test_extended_tools_append_after_common_prefix(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("file_read_tool"), source=ToolSource.META, layer=ToolLayer.CORE)
        reg.register(_make_tool("web_search_tool"), source=ToolSource.USER, layer=ToolLayer.COMMON)
        reg.register(_make_tool("memory_recall_tool"), source=ToolSource.USER, layer=ToolLayer.COMMON)
        common_prefix = [tool.name for tool in reg.resolve()]

        with_extended = ToolRegistry()
        for name in (
            "discover_capability_tool",
            "file_read_tool",
            "memory_recall_tool",
            "web_search_tool",
        ):
            layer = ToolLayer.EXTENDED if name == "discover_capability_tool" else None
            with_extended.register(_make_tool(name), source=ToolSource.USER, layer=layer)
        names = [tool.name for tool in with_extended.resolve()]

        assert names[: len(common_prefix)] == common_prefix
        assert names[len(common_prefix) :] == ["discover_capability_tool"]


class TestToolRegistryBindMode:
    def test_runtime_only_not_in_resolve(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("visible"), source=ToolSource.META)
        reg.register(
            _make_tool("_internal_hook"),
            source=ToolSource.MIDDLEWARE,
            bind_mode=ToolBindMode.RUNTIME_ONLY,
        )
        resolved = reg.resolve()
        names = [t.name for t in resolved]
        assert names == ["visible"]

    def test_runtime_only_in_get_runtime_tools(self) -> None:
        reg = ToolRegistry()
        reg.register(
            _make_tool("_internal_hook"),
            source=ToolSource.MIDDLEWARE,
            bind_mode=ToolBindMode.RUNTIME_ONLY,
        )
        reg.register(_make_tool("visible"), source=ToolSource.META)
        assert {t.name for t in reg.get_runtime_tools()} == {"_internal_hook"}

    def test_runtime_only_in_snapshot(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("active"), source=ToolSource.META)
        reg.register(
            _make_tool("_internal_hook"),
            source=ToolSource.META,
            bind_mode=ToolBindMode.RUNTIME_ONLY,
        )
        snaps = reg.snapshot()
        non_turn1_snaps = [
            s for s in snaps if s.bind_mode != ToolBindMode.TURN1.value
        ]
        turn1_snaps = [s for s in snaps if s.bind_mode == ToolBindMode.TURN1.value]
        assert len(non_turn1_snaps) == 1
        assert non_turn1_snaps[0].name == "_internal_hook"
        assert non_turn1_snaps[0].bind_mode == ToolBindMode.RUNTIME_ONLY.value
        assert len(turn1_snaps) == 1


class TestToolRegistryHasTool:
    def test_has_tool_exists(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("my_tool"), source=ToolSource.META)
        assert reg.has_tool("my_tool") is True

    def test_has_tool_not_exists(self) -> None:
        reg = ToolRegistry()
        assert reg.has_tool("nonexistent") is False

    def test_has_tool_runtime_only(self) -> None:
        reg = ToolRegistry()
        reg.register(
            _make_tool("runtime_one"),
            source=ToolSource.META,
            bind_mode=ToolBindMode.RUNTIME_ONLY,
        )
        assert reg.has_tool("runtime_one") is True

    def test_has_tool_after_duplicate_registration(self) -> None:
        reg = ToolRegistry()
        reg.register(_make_tool("dup"), source=ToolSource.META)
        reg.register(_make_tool("dup"), source=ToolSource.USER)
        assert reg.has_tool("dup") is True

    def test_has_tool_empty_registry(self) -> None:
        reg = ToolRegistry()
        assert reg.has_tool("anything") is False


class TestRegistryWarning:
    """Tests for the WARNING log when tools are not in _TOOL_LAYERS."""

    def test_unregistered_tool_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        reg = ToolRegistry()
        with caplog.at_level(logging.WARNING, logger="myrm_agent_harness.agent.tool_management.registry"):
            reg.register(_make_tool("totally_unknown_xyz_tool"), source=ToolSource.META)
        assert "totally_unknown_xyz_tool" in caplog.text
        assert "not in _TOOL_LAYERS" in caplog.text

    def test_registered_tool_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        reg = ToolRegistry()
        with caplog.at_level(logging.WARNING, logger="myrm_agent_harness.agent.tool_management.registry"):
            reg.register(_make_tool("web_fetch_tool"), source=ToolSource.META)
        assert "not in _TOOL_LAYERS" not in caplog.text

    def test_explicit_layer_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        reg = ToolRegistry()
        with caplog.at_level(logging.WARNING, logger="myrm_agent_harness.agent.tool_management.registry"):
            reg.register(
                _make_tool("brand_new_mcp_tool"),
                source=ToolSource.META,
                layer=ToolLayer.EXTENDED,
            )
        assert "not in _TOOL_LAYERS" not in caplog.text

    def test_provider_tool_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        reg = ToolRegistry()
        with caplog.at_level(logging.WARNING, logger="myrm_agent_harness.agent.tool_management.registry"):
            reg.register(
                _make_tool("mcp_github_tool"),
                source=ToolSource.USER,
                provider="mcp:github",
            )
        assert "not in _TOOL_LAYERS" not in caplog.text
