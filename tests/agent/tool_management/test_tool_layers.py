"""Tests for tool_layers module — tool layer priority registry."""

from myrm_agent_harness.agent.tool_management.tool_layers import (
    _TOOL_LAYERS,
    ToolLayer,
    get_tool_layer,
    is_registered_action_tool,
    register_tool_layer,
)


class TestToolLayer:
    def test_layer_ordering(self):
        assert (
            ToolLayer.CORE < ToolLayer.HIGH_PRIORITY < ToolLayer.EXTENDED < ToolLayer.EXTERNAL
        )

    def test_layer_values(self):
        assert ToolLayer.CORE == 1
        assert ToolLayer.HIGH_PRIORITY == 2
        assert ToolLayer.EXTENDED == 3
        assert ToolLayer.EXTERNAL == 4


class TestGetToolLayer:
    def test_core_tools_return_core(self):
        core_tools = [
            "web_fetch_tool",
            "bash_code_execute_tool",
            "bash_process_tool",
            "file_edit_tool",
            "file_read_tool",
            "file_write_tool",
            "glob_tool",
            "grep_tool",
        ]
        for tool in core_tools:
            assert get_tool_layer(tool) == ToolLayer.CORE, f"{tool} should be CORE"

    def test_high_priority_tools_return_high_priority(self):
        high_priority_tools = [
            "web_search_tool",
            "memory_search_tool",
            "memory_save_tool",
            "memory_manage_tool",
            "skill_select_tool",
        ]
        for tool in high_priority_tools:
            assert get_tool_layer(tool) == ToolLayer.HIGH_PRIORITY, f"{tool} should be HIGH_PRIORITY"

    def test_extended_tools_return_extended(self):
        extended_tools = [
            "todo_write",
            "request_answer_user_tool",
            "skill_manage_tool",
            "browser_navigate_tool",
        ]
        for tool in extended_tools:
            assert (
                get_tool_layer(tool) == ToolLayer.EXTENDED
            ), f"{tool} should be EXTENDED"

    def test_unknown_tool_defaults_to_external(self):
        assert get_tool_layer("totally_unknown_tool") == ToolLayer.EXTERNAL
        assert get_tool_layer("mcp__github__search") == ToolLayer.EXTERNAL

    def test_is_registered_action_tool(self):
        assert is_registered_action_tool("web_search_tool") is True
        assert is_registered_action_tool("browser_click") is False

    def test_knowledge_tool_not_registered(self):
        assert "knowledge_tool" not in _TOOL_LAYERS

    def test_code_search_tool_not_registered(self):
        """Semantic code_search was removed; workspace exploration uses grep/glob."""
        assert "code_search_tool" not in _TOOL_LAYERS

    def test_llm_map_tool_not_registered(self):
        """Batch fan-out uses delegate_task_tool mode=batch, not llm_map."""
        assert "llm_map_tool" not in _TOOL_LAYERS
        assert "delegate_task_tool" in _TOOL_LAYERS


class TestRegisterToolLayer:
    def test_register_new_tool(self):
        register_tool_layer("test_custom_tool_xyz", ToolLayer.HIGH_PRIORITY)
        assert get_tool_layer("test_custom_tool_xyz") == ToolLayer.HIGH_PRIORITY
        del _TOOL_LAYERS["test_custom_tool_xyz"]

    def test_override_existing_tool(self):
        original = get_tool_layer("web_search_tool")
        register_tool_layer("web_search_tool", ToolLayer.CORE)
        assert get_tool_layer("web_search_tool") == ToolLayer.CORE
        register_tool_layer("web_search_tool", original)


class TestCommonLayerSortKey:
    def test_web_search_before_memory_block(self) -> None:
        from langchain_core.tools import StructuredTool

        from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
        from myrm_agent_harness.agent.tool_management.types import ToolSource

        def _tool(name: str) -> StructuredTool:
            return StructuredTool.from_function(
                lambda: None, name=name, description="d"
            )

        reg = ToolRegistry()
        for name in (
            "skill_select_tool",
            "memory_manage_tool",
            "memory_search_tool",
            "memory_save_tool",
            "web_search_tool",
        ):
            reg.register(_tool(name), source=ToolSource.USER)
        names = [t.name for t in reg.resolve()]
        assert names.index("web_search_tool") < names.index("memory_manage_tool")
        assert names.index("web_search_tool") < names.index("memory_search_tool")
        assert names.index("web_search_tool") < names.index("memory_save_tool")
        assert names.index("memory_save_tool") < names.index("skill_select_tool")

