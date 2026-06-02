"""Tests for ActionSpaceProfiler — ASCS (Action Space Complexity Score)."""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic import BaseModel, Field

from myrm_agent_harness.agent.tool_management.action_space import ActionSpaceProfiler


def _make_tool(name: str = "t", description: str = "", args_schema: type | None = None):
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.args_schema = args_schema
    return tool


class SimpleInput(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, description="Max results")


class NestedInput(BaseModel):
    query: str
    options: dict = Field(default_factory=dict)


class EnumInput(BaseModel):
    mode: str = Field(description="Mode")


class TestCalculateScore:
    def test_empty_tools(self) -> None:
        assert ActionSpaceProfiler.calculate_score([]) == 0

    def test_single_tool_base_cost(self) -> None:
        tool = _make_tool(description="x" * 49)
        score = ActionSpaceProfiler.calculate_score([tool])
        assert score == ActionSpaceProfiler.BASE_TOOL_COST

    def test_description_adds_cost(self) -> None:
        tool = _make_tool(description="x" * 150)
        score = ActionSpaceProfiler.calculate_score([tool])
        assert score == ActionSpaceProfiler.BASE_TOOL_COST + 3

    def test_tool_with_schema(self) -> None:
        tool = _make_tool(args_schema=SimpleInput)
        score = ActionSpaceProfiler.calculate_score([tool])
        assert score > ActionSpaceProfiler.BASE_TOOL_COST

    def test_multiple_tools_accumulate(self) -> None:
        tools = [_make_tool(name=f"t{i}") for i in range(5)]
        score = ActionSpaceProfiler.calculate_score(tools)
        assert score == ActionSpaceProfiler.BASE_TOOL_COST * 5

    def test_dict_schema_input(self) -> None:
        schema = {
            "description": "A" * 100,
            "properties": {"q": {"type": "string"}, "n": {"type": "integer"}},
        }
        score = ActionSpaceProfiler.calculate_score([schema])
        assert score == ActionSpaceProfiler.BASE_TOOL_COST + 2 * ActionSpaceProfiler.PARAM_COST + 2

    def test_nested_schema_adds_nesting_cost(self) -> None:
        schema = {
            "properties": {
                "opts": {
                    "type": "object",
                    "properties": {"inner": {"type": "string"}},
                }
            }
        }
        score = ActionSpaceProfiler.calculate_score([schema])
        expected = (
            ActionSpaceProfiler.BASE_TOOL_COST
            + ActionSpaceProfiler.PARAM_COST
            + ActionSpaceProfiler.NESTING_COST * 1
            + ActionSpaceProfiler.PARAM_COST
        )
        assert score == expected

    def test_enum_adds_cost(self) -> None:
        schema = {
            "properties": {"mode": {"type": "string", "enum": ["a", "b", "c"]}}
        }
        score = ActionSpaceProfiler.calculate_score([schema])
        assert score == ActionSpaceProfiler.BASE_TOOL_COST + ActionSpaceProfiler.PARAM_COST + 3


class TestEstimateExternalLoad:
    def test_mcp_only(self) -> None:
        assert ActionSpaceProfiler.estimate_external_load(3, 0) == 3 * 400

    def test_builtin_only(self) -> None:
        assert ActionSpaceProfiler.estimate_external_load(0, 5) == 5 * 100

    def test_mixed(self) -> None:
        assert ActionSpaceProfiler.estimate_external_load(2, 3) == 2 * 400 + 3 * 100

    def test_zero(self) -> None:
        assert ActionSpaceProfiler.estimate_external_load(0, 0) == 0


class TestSchemaExtraction:
    def test_tool_with_pydantic_schema(self) -> None:
        tool = _make_tool(args_schema=SimpleInput)
        schema = ActionSpaceProfiler._get_tool_schema(tool)
        assert schema is not None
        assert "properties" in schema

    def test_tool_without_schema(self) -> None:
        tool = _make_tool()
        tool.args_schema = None
        tool.get_input_schema = None
        delattr(tool, "get_input_schema")
        schema = ActionSpaceProfiler._get_tool_schema(tool)
        assert schema is None

    def test_tool_with_get_input_schema_fallback(self) -> None:
        tool = _make_tool()
        tool.args_schema = None

        class FakeSchema:
            @staticmethod
            def model_json_schema():
                return {"properties": {"x": {"type": "string"}}}

        tool.get_input_schema = lambda: FakeSchema
        schema = ActionSpaceProfiler._get_tool_schema(tool)
        assert schema is not None
