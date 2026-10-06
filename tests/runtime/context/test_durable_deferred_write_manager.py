"""Tests for DurableDeferredWriteManager and abort-survive semantics."""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.runtime.context.durable_deferred_write_manager import (
    DurableDeferredWriteManager,
)


def test_durable_acceptance_persists_to_journal(tmp_path: Path) -> None:
    """Verify deferred writes are synchronously written to append-only journal before returning."""
    journal_path = tmp_path / "deferred_journal.jsonl"
    manager = DurableDeferredWriteManager(journal_path=journal_path)

    item1 = manager.defer_model_change("gpt-4.5-preview", run_id="run-101")
    item2 = manager.defer_thinking_level("high", run_id="run-101")
    item3 = manager.defer_active_tools(["file_search", "code_eval"])

    assert item1.write_id.startswith("dw-")
    assert item2.write_id.startswith("dw-")
    assert item3.write_id.startswith("dw-")
    assert manager.pending_count == 3

    # Verify journal content on disk
    lines = journal_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    records = [json.loads(line) for line in lines]
    assert records[0]["record_type"] == "write_deferred"
    assert records[0]["target"]["kind"] == "model_config"
    assert records[0]["target"]["payload"]["model"] == "gpt-4.5-preview"
    assert records[1]["target"]["kind"] == "thinking_level"
    assert records[2]["target"]["kind"] == "active_tools"


def test_apply_pending_writes_at_checkpoint(tmp_path: Path) -> None:
    """Verify deferred writes are atomically applied to state and logged as write_applied."""
    journal_path = tmp_path / "deferred_journal.jsonl"
    manager = DurableDeferredWriteManager(journal_path=journal_path)

    manager.defer_model_change("claude-3-7-sonnet")
    manager.defer_custom_entry("workspace", {"env": "production"})

    state: dict[str, str] = {}
    applied = manager.apply_pending_writes(target_state=state)

    assert len(applied) == 2
    assert manager.pending_count == 0
    assert state["model"] == "claude-3-7-sonnet"
    assert state["custom_env"] == "production"

    # Journal should now have 2 deferred and 2 applied records
    lines = journal_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 4
    applied_records = [json.loads(line) for line in lines[2:]]
    assert applied_records[0]["record_type"] == "write_applied"
    assert applied_records[1]["record_type"] == "write_applied"


def test_deferred_writes_survive_abort() -> None:
    """Verify deferred facts survive abort and are committed during abort reconciliation."""
    manager = DurableDeferredWriteManager()

    # User modifies configuration mid-run
    manager.defer_model_change("gemini-2.5-pro", run_id="run-888")
    manager.defer_thinking_level("medium", run_id="run-888")

    assert manager.pending_count == 2

    state: dict[str, str] = {"model": "gpt-4o", "thinking_level": "low"}

    # Run is aborted! Steering intent dies, but deferred facts survive!
    result = manager.apply_on_abort(target_state=state, run_id="run-888")

    assert result.survived is True
    assert result.applied_count == 2
    assert manager.pending_count == 0

    # The facts are retained and updated even though the run was cancelled
    assert state["model"] == "gemini-2.5-pro"
    assert state["thinking_level"] == "medium"


def test_crash_resurrection_unapplied_writes(tmp_path: Path) -> None:
    """Verify unapplied deferred writes survive process crash and resurrect on startup."""
    journal_path = tmp_path / "crash_deferred.jsonl"

    # Instance 1: write 2 items, apply only 1, stage a 3rd, then crash
    proc1 = DurableDeferredWriteManager(journal_path=journal_path)
    proc1.defer_model_change("model-v1")
    item2 = proc1.defer_thinking_level("high")

    # Only apply item 1
    # Manually simulate applying item 1
    with proc1._lock:
        proc1._pending_writes.remove(item2)  # item2 stays unapplied
        proc1.apply_pending_writes()  # applies model-v1

    # Stage item 3
    proc1.defer_custom_entry("tag", {"version": "2.0"})

    # Crash!
    del proc1

    # Instance 2: resumes from disk journal
    proc2 = DurableDeferredWriteManager(journal_path=journal_path)

    # Item 1 was applied, item 2 and item 3 were unapplied and must resurrect
    assert proc2.pending_count == 2

    state: dict[str, str] = {}
    applied = proc2.apply_pending_writes(target_state=state)
    assert len(applied) == 2
    assert state["thinking_level"] == "high"
    assert state["custom_version"] == "2.0"
