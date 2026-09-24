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


def test_add_subtask():
    LocalWorkingMemoryBlock.initialize(goal="Quick run")
    tool = create_working_memory_manage_tool()

    res_raw = tool.invoke({
        "action": "add_subtask",
        "title": "Run database migrations",
        "notes": "Using alembic upgrade head",
    })
    res = json.loads(res_raw)
    assert res["status"] == "success"
    assert res["action"] == "add_subtask"
    assert res["title"] == "Run database migrations"
    new_id = res["subtask_id"]

    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    matching = [st for st in state.subtasks if st.id == new_id]
    assert len(matching) == 1
    assert matching[0].title == "Run database migrations"
    assert matching[0].notes == "Using alembic upgrade head"
    assert matching[0].status == SubtaskStatus.PENDING


def test_update_subtask_not_found_returns_error():
    LocalWorkingMemoryBlock.initialize(goal="Quick run")
    tool = create_working_memory_manage_tool()

    res_raw = tool.invoke({
        "action": "update_subtask",
        "subtask_id": "step-99",
        "status": "in_progress",
        "notes": "Non-existent step",
    })
    res = json.loads(res_raw)
    assert res["status"] == "error"
    assert "Subtask 'step-99' not found." in res["error"]
    assert "add_subtask" in res["hint"]

    # Verify no phantom subtasks created
    state = LocalWorkingMemoryBlock.get_state()
    assert state is not None
    assert len(state.subtasks) == 0


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

    # Missing status for update_subtask
    res_err1_b = json.loads(tool.invoke({"action": "update_subtask", "subtask_id": "step-1"}))
    assert res_err1_b["status"] == "error"
    assert "Missing required 'status'" in res_err1_b["error"]

    # Invalid status handled defensively by underlying func
    res_err1_c = json.loads(tool.func(action="update_subtask", subtask_id="step-1", status="unknown_status"))
    assert res_err1_c["status"] == "error"
    assert "Invalid status" in res_err1_c["error"]

    # Missing summary for summarize
    res_err2 = json.loads(tool.invoke({"action": "summarize"}))
    assert res_err2["status"] == "error"

    # Missing key/value for set_scratchpad
    res_err3_a = json.loads(tool.invoke({"action": "set_scratchpad", "key": "k"}))
    assert res_err3_a["status"] == "error"
    assert "required for 'set_scratchpad'" in res_err3_a["error"]

    res_err3_b = json.loads(tool.invoke({"action": "set_scratchpad", "value": "v"}))
    assert res_err3_b["status"] == "error"


    # Discard without explicit target should gracefully self-heal with fallback
    res_err4 = json.loads(tool.invoke({"action": "discard"}))
    assert res_err4["status"] == "success"
    assert "Avoid failing approach: unknown" in res_err4["avoidance_rule"]



    # Unknown action handled defensively
    res_err5 = json.loads(tool.func(action="unknown_action"))
    assert res_err5["status"] == "error"
    assert "Unsupported action" in res_err5["error"]




def test_exception_defense(monkeypatch):
    tool = create_working_memory_manage_tool()

    # Inject exception in discard
    def mock_record_trap(*args, **kwargs):
        raise RuntimeError("Disk IO failure")

    monkeypatch.setattr(LocalWorkingMemoryBlock, "record_trap", mock_record_trap)
    res_discard = json.loads(tool.invoke({
        "action": "discard",
        "target": "bad_path",
        "avoidance_rule": "Avoid bad path",
    }))
    assert res_discard["status"] == "error"
    assert "Disk IO failure" in res_discard["error"]

    # Inject exception in summarize
    def mock_set_scratchpad(*args, **kwargs):
        raise RuntimeError("Memory overflow")

    monkeypatch.setattr(LocalWorkingMemoryBlock, "set_scratchpad", mock_set_scratchpad)
    res_sum = json.loads(tool.invoke({"action": "summarize", "summary": "brief"}))
    assert res_sum["status"] == "error"
    assert "Memory overflow" in res_sum["error"]

    # Inject exception in set_scratchpad
    res_scratch = json.loads(tool.invoke({"action": "set_scratchpad", "key": "k", "value": "v"}))
    assert res_scratch["status"] == "error"
    assert "Memory overflow" in res_scratch["error"]


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


def test_working_memory_tool_dispatches_snapshot_in_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure working_memory_manage_tool injects snapshot into event payload for task safety."""
    from myrm_agent_harness.agent.meta_tools.working_memory.working_memory_agent_tools import (
        create_working_memory_manage_tool,
    )

    LocalWorkingMemoryBlock.initialize(goal="Snapshot test")
    LocalWorkingMemoryBlock.add_subtask(title="Subtask 1", subtask_id="st-1")

    dispatched_events: list[tuple[str, dict[str, object]]] = []

    def mock_dispatch(event_name: str, payload: dict[str, object]) -> None:
        dispatched_events.append((event_name, payload))

    monkeypatch.setattr(
        "myrm_agent_harness.agent.meta_tools.working_memory.working_memory_agent_tools.dispatch_custom_event",
        mock_dispatch,
    )

    tool = create_working_memory_manage_tool()

    # 1. add_subtask
    tool.invoke({"action": "add_subtask", "title": "First step", "subtask_id": "st-1", "notes": "Initial setup"})
    assert len(dispatched_events) == 1
    evt_name, payload = dispatched_events[-1]
    assert evt_name == "working_memory_update"
    assert payload["action"] == "add_subtask"
    assert payload["subtask_id"] == "st-1"
    assert "snapshot" in payload
    assert isinstance(payload["snapshot"], dict)

    # 2. update_subtask
    tool.invoke({"action": "update_subtask", "subtask_id": "st-1", "status": "in_progress", "notes": "Working on it"})
    assert len(dispatched_events) == 2
    evt_name, payload = dispatched_events[-1]
    assert evt_name == "working_memory_update"
    assert payload["action"] == "update_subtask"
    assert "snapshot" in payload
    assert isinstance(payload["snapshot"], dict)

    # 3. discard
    tool.invoke({"action": "discard", "target": "approach_a", "avoidance_rule": "Do not use A"})
    assert len(dispatched_events) == 3
    evt_name, payload = dispatched_events[-1]
    assert evt_name == "working_memory_update"
    assert "snapshot" in payload
    assert isinstance(payload["snapshot"], dict)

    # 4. summarize
    tool.invoke({"action": "summarize", "summary": "Current progress report"})
    assert len(dispatched_events) == 4
    evt_name, payload = dispatched_events[-1]
    assert evt_name == "working_memory_update"
    assert "snapshot" in payload
    assert isinstance(payload["snapshot"], dict)

    # 5. set_scratchpad
    tool.invoke({"action": "set_scratchpad", "key": "lead_id", "value": "12345"})
    assert len(dispatched_events) == 5
    evt_name, payload = dispatched_events[-1]
    assert evt_name == "working_memory_update"
    assert "snapshot" in payload
    assert isinstance(payload["snapshot"], dict)



