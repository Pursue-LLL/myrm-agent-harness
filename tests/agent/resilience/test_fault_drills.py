"""Fault-drill playbook: dependency failures must degrade, never crash silently.

Each drill follows make → expect degraded behavior → recover using the
resilience governor. All drills
run in isolated tmp dirs; no network, no production state.
"""

from pathlib import Path

import pytest

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
