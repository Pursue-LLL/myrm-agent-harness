from langchain_core.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.agent._internals._agent_build import _weave_dynamic_schemas
from myrm_agent_harness.agent.tool_management.utils import with_dynamic_hints


class DummyInput(BaseModel):
    query: str = Field(description="Query string")

@tool("dummy_tool", args_schema=DummyInput)
def dummy_tool(query: str) -> str:
    """Base description for dummy tool."""
    return query

@tool("other_tool", args_schema=DummyInput)
def other_tool(query: str) -> str:
    """Other tool."""
    return query

def test_with_dynamic_hints_initial_state():
    """Test that the initial tool has the full hinted description."""
    decorated_tool = with_dynamic_hints(
        dummy_tool,
        {"some_tool": "Prefer some_tool."}
    )

    assert "Base description" in decorated_tool.description
    assert "Prefer some_tool." in decorated_tool.description
    assert hasattr(decorated_tool, "dynamic_schema_modifier")

def test_weave_dynamic_schemas_hint_removed():
    """Test that if the referenced tool is missing, the hint is removed."""
    decorated_tool = with_dynamic_hints(
        dummy_tool,
        {"some_tool": "Prefer some_tool."}
    )

    # We resolve tools but some_tool is NOT in the list
    tools = [decorated_tool, other_tool]
    weaved_tools = _weave_dynamic_schemas(tools)

    assert len(weaved_tools) == 2
    weaved_dummy = weaved_tools[0]

    # The hint should be gone because 'some_tool' isn't available
    assert "Prefer some_tool." not in weaved_dummy.description
    assert "Base description" in weaved_dummy.description

    # The original tool should NOT be mutated globally (copy on weave)
    assert weaved_dummy is not decorated_tool

def test_weave_dynamic_schemas_hint_kept():
    """Test that if the referenced tool is present, the hint is kept."""
    @tool("some_tool", args_schema=DummyInput)
    def some_tool(query: str) -> str:
        """Some tool."""
        return query

    decorated_tool = with_dynamic_hints(
        dummy_tool,
        {"some_tool": "Prefer some_tool."}
    )

    # some_tool IS in the list
    tools = [decorated_tool, some_tool]
    weaved_tools = _weave_dynamic_schemas(tools)

    weaved_dummy = weaved_tools[0]

    # The hint should be kept
    assert "Prefer some_tool." in weaved_dummy.description
    assert "Base description" in weaved_dummy.description
