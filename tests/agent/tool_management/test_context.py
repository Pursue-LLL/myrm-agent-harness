"""Unit tests for tool_management — ToolLayer registry."""

from myrm_agent_harness.agent.tool_management import ToolLayer, get_tool_layer, register_tool_layer
from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS


class TestToolLayer:
    """Tests for ToolLayer enum."""

    def test_layer_values(self) -> None:
        assert ToolLayer.CORE == 1
        assert ToolLayer.COMMON == 2
        assert ToolLayer.EXTENDED == 3

    def test_layer_ordering(self) -> None:
        assert ToolLayer.CORE < ToolLayer.COMMON < ToolLayer.EXTENDED


class TestToolLayerRegistry:
    """Tests for tool layer registry."""

    def test_get_registered_tool_layer(self) -> None:
        layer = get_tool_layer("bash_code_execute_tool")
        assert layer == ToolLayer.COMMON

    def test_get_unregistered_tool_layer(self) -> None:
        layer = get_tool_layer("unknown_tool")
        assert layer == ToolLayer.EXTENDED

    def test_register_custom_tool_layer(self) -> None:
        key = "_test_only_custom_tool"
        register_tool_layer(key, ToolLayer.CORE)
        try:
            assert get_tool_layer(key) == ToolLayer.CORE
        finally:
            _TOOL_LAYERS.pop(key, None)
