"""Unit tests for In-Sandbox Data Reduction and Session Action Ledger (Item 221).

[INPUT]
- InSandboxDataReductionEngine, SandboxReductionConfig, ActionLedgerEntry, ActionKind, ReductionKind.
- Simulated bulky shell outputs, diff strings, and multi-turn execution actions.

[OUTPUT]
- Deterministic verification of output truncation (80%+ reduction ratio), diff summarization,
- SQLite action recording, post-compaction precise historical querying, and ledger re-anchoring.

[POS]
- Verifies context blowout prevention while ensuring 100% precise recovery of technical details.
"""

from __future__ import annotations

import time
import pytest

from myrm_agent_harness.agent.context_management.sandbox_reduction import (
    ActionKind,
    ActionLedgerEntry,
    InSandboxDataReductionEngine,
    LedgerQueryResult,
    ReducedOutputEnvelope,
    ReductionKind,
    SandboxReductionConfig,
)


def test_in_sandbox_log_reduction_and_error_extraction() -> None:
    """Verifies heavy log distillation, context reduction ratio, and prominent error capture."""
    engine = InSandboxDataReductionEngine()

    # Generate 300 lines of noisy build/log output with occasional errors
    noisy_lines = [f"[DEBUG] Step {i}: Processing memory segment {hex(i * 1024)}" for i in range(300)]
    noisy_lines[42] = "[ERROR] DatabaseConnectionPoolTimeout: Failed to acquire lease"
    noisy_lines[150] = "[EXCEPTION] FileNotFoundError: Path '/tmp/cache_lock' missing"
    raw_output = "\n".join(noisy_lines)

    result = engine.reduce_output(
        raw_output=raw_output,
        kind=ReductionKind.LOG_TRUNCATION,
        max_sample_lines=10,
    )

    assert result.kind == ReductionKind.LOG_TRUNCATION
    assert result.original_bytes > 10000
    assert result.reduction_ratio > 0.8  # >80% reduction
    assert len(result.sample_lines) >= 10
    assert "DatabaseConnectionPoolTimeout" in result.summary_text
    assert "FileNotFoundError" in result.summary_text


def test_in_sandbox_diff_reduction() -> None:
    """Verifies git diff distillation into hunk headers and line change statistics."""
    engine = InSandboxDataReductionEngine()

    raw_diff = """
diff --git a/src/core.py b/src/core.py
index 1234567..89abcdef 100644
--- a/src/core.py
+++ b/src/core.py
@@ -10,6 +10,8 @@ def initialize():
+    configure_logging()
+    setup_tracing()
     run_event_loop()
@@ -40,4 +42,3 @@ def shutdown():
-    flush_all_queues()
     close_pool()
"""
    result = engine.reduce_output(
        raw_output=raw_diff,
        kind=ReductionKind.DIFF_SUMMARY,
    )

    assert result.kind == ReductionKind.DIFF_SUMMARY
    assert "[Diff Reduction]" in result.summary_text
    assert "+2 / -1" in result.summary_text
    assert any("@@" in ln for ln in result.sample_lines)


def test_sqlite_action_ledger_recording_and_post_compaction_query() -> None:
    """Verifies fine-grained action ledger persistence and precise post-compaction querying."""
    engine = InSandboxDataReductionEngine()

    now = time.time()

    # Record atomic actions across different turns
    engine.record_action_entry(
        ActionLedgerEntry(
            action_id="act_001",
            session_id="sess_ledger_1",
            turn_id="turn_1",
            action_kind=ActionKind.FILE_EDIT,
            tool_name="replace_file_content",
            target_path="src/router.py",
            diff_summary="+5 -2",
            exit_code=0,
            timestamp=now - 20,
        )
    )
    engine.record_action_entry(
        ActionLedgerEntry(
            action_id="act_002",
            session_id="sess_ledger_1",
            turn_id="turn_2",
            action_kind=ActionKind.COMMAND_EXECUTION,
            tool_name="run_command",
            command_snippet="pytest tests/test_router.py",
            exit_code=1,
            error_evidence="AssertionError in line 54: expected 200 got 500",
            timestamp=now - 10,
        )
    )
    engine.record_action_entry(
        ActionLedgerEntry(
            action_id="act_003",
            session_id="sess_ledger_1",
            turn_id="turn_3",
            action_kind=ActionKind.FILE_EDIT,
            tool_name="write_to_file",
            target_path="src/config.py",
            diff_summary="New file created",
            exit_code=0,
            timestamp=now,
        )
    )

    # Query 1: Find all actions for session
    all_query = engine.query_action_ledger(session_id="sess_ledger_1")
    assert all_query.total_matched == 3
    assert len(all_query.entries) == 3

    # Query 2: Filter specifically by target path
    router_query = engine.query_action_ledger(session_id="sess_ledger_1", target_path="router.py")
    assert router_query.total_matched == 2  # matches act_001 (src/router.py) and act_002 (test_router.py)

    # Query 3: Filter only errors
    error_query = engine.query_action_ledger(session_id="sess_ledger_1", only_errors=True)
    assert error_query.total_matched == 1
    assert error_query.entries[0].action_id == "act_002"
    assert "AssertionError in line 54" in str(error_query.entries[0].error_evidence)
    assert "[Exit 1]" in error_query.compact_report


def test_compact_ledger_reanchor_generation_and_clear() -> None:
    """Verifies prompt anchor generation for compaction and clean teardown."""
    engine = InSandboxDataReductionEngine()

    engine.record_action_entry(
        ActionLedgerEntry(
            action_id="act_anchor",
            session_id="sess_anchor",
            turn_id="turn_1",
            action_kind=ActionKind.FILE_EDIT,
            tool_name="edit_file",
            target_path="README.md",
            diff_summary="+10 lines",
        )
    )

    anchor_str = engine.generate_compact_ledger_reanchor("sess_anchor")
    assert "<session_action_ledger_anchor>" in anchor_str
    assert "README.md" in anchor_str

    # Clear session
    engine.clear_session("sess_anchor")
    empty_query = engine.query_action_ledger("sess_anchor")
    assert empty_query.total_matched == 0
    assert engine.generate_compact_ledger_reanchor("sess_anchor") == ""

    engine.close()
