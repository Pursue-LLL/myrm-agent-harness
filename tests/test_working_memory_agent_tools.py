"""Unit tests for working_memory_manage_tool and its integration with LocalWorkingMemoryBlock."""

import json
import pytest

from myrm_agent_harness.agent.context_management.working_memory.block import (
    LocalWorkingMemoryBlock,
)
from myrm_agent_harness.agent.context_management.working_memory.types import (
    SubtaskStatus,
)
from myrm_agent_harness.agent.meta_tools.working_memory import (
    create_working_memory_manage_tool,
)


@pytest.fixture(autouse=True)
def reset_working_memory():
    LocalWorkingMemoryBlock.reset()
    yield
    LocalWorkingMemoryBlock.reset()


def test_tool_creation():
    tool = create_working_memory_manage_tool()
    assert tool.name == "working_memory_manage_tool"
    assert "discard failed dead-end approaches" in tool.description


def test_update_subtask():
    LocalWorkingMemoryBlock.initialize(
        goal="Develop authentication feature",
        initial_subtasks=["Setup models", "Build token generator", "Write tests"],
    )
    tool = create_working_memory_manage_tool()

    res_raw = tool.invoke({
        "action": "update_subtask",
        "subtask_id": "step-1",
        "status": "completed",
        "notes": "models migrated and verified",
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"
    assert res["new_status"] == "completed"

    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    assert state.subtasks[0].status == SubtaskStatus.COMPLETED
    assert state.subtasks[0].notes == "models migrated and verified"


def test_update_subtask_auto_create_tolerance():
    LocalWorkingMemoryBlock.initialize(goal="Quick run")
    tool = create_working_memory_manage_tool()

    # Updating a non-existent step should auto-create it gracefully
    res_raw = tool.invoke({
        "action": "update_subtask",
        "subtask_id": "step-99",
        "status": "in_progress",
        "notes": "Spontaneous task",
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"

    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    matching = [st for st in state.subtasks if st.id == "step-99"]
    assert len(matching) == 1
    assert matching[0].status == SubtaskStatus.IN_PROGRESS


def test_discard_action_registers_trap_and_updates_subtask():
    LocalWorkingMemoryBlock.initialize(
        goal="Solve memory leak",
        initial_subtasks=["Check GC heap", "Profile event listeners"],
    )
    tool = create_working_memory_manage_tool()

    res_raw = tool.invoke({
        "action": "discard",
        "subtask_id": "step-1",
        "target": "approach_gc_collect",
        "reason": "gc.collect() did not reclaim cyclic buffer references",
        "avoidance_rule": "Do not rely on gc.collect(); use weakref instead",
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"
    assert res["action"] == "discard"
    assert "Do not rely on gc.collect()" in res["avoidance_rule"]

    # Verify trap registered in LocalWorkingMemoryBlock
    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    assert len(state.traps) == 1
    assert state.traps[0].fingerprint == "approach_gc_collect"
    assert "Do not rely on gc.collect()" in state.traps[0].avoidance_rule
    assert state.subtasks[0].status == SubtaskStatus.FAILED

    # Verify turn tail markdown now reflects this trap
    turn_tail_md = LocalWorkingMemoryBlock.format_turn_tail_markdown()
    assert "<working_board>" in turn_tail_md
    assert "Avoidance Traps" in turn_tail_md
    assert "Do not rely on gc.collect()" in turn_tail_md


def test_summarize_action():
    LocalWorkingMemoryBlock.initialize(goal="Large data sync")
    tool = create_working_memory_manage_tool()

    summary_text = "Batch 1 to 5 uploaded successfully; 1200 rows indexed."
    res_raw = tool.invoke({
        "action": "summarize",
        "summary": summary_text,
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"

    # Verify stored in scratchpad
    assert LocalWorkingMemoryBlock.get_scratchpad("latest_summary") == summary_text


def test_set_scratchpad_action():
    LocalWorkingMemoryBlock.initialize(goal="Scratchpad test")
    tool = create_working_memory_manage_tool()

    res_raw = tool.invoke({
        "action": "set_scratchpad",
        "key": "temp_port",
        "value": "8088",
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"
    assert LocalWorkingMemoryBlock.get_scratchpad("temp_port") == "8088"


def test_defensive_error_handling():
    tool = create_working_memory_manage_tool()

    # Missing subtask_id for update_subtask
    res_err1 = json.loads(tool.invoke({"action": "update_subtask"}))
    assert res_err1["status"] == "error"
    assert "hint" in res_err1

    # Missing summary for summarize
    res_err2 = json.loads(tool.invoke({"action": "summarize"}))
    assert res_err2["status"] == "error"

    # Missing key/value for set_scratchpad
    res_err3 = json.loads(tool.invoke({"action": "set_scratchpad"}))
    assert res_err3["status"] == "error"


def test_get_meta_tools_mounts_working_memory_tool():
    from myrm_agent_harness.agent.meta_tools import get_meta_tools
    from myrm_agent_harness.agent.tool_management import ToolRegistry

    registry1 = ToolRegistry()
    tools = get_meta_tools(skills=[], registry=registry1, enable_shell_tools=False, enable_working_memory_tool=True)
    tool_names = [t.name for t in tools]
    assert "working_memory_manage_tool" in tool_names

    # Disabled case
    registry2 = ToolRegistry()
    tools_disabled = get_meta_tools(skills=[], registry=registry2, enable_shell_tools=False, enable_working_memory_tool=False)
    assert "working_memory_manage_tool" not in [t.name for t in tools_disabled]

