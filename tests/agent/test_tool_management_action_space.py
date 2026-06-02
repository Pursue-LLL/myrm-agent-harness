"""Tests for ActionSpaceProfiler."""

from langchain_core.tools import tool

from myrm_agent_harness.agent.tool_management.action_space import ActionSpaceProfiler


@tool
def simple_tool(name: str) -> str:
    """A very simple tool."""
    return f"Hello {name}"


@tool
def complex_tool(data: dict[str, str], options: list[str]) -> str:
    """A complex tool with nested dicts and arrays."""
    return "Done"


def test_action_space_profiler_with_langchain_tools() -> None:
    """Test profiler with real LangChain BaseTool instances."""
    tools = [simple_tool, complex_tool]

    score = ActionSpaceProfiler.calculate_score(tools)

    # Base cost: 10 * 2 = 20
    # Description cost: len / 50 -> simple_tool (21//50=0), complex_tool (48//50=0)
    # simple_tool properties: name (5) = 5
    # complex_tool properties: data (5 + nesting 10), options (5 + nesting 10) = 30
    # total expected approx: 20 + 0 + 5 + 30 = 55
    assert score > 20
    assert score < 200

def test_action_space_profiler_with_raw_schemas() -> None:
    """Test profiler with raw OpenAPI schema dictionaries."""
    raw_schemas = [
        {
            "description": "A very simple tool.",
            "properties": {
                "name": {"type": "string", "title": "Name"}
            }
        },
        {
            "description": "A complex tool with nested dicts and arrays.",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "key1": {"type": "string"}
                    }
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            }
        }
    ]

    score = ActionSpaceProfiler.calculate_score(raw_schemas)
    assert score > 20
    assert score < 200

def test_estimate_external_load() -> None:
    """Test estimation for MCP and Built-ins."""
    score = ActionSpaceProfiler.estimate_external_load(mcp_count=2, builtin_count=1)
    assert score == (2 * 400) + (1 * 100)
    assert score == 900
