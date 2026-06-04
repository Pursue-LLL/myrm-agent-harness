import pytest
import os
import sqlite3
from pathlib import Path
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore

@pytest.fixture
def temp_db_path(tmp_path):
    db_file = tmp_path / "test_workflow_events.db"
    yield str(db_file)
    if db_file.exists():
        os.remove(db_file)

def test_store_init(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    assert Path(temp_db_path).exists()
    
    # Verify table exists
    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subagent_events'")
        assert cursor.fetchone() is not None

def test_store_save_and_get(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    
    workflow_id = "wf_123"
    task_id = "task_1"
    agent_type = "generalPurpose"
    task_description = "test task"
    result_data = {"success": True, "result": "hello"}
    
    # Save
    store.save_result(workflow_id, task_id, agent_type, task_description, result_data)
    
    # Get
    cached = store.get_cached_result(workflow_id, task_id)
    assert cached is not None
    assert cached["success"] is True
    assert cached["result"] == "hello"
    
    # Miss
    miss = store.get_cached_result("wf_999", task_id)
    assert miss is None

def test_store_overwrite(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    
    workflow_id = "wf_123"
    task_id = "task_1"
    
    store.save_result(workflow_id, task_id, "type1", "desc1", {"val": 1})
    store.save_result(workflow_id, task_id, "type1", "desc1", {"val": 2}) # Overwrite
    
    cached = store.get_cached_result(workflow_id, task_id)
    assert cached["val"] == 2
