import pytest
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolNode

from myrm_agent_harness.agent._internals.langgraph_guard import apply_langgraph_tool_args_guard
from myrm_agent_harness.agent.security.tool_registry import TOOL_SAFETY_METADATA, SafetyMetadata

apply_langgraph_tool_args_guard()

@tool
def safe_tool_1(x: int) -> str:
    """Safe tool 1."""
    return f"safe_1_{x}"

@tool
def safe_tool_2(x: int) -> str:
    """Safe tool 2."""
    return f"safe_2_{x}"

@tool
def unsafe_tool_success(x: int) -> str:
    """Unsafe tool that succeeds."""
    return f"unsafe_success_{x}"

@tool
def unsafe_tool_fail(x: int) -> str:
    """Unsafe tool that fails."""
    raise ValueError(f"unsafe_fail_{x}")

# Register safety metadata
TOOL_SAFETY_METADATA["safe_tool_1"] = SafetyMetadata(is_concurrent_safe=True)
TOOL_SAFETY_METADATA["safe_tool_2"] = SafetyMetadata(is_concurrent_safe=True)
TOOL_SAFETY_METADATA["unsafe_tool_success"] = SafetyMetadata(is_concurrent_safe=False)
TOOL_SAFETY_METADATA["unsafe_tool_fail"] = SafetyMetadata(is_concurrent_safe=False)

from langgraph.graph import MessagesState, StateGraph


@pytest.mark.asyncio
async def test_langgraph_guard_safe_concurrent():
    node = ToolNode([safe_tool_1, safe_tool_2])
    builder = StateGraph(MessagesState)
    builder.add_node("tools", node)
    builder.set_entry_point("tools")
    graph = builder.compile()

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            ToolCall(name="safe_tool_1", args={"x": 1}, id="tc1"),
            ToolCall(name="safe_tool_2", args={"x": 2}, id="tc2"),
        ]
    )

    result = await graph.ainvoke({"messages": [ai_msg]})
    msgs = result["messages"]
    # 1 input + 2 outputs
    assert len(msgs) == 3
    assert msgs[-2].content == "safe_1_1"
    assert msgs[-1].content == "safe_2_2"
    assert msgs[-2].status != "error"
    assert msgs[-1].status != "error"

@pytest.mark.asyncio
async def test_langgraph_guard_unsafe_short_circuit_async():
    node = ToolNode([safe_tool_1, unsafe_tool_fail, safe_tool_2], handle_tool_errors=True)
    builder = StateGraph(MessagesState)
    builder.add_node("tools", node)
    builder.set_entry_point("tools")
    graph = builder.compile()

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            ToolCall(name="safe_tool_1", args={"x": 1}, id="tc1"),
            ToolCall(name="unsafe_tool_fail", args={"x": 2}, id="tc2"),
            ToolCall(name="safe_tool_2", args={"x": 3}, id="tc3"),
        ]
    )

    result = await graph.ainvoke({"messages": [ai_msg]})
    msgs = result["messages"]

    assert len(msgs) == 4
    # First one succeeds
    assert msgs[-3].content == "safe_1_1"
    assert msgs[-3].status != "error"

    # Second one fails
    assert msgs[-2].status == "error"

    # Third one should be aborted
    assert msgs[-1].status == "error"
    assert "Aborted" in msgs[-1].content
    assert msgs[-1].name == "safe_tool_2"

def test_langgraph_guard_unsafe_short_circuit_sync():
    node = ToolNode([safe_tool_1, unsafe_tool_fail, safe_tool_2], handle_tool_errors=True)
    builder = StateGraph(MessagesState)
    builder.add_node("tools", node)
    builder.set_entry_point("tools")
    graph = builder.compile()

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            ToolCall(name="safe_tool_1", args={"x": 1}, id="tc1"),
            ToolCall(name="unsafe_tool_fail", args={"x": 2}, id="tc2"),
            ToolCall(name="safe_tool_2", args={"x": 3}, id="tc3"),
        ]
    )

    result = graph.invoke({"messages": [ai_msg]})
    msgs = result["messages"]

    assert len(msgs) == 4
    assert msgs[-3].content == "safe_1_1"
    assert msgs[-2].status == "error"
    assert msgs[-1].status == "error"
    assert "Aborted" in msgs[-1].content
    assert msgs[-1].name == "safe_tool_2"
