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
        assert ToolLayer.CORE < ToolLayer.COMMON < ToolLayer.EXTENDED

    def test_layer_values(self):
        assert ToolLayer.CORE == 1
        assert ToolLayer.COMMON == 2
        assert ToolLayer.EXTENDED == 3


class TestGetToolLayer:
    def test_core_tools_return_core(self):
        core_tools = [
            "web_fetch_tool",
            "bash_code_execute_tool",
            "file_edit_tool",
            "file_read_tool",
            "file_write_tool",
            "glob_tool",
            "grep_tool",
        ]
        for tool in core_tools:
            assert get_tool_layer(tool) == ToolLayer.CORE, f"{tool} should be CORE"

    def test_common_tools_return_common(self):
        common_tools = [
            "todo_write",
            "web_search_tool",
            "memory_recall_tool",
            "memory_save_tool",
            "memory_manage_tool",
        ]
        for tool in common_tools:
            assert get_tool_layer(tool) == ToolLayer.COMMON, f"{tool} should be COMMON"

    def test_extended_tools_return_extended(self):
        extended_tools = [
            "request_answer_user_tool",
            "skill_select_tool",
            "skill_manage_tool",
            "conversation_search_tool",
        ]
        for tool in extended_tools:
            assert get_tool_layer(tool) == ToolLayer.EXTENDED, f"{tool} should be EXTENDED"

    def test_unknown_tool_defaults_to_extended(self):
        assert get_tool_layer("totally_unknown_tool") == ToolLayer.EXTENDED
        assert get_tool_layer("some_custom_mcp_tool") == ToolLayer.EXTENDED

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
        register_tool_layer("test_custom_tool_xyz", ToolLayer.COMMON)
        assert get_tool_layer("test_custom_tool_xyz") == ToolLayer.COMMON
        del _TOOL_LAYERS["test_custom_tool_xyz"]

    def test_override_existing_tool(self):
        original = get_tool_layer("web_search_tool")
        register_tool_layer("web_search_tool", ToolLayer.CORE)
        assert get_tool_layer("web_search_tool") == ToolLayer.CORE
        register_tool_layer("web_search_tool", original)


class TestCommonLayerSortKey:
    def test_memory_block_before_web_search(self) -> None:
        from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
        from myrm_agent_harness.agent.tool_management.types import ToolSource
        from langchain_core.tools import StructuredTool

        def _tool(name: str) -> StructuredTool:
            return StructuredTool.from_function(lambda: None, name=name, description="d")

        reg = ToolRegistry()
        for name in ("web_search_tool", "memory_recall_tool", "memory_save_tool", "memory_manage_tool"):
            reg.register(_tool(name), source=ToolSource.USER)
        names = [t.name for t in reg.resolve()]
        assert names.index("memory_manage_tool") < names.index("web_search_tool")
        assert names.index("memory_recall_tool") < names.index("web_search_tool")
