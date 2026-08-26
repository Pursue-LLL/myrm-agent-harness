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


def test_store_identity_hash_cross_fork_readonly_hit(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    original_wf = "wf_run_1"
    forked_wf = "wf_run_2_forked"
    task_id = "task_analysis"

    readonly_params = _default_params(
        agent_type="generalPurpose",
        task_description="Scan repository dependencies",
        readonly=True,
    )
    result_data = {"success": True, "dependencies": ["fastapi", "uvicorn"]}

    store.save_result(
        original_wf,
        task_id,
        readonly_params.agent_type,
        readonly_params.task_description,
        result_data,
        spawn_params=readonly_params,
    )

    # In forked workflow, task_id is same or different, but identity_hash matches
    forked_hit = store.get_cached_result(
        forked_wf,
        "task_analysis_forked",
        expected=readonly_params,
        allow_identity_fallback=True,
    )
    assert forked_hit is not None
    assert forked_hit["success"] is True
    assert forked_hit["dependencies"] == ["fastapi", "uvicorn"]


def test_store_identity_hash_write_operation_no_cross_fork_fallback(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    original_wf = "wf_run_write_1"
    forked_wf = "wf_run_write_2"
    task_id = "task_code_gen"

    write_params = _default_params(
        agent_type="generalPurpose",
        task_description="Generate new controller file",
        readonly=False,  # write operation
    )
    result_data = {"success": True, "files_created": ["controller.py"]}

    store.save_result(
        original_wf,
        task_id,
        write_params.agent_type,
        write_params.task_description,
        result_data,
        spawn_params=write_params,
    )

    # In forked workflow, write operation MUST NOT fallback across runs
    forked_miss = store.get_cached_result(
        forked_wf,
        task_id,
        expected=write_params,
        allow_identity_fallback=True,
    )
    assert forked_miss is None


def test_store_identity_hash_failed_run_not_reused(temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    original_wf = "wf_failed_run"
    forked_wf = "wf_retry_run"
    task_id = "task_fail"

    readonly_params = _default_params(
        task_description="Query unstable API",
        readonly=True,
    )
    failed_result = {"success": False, "error": "Rate limit exceeded"}

    store.save_result(
        original_wf,
        task_id,
        readonly_params.agent_type,
        readonly_params.task_description,
        failed_result,
        spawn_params=readonly_params,
    )

    # Failed result must NOT be reused across forked runs
    forked_miss = store.get_cached_result(
        forked_wf,
        "task_fail_new",
        expected=readonly_params,
        allow_identity_fallback=True,
    )
    assert forked_miss is None


def test_store_append_journal_entry(tmp_path, temp_db_path):
    store = WorkflowEventStore(temp_db_path)
    journal_file = tmp_path / ".myrm" / ".workflow-journal.jsonl"
    params = _default_params(task_description="Review PR", readonly=True)
    result_payload = {"success": True, "verdict": "approved"}

    store.append_journal_entry(
        journal_file,
        workflow_id="wf_audit",
        task_id="task_audit_1",
        agent_type=params.agent_type,
        task_description=params.task_description,
        result=result_payload,
        spawn_params=params,
    )

    assert journal_file.exists()
    content = journal_file.read_text(encoding="utf-8").strip()
    import json
    data = json.loads(content)
    assert data["workflow_id"] == "wf_audit"
    assert data["task_id"] == "task_audit_1"
    assert data["identity_hash"] == params.fingerprint()
    assert data["readonly"] is True
    assert data["success"] is True
    assert data["result"]["verdict"] == "approved"

