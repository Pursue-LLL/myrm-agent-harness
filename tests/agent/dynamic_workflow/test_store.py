import os
import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore


@pytest.fixture
def temp_db_path(tmp_path):
    db_file = tmp_path / "test_workflow_events.db"
    yield str(db_file)
    if db_file.exists():
        os.remove(db_file)


def test_store_init(temp_db_path):
    WorkflowEventStore(temp_db_path)
    assert Path(temp_db_path).exists()

    conn = sqlite3.connect(temp_db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subagent_events'")
        assert cursor.fetchone() is not None

        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal.lower() == "wal"
    finally:
        conn.close()


def test_store_save_and_get(temp_db_path):
    store = WorkflowEventStore(temp_db_path)

    workflow_id = "wf_123"
    task_id = "task_1"
    agent_type = "generalPurpose"
    task_description = "test task"
    result_data = {"success": True, "result": "hello"}

    store.save_result(workflow_id, task_id, agent_type, task_description, result_data)

    cached = store.get_cached_result(workflow_id, task_id)
    assert cached is not None
    assert cached["success"] is True
    assert cached["result"] == "hello"

    miss = store.get_cached_result("wf_999", task_id)
    assert miss is None


def test_store_overwrite(temp_db_path):
    store = WorkflowEventStore(temp_db_path)

    workflow_id = "wf_123"
    task_id = "task_1"

    store.save_result(workflow_id, task_id, "type1", "desc1", {"val": 1})
    store.save_result(workflow_id, task_id, "type1", "desc1", {"val": 2})

    cached = store.get_cached_result(workflow_id, task_id)
    assert cached["val"] == 2


def test_connect_rollback_on_error(temp_db_path):
    """Verify that a failed write triggers rollback and doesn't persist."""
    store = WorkflowEventStore(temp_db_path)

    store.save_result("wf_err", "t1", "type", "desc", {"ok": True})

    with pytest.raises(sqlite3.OperationalError), store._connect() as conn:
        conn.execute("INSERT INTO nonexistent_table VALUES (1)")

    cached = store.get_cached_result("wf_err", "t1")
    assert cached == {"ok": True}
