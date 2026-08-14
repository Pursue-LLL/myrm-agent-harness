import os
import sqlite3
from pathlib import Path

import pytest

from myrm_agent_harness.agent.dynamic_workflow.spawn_cache import SpawnCacheParams
from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore


def _default_params(**overrides: object) -> SpawnCacheParams:
    base = {
        "agent_type": "generalPurpose",
        "task_description": "test task",
        "readonly": False,
        "verification_mode": "none",
        "verifier_agent_type": None,
        "max_verification_rounds": 2,
    }
    base.update(overrides)
    return SpawnCacheParams(**base)  # type: ignore[arg-type]


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
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orchestration_scripts'")
        assert cursor.fetchone() is not None

        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal.lower() == "wal"

        columns = {row[1] for row in conn.execute("PRAGMA table_info(subagent_events)").fetchall()}
        assert "spawn_params_json" in columns
    finally:
        conn.close()


def test_store_save_and_get(temp_db_path):
    store = WorkflowEventStore(temp_db_path)

    workflow_id = "wf_123"
    task_id = "task_1"
    params = _default_params(task_description="test task")
    result_data = {"success": True, "result": "hello"}

    store.save_result(
        workflow_id,
        task_id,
        params.agent_type,
        params.task_description,
        result_data,
        spawn_params=params,
    )

    cached = store.get_cached_result(workflow_id, task_id, expected=params)
    assert cached is not None
    assert cached["success"] is True
    assert cached["result"] == "hello"

    miss = store.get_cached_result("wf_999", task_id, expected=params)
    assert miss is None


def test_store_cache_miss_on_param_change(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    workflow_id = "wf_params"
    task_id = "task_1"
    original = _default_params(task_description="scan pricing")
    store.save_result(
        workflow_id,
        task_id,
        original.agent_type,
        original.task_description,
        {"success": True, "result": "old"},
        spawn_params=original,
    )

    changed = _default_params(task_description="scan pricing", verification_mode="adversarial")
    assert store.get_cached_result(workflow_id, task_id, expected=changed) is None


def test_store_cache_miss_on_verifier_type_change(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    workflow_id = "wf_verifier"
    task_id = "task_1"
    original = _default_params(task_description="audit")
    store.save_result(
        workflow_id,
        task_id,
        original.agent_type,
        original.task_description,
        {"success": True, "result": "old"},
        spawn_params=original,
    )

    changed = _default_params(task_description="audit", verifier_agent_type="shell")
    assert store.get_cached_result(workflow_id, task_id, expected=changed) is None


def test_store_cache_miss_on_max_verification_rounds_change(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    workflow_id = "wf_rounds"
    task_id = "task_1"
    original = _default_params(task_description="audit")
    store.save_result(
        workflow_id,
        task_id,
        original.agent_type,
        original.task_description,
        {"success": True, "result": "old"},
        spawn_params=original,
    )

    changed = _default_params(task_description="audit", max_verification_rounds=4)
    assert store.get_cached_result(workflow_id, task_id, expected=changed) is None


def test_store_overwrite(temp_db_path):
    store = WorkflowEventStore(temp_db_path)

    workflow_id = "wf_123"
    task_id = "task_1"
    params = _default_params(task_description="desc1")

    store.save_result(workflow_id, task_id, params.agent_type, params.task_description, {"val": 1}, spawn_params=params)
    store.save_result(workflow_id, task_id, params.agent_type, params.task_description, {"val": 2}, spawn_params=params)

    cached = store.get_cached_result(workflow_id, task_id, expected=params)
    assert cached["val"] == 2


def test_connect_rollback_on_error(temp_db_path):
    """Verify that a failed write triggers rollback and doesn't persist."""
    store = WorkflowEventStore(temp_db_path)
    params = _default_params(task_description="desc")

    store.save_result("wf_err", "t1", params.agent_type, params.task_description, {"ok": True}, spawn_params=params)

    with pytest.raises(sqlite3.OperationalError), store._connect() as conn:
        conn.execute("INSERT INTO nonexistent_table VALUES (1)")

    cached = store.get_cached_result("wf_err", "t1", expected=params)
    assert cached == {"ok": True}


def test_store_orchestration_script_roundtrip(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    script = "import myrm_tools\nprint('ok')"

    store.save_orchestration_script("wf_script", script)
    assert store.get_orchestration_script("wf_script") == script
    assert store.get_orchestration_script("wf_missing") is None

    store.save_orchestration_script("wf_script", "print('updated')")
    assert store.get_orchestration_script("wf_script") == "print('updated')"
