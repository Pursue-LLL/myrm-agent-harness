"""Tests for durable tri-queue engine (steer / followUp / nextRun) and abort divergence."""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.runtime.context.durable_tri_queue import (
    DurableTriQueueManager,
    QueueCoalesceMode,
    QueueType,
)


def test_durable_acceptance_writes_to_journal(tmp_path: Path) -> None:
    """Verify enqueuing persists to append-only journal before returning."""
    journal_path = tmp_path / "queue_journal.jsonl"
    manager = DurableTriQueueManager(journal_path=journal_path)

    item1 = manager.steer("Focus on pytest first", run_id="run-101")
    item2 = manager.follow_up("Review test coverage", run_id="run-101")
    item3 = manager.next_run("Refactor legacy utils", metadata={"priority": "high"})

    assert item1.entry_id.startswith("qitem-")
    assert item2.entry_id.startswith("qitem-")
    assert item3.entry_id.startswith("qitem-")
    assert manager.pending_counts == {
        QueueType.STEER: 1,
        QueueType.FOLLOW_UP: 1,
        QueueType.NEXT_RUN: 1,
    }

    # Verify journal content
    lines = journal_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3

    records = [json.loads(line) for line in lines]
    assert records[0]["record_type"] == "queue_enqueued"
    assert records[0]["target"]["payload"] == "Focus on pytest first"
    assert records[1]["target"]["queue_type"] == "follow_up"
    assert records[2]["target"]["queue_type"] == "next_run"
    assert records[2]["target"]["metadata"]["priority"] == "high"


def test_cancel_queued_retraction(tmp_path: Path) -> None:
    """Verify durable retraction via cancel_queued removes item and records cancellation."""
    journal_path = tmp_path / "queue_journal.jsonl"
    manager = DurableTriQueueManager(journal_path=journal_path)

    item = manager.steer("Typo in previous note")
    assert manager.pending_counts[QueueType.STEER] == 1

    # Cancel unconsumed item
    cancelled = manager.cancel_queued(item.entry_id)
    assert cancelled is True
    assert manager.pending_counts[QueueType.STEER] == 0

    # Cancelling again returns False
    assert manager.cancel_queued(item.entry_id) is False

    # Check journal has cancellation record
    lines = journal_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    c_rec = json.loads(lines[1])
    assert c_rec["record_type"] == "queue_cancelled"
    assert c_rec["entry_id"] == item.entry_id


def test_checkpoint_drain_order_and_tool_concurrency(tmp_path: Path) -> None:
    """Verify checkpoint drain consumes steer first, and followUp only when tools are idle."""
    manager = DurableTriQueueManager(journal_path=tmp_path / "journal.jsonl")

    manager.steer("Steer instruction 1")
    manager.follow_up("Follow up instruction 1")

    # Step 1: Active tools in flight -> steer consumed, followup NOT consumed
    steer_msgs, followup_msgs = manager.drain_for_checkpoint(has_active_tools=True)
    assert steer_msgs == ["Steer instruction 1"]
    assert followup_msgs == []
    assert manager.pending_counts[QueueType.STEER] == 0
    assert manager.pending_counts[QueueType.FOLLOW_UP] == 1

    # Step 2: Tools completed -> followup is consumed
    steer_msgs2, followup_msgs2 = manager.drain_for_checkpoint(has_active_tools=False)
    assert steer_msgs2 == []
    assert followup_msgs2 == ["Follow up instruction 1"]
    assert manager.pending_counts[QueueType.FOLLOW_UP] == 0


def test_coalesce_mode_merges_multiple_pending_notes(tmp_path: Path) -> None:
    """Verify coalesce mode concatenates multiple pending notes into a single directive."""
    manager = DurableTriQueueManager(journal_path=tmp_path / "journal.jsonl")

    manager.steer("Correction Part A")
    manager.steer("Correction Part B")
    manager.steer("Correction Part C")

    items = manager.consume_steer(mode=QueueCoalesceMode.COALESCE)
    assert len(items) == 1
    assert items[0].payload == "Correction Part A\n\nCorrection Part B\n\nCorrection Part C"
    assert manager.pending_counts[QueueType.STEER] == 0


def test_abort_semantics_divergence(tmp_path: Path) -> None:
    """Verify steer and followUp die on abort while nextRun survives."""
    journal_path = tmp_path / "journal.jsonl"
    manager = DurableTriQueueManager(journal_path=journal_path)

    manager.steer("Mid-run steering A", run_id="run-200")
    manager.steer("Mid-run steering B", run_id="run-200")
    manager.follow_up("Post-run follow-up", run_id="run-200")
    manager.next_run("Seed for tomorrow's run")

    assert manager.pending_counts == {
        QueueType.STEER: 2,
        QueueType.FOLLOW_UP: 1,
        QueueType.NEXT_RUN: 1,
    }

    outcome = manager.abort_run(run_id="run-200")

    # Steer & followUp purged and payloads returned
    assert outcome.aborted_steer_payloads == (
        "Mid-run steering A",
        "Mid-run steering B",
    )
    assert outcome.aborted_followup_payloads == ("Post-run follow-up",)
    assert outcome.survived_next_run_count == 1

    # State verification: steer and followUp are gone, nextRun survived
    assert manager.pending_counts[QueueType.STEER] == 0
    assert manager.pending_counts[QueueType.FOLLOW_UP] == 0
    assert manager.pending_counts[QueueType.NEXT_RUN] == 1

    next_items = manager.consume_next_run()
    assert len(next_items) == 1
    assert next_items[0].payload == "Seed for tomorrow's run"


def test_crash_resurrection_from_journal(tmp_path: Path) -> None:
    """Verify process crash resurrects unconsumed items while respecting cancellations & aborts."""
    journal_path = tmp_path / "crash_test.jsonl"

    # Instance 1: perform operations and simulate crash
    proc1 = DurableTriQueueManager(journal_path=journal_path)
    proc1.steer("Steer message 1")
    proc1.steer("Steer message 2")
    item_followup = proc1.follow_up("Follow up task")
    proc1.next_run("Next run persistent intent")

    # Consume steer1 and cancel followup
    proc1.consume_steer()  # consumes both steer1 & steer2
    proc1.cancel_queued(item_followup.entry_id)

    # Now enqueue fresh items before crash
    proc1.steer("Unconsumed steer surviving crash")
    proc1.follow_up("Unconsumed followup surviving crash")

    # Crash! proc1 is dropped.
    del proc1

    # Instance 2: resurrects from disk journal
    proc2 = DurableTriQueueManager(journal_path=journal_path)
    counts = proc2.pending_counts

    assert counts[QueueType.STEER] == 1
    assert counts[QueueType.FOLLOW_UP] == 1
    assert counts[QueueType.NEXT_RUN] == 1

    steer_res = proc2.consume_steer()
    assert len(steer_res) == 1
    assert steer_res[0].payload == "Unconsumed steer surviving crash"

    follow_res = proc2.consume_followup()
    assert len(follow_res) == 1
    assert follow_res[0].payload == "Unconsumed followup surviving crash"

    next_res = proc2.consume_next_run()
    assert len(next_res) == 1
    assert next_res[0].payload == "Next run persistent intent"
