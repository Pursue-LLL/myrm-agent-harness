"""Unit tests for WorkflowTemplateStore."""

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.template_store import (
    WorkflowTemplateStore,
    compute_workflow_id,
)

_VALID_SCRIPT = """
import myrm_tools
myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="hello", readonly=True)
"""


def test_compute_workflow_id_is_deterministic() -> None:
    assert compute_workflow_id("chat", "msg") == compute_workflow_id("chat", "msg")
    assert compute_workflow_id("chat", "msg") != compute_workflow_id("chat", "msg2")


def test_save_list_get_delete_template(tmp_path) -> None:
    db_path = tmp_path / "workflow.db"
    store = WorkflowTemplateStore(db_path)
    record = store.save_template(
        template_id="My Demo Flow",
        display_name="My Demo Flow",
        script_code=_VALID_SCRIPT,
        trust_latch=True,
    )
    assert record.template_id == "my-demo-flow"
    assert record.trust_latch is True
    assert store.list_templates()[0].template_id == "my-demo-flow"
    loaded = store.get_template("my-demo-flow")
    assert loaded is not None
    assert loaded.script_code.strip().startswith("import myrm_tools")
    assert store.delete_template("my-demo-flow") is True
    assert store.get_template("my-demo-flow") is None


def test_save_from_orchestration_run(tmp_path) -> None:
    db_path = tmp_path / "workflow.db"
    event_store = WorkflowEventStore(db_path)
    template_store = WorkflowTemplateStore(db_path)
    workflow_id = compute_workflow_id("chat_a", "msg_b")
    event_store.save_orchestration_script(workflow_id, _VALID_SCRIPT)

    record = template_store.save_from_orchestration_run(
        chat_id="chat_a",
        message_id="msg_b",
        template_id="saved-flow",
        display_name="Saved Flow",
        trust_latch=False,
        event_store=event_store,
    )
    assert record.template_id == "saved-flow"
    assert "spawn_subagent" in record.script_code
