"""Unit tests for BSDL Core BackgroundJobStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_job_store import (
    BackgroundJobStore,
    reset_background_job_store_for_tests,
)
from myrm_agent_harness.agent.meta_tools.bash._background_job_store_core import (
    BackgroundJobRecord,
    map_store_status_to_shell_task_status,
    reconcile_orphaned_job_ids,
)


@pytest.fixture
def store(tmp_path: Path) -> BackgroundJobStore:
    reset_background_job_store_for_tests()
    return BackgroundJobStore(tmp_path / "bg_jobs.db")


def test_insert_and_get_running(store: BackgroundJobStore) -> None:
    store.insert_running(
        job_id="job-a",
        pid=100,
        session_id="chat-1",
        command="npm test",
        started_at=1.0,
    )
    record = store.get_by_job_id("job-a")
    assert record is not None
    assert record.status == "running"
    assert record.pid == 100


def test_finish_dedupe_claim(store: BackgroundJobStore) -> None:
    store.insert_running(
        job_id="job-f",
        pid=101,
        session_id="chat-1",
        command="echo",
        started_at=1.0,
    )
    store.update_terminal(
        "job-f",
        status="exited",
        exit_code=0,
        error_category=None,
        completed_at=2.0,
    )
    assert store.try_claim_finish("job-f") is True
    assert store.try_claim_finish("job-f") is False


def test_reconcile_orphans_running_without_live_pid(store: BackgroundJobStore) -> None:
    store.insert_running(
        job_id="job-o",
        pid=202,
        session_id="chat-2",
        command="sleep",
        started_at=1.0,
    )
    count = store.reconcile_running_jobs(frozenset())
    assert count == 1
    record = store.get_by_job_id("job-o")
    assert record is not None
    assert record.status == "orphaned"


def test_reconcile_core_helper() -> None:
    record = BackgroundJobRecord(
        job_id="j1",
        pid=1,
        session_id="s",
        command="c",
        status="running",
        started_at=0.0,
        completed_at=None,
        exit_code=None,
        error_category=None,
        finish_processed=False,
        vault_log_ref=None,
    )
    orphaned = reconcile_orphaned_job_ids(
        frozenset({"j1"}),
        frozenset(),
        records_by_job_id={"j1": record},
    )
    assert orphaned == ("j1",)


def test_map_orphaned_status() -> None:
    assert map_store_status_to_shell_task_status("orphaned", None) == "orphaned"
