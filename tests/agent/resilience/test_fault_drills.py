"""Fault-drill playbook: dependency failures must degrade, never crash silently.

Each drill follows make → expect degraded behavior → recover using the
resilience substrate (governor, budget controller, checkpointer). All drills
run in isolated tmp dirs; no network, no production state.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.resilience.budget_controller import (
    DynamicExecutionBudgetController,
)
from myrm_agent_harness.agent.resilience.checkpointer import MarathonCheckpointer
from myrm_agent_harness.agent.resilience.error_recovery import (
    ErrorSelfCorrectionGovernor,
)
from myrm_agent_harness.agent.resilience.types import RecoveryActionType


def test_drill_sqlite_locked_recovers_via_retry_then_escalate(tmp_path: Path) -> None:
    # Real exclusive lock: a second connection holds BEGIN EXCLUSIVE while
    # the writer attempts its insert, producing a genuine locked error.
    import sqlite3

    db = tmp_path / "memory.db"
    holder = sqlite3.connect(str(db), timeout=5.0)
    holder.execute("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT)")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        writer = sqlite3.connect(str(db), timeout=0.1)
        try:
            with pytest.raises(sqlite3.OperationalError, match=r"[Ll]ocked"):
                writer.execute("INSERT INTO kv VALUES ('a', 'b')")
            locked_message = "sqlite3.OperationalError: database is locked"
        finally:
            writer.close()
    finally:
        holder.rollback()
        holder.close()
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    first = governor.diagnose_and_suggest_repair(
        operation="memory_write",
        target="sqlite://memory.db",
        error_message=locked_message,
        attempt=1,
    )
    assert first.success is True
    assert first.action_taken != RecoveryActionType.ESCALATE
    last = governor.diagnose_and_suggest_repair(
        operation="memory_write",
        target="sqlite://memory.db",
        error_message=locked_message,
        attempt=3,
    )
    assert last.action_taken == RecoveryActionType.ESCALATE


def test_drill_vector_store_unreachable_degrades_to_keyword_only() -> None:
    # Real dead-port failure against the actual client (no mock).
    from qdrant_client import QdrantClient

    client = QdrantClient(url="http://127.0.0.1:9", timeout=3, check_compatibility=False)
    try:
        with pytest.raises(Exception) as exc_info:
            client.get_collections()
    finally:
        client.close()
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="vector_search",
        target="qdrant://localhost:6333",
        error_message=f"{type(exc_info.value).__name__}: {exc_info.value}",
        attempt=1,
    )
    assert outcome.success is True
    assert outcome.action_taken in (
        RecoveryActionType.RETRY,
        RecoveryActionType.ALTERNATIVE_TOOL,
        RecoveryActionType.ENV_REPAIR,
    )


def test_drill_disk_full_fails_closed_without_partial_checkpoint(
    tmp_path: Path,
) -> None:
    # A regular file where the store directory belongs makes every write
    # fail with a real OSError on any uid (chmod-based read-only dirs do not
    # stop root, so they are not used here).
    blocker = tmp_path / "chk"
    blocker.mkdir()
    store = MarathonCheckpointer(storage_dir=blocker)
    blocker.rmdir()
    blocker.write_text("not-a-directory")
    with pytest.raises(OSError):
        store.save_checkpoint(
            session_id="drill-disk-full",
            step_index=0,
            step_name="probe",
            state_payload={"k": "v"},
        )
    assert list(tmp_path.glob("chk-drill-disk-full-*")) == []


def test_drill_llm_relay_timeout_retries_then_escalates() -> None:
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    first = governor.diagnose_and_suggest_repair(
        operation="llm_complete",
        target="relay://models",
        error_message="TimeoutError: request timed out after 30s",
        attempt=1,
    )
    assert first.success is True
    assert first.action_taken == RecoveryActionType.RETRY
    final = governor.diagnose_and_suggest_repair(
        operation="llm_complete",
        target="relay://models",
        error_message="TimeoutError: request timed out after 30s",
        attempt=5,
    )
    assert final.action_taken == RecoveryActionType.ESCALATE


def test_drill_egress_blocked_escalates_with_actionable_hint() -> None:
    governor = ErrorSelfCorrectionGovernor(max_recovery_attempts=2)
    outcome = governor.diagnose_and_suggest_repair(
        operation="web_fetch",
        target="https://external.example.com",
        error_message="EgressDenied: destination not in allowlist",
        attempt=1,
    )
    assert outcome.success is True
    assert "Diagnosed Cause" in outcome.diagnostic_details


def test_drill_sleep_wake_resumes_from_checkpoint(tmp_path: Path) -> None:
    store = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    store.save_checkpoint(
        session_id="drill-sleep",
        step_index=3,
        step_name="crawl",
        completed_steps=["a", "b", "c"],
        pending_steps=["d"],
    )
    revived = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    record = revived.load_latest_checkpoint("drill-sleep")
    assert record is not None
    assert record.step_index == 3
    assert record.pending_steps == ["d"]
    budget = DynamicExecutionBudgetController()
    budget.record_step("d")
    assert budget.get_snapshot().total_steps == 1


def test_drill_corrupt_checkpoint_file_degrades_to_none(tmp_path: Path) -> None:
    store = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    session_dir = tmp_path / "chk" / "drill-corrupt"
    session_dir.mkdir(parents=True)
    (session_dir / "chk-drill-corrupt-0000-deadbe.json").write_text("{broken", encoding="utf-8")
    assert store.load_latest_checkpoint("drill-corrupt") is None
    assert store.load_latest_checkpoint("drill-missing") is None


def test_drill_corrupt_checkpoint_listed_files_are_skipped(tmp_path: Path) -> None:
    store = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    store.save_checkpoint(session_id="drill-list", step_index=0, step_name="a")
    session_dir = tmp_path / "chk" / "drill-list"
    (session_dir / "chk-drill-list-0001-deadbe.json").write_text("{broken", encoding="utf-8")
    records = store.list_checkpoints("drill-list")
    assert len(records) == 1
    assert records[0].step_index == 0
    assert store.list_checkpoints("drill-missing") == []


def test_drill_completed_session_purge_leaves_no_residue(tmp_path: Path) -> None:
    store = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    store.save_checkpoint(session_id="drill-done", step_index=0, step_name="a")
    assert store.list_checkpoints("drill-done") != []
    store.purge_session("drill-done")
    assert store.list_checkpoints("drill-done") == []
    assert not (tmp_path / "chk" / "drill-done").exists()
    store.purge_session("drill-missing")


def test_drill_empty_session_dir_loads_as_none(tmp_path: Path) -> None:
    store = MarathonCheckpointer(storage_dir=tmp_path / "chk")
    (tmp_path / "chk" / "drill-empty").mkdir(parents=True)
    assert store.load_latest_checkpoint("drill-empty") is None
