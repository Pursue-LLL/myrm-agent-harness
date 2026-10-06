"""Tests for attempt-level usage ledger with adjustment records (Pi Harness v2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.usage_ledger_attempt import (
    AttemptUsageItem,
    AttemptUsageLedger,
    EffectiveEntryCost,
    SessionUsageRollup,
    UsageCause,
)


def test_record_attempt_and_basic_query() -> None:
    """Test basic recording of provider attempt usage and querying."""
    ledger = AttemptUsageLedger()

    item = ledger.record_attempt(
        entry_id="entry-101",
        run_id="run-001",
        attempt=1,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=1000,
        completion_tokens=200,
        cost_usd=0.015,
        stop_reason="end_turn",
        details={"latency_ms": "1250"},
    )

    assert isinstance(item, AttemptUsageItem)
    assert item.entry_id == "entry-101"
    assert item.run_id == "run-001"
    assert item.cause == UsageCause.ASSISTANT
    assert item.model == "claude-3-7-sonnet"
    assert item.prompt_tokens == 1000
    assert item.completion_tokens == 200
    assert item.total_tokens == 1200
    assert item.cost_usd == 0.015
    assert item.details["latency_ms"] == "1250"

    # Effective cost query
    eff = ledger.get_effective_cost("entry-101")
    assert eff.attempt_count == 1
    assert eff.total_tokens == 1200
    assert eff.total_cost_usd == 0.015
    assert len(eff.records) == 1
    assert eff.records[0].record_id == item.record_id


def test_failed_attempt_durability_without_entry_materialization() -> None:
    """Test that failed attempts survive and accumulate in session rollup even when no entry materializes."""
    ledger = AttemptUsageLedger()

    # Attempt 1: Failed before entry materialized (e.g. 500 error / overflow), entry_id is None
    item1 = ledger.record_attempt(
        entry_id=None,
        run_id="run-failed-01",
        attempt=1,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=8000,
        completion_tokens=50,
        cost_usd=0.024,
        stop_reason="error",
        details={"status_code": "500"},
    )
    assert item1.entry_id is None

    # Attempt 2: Second failed attempt, entry_id is still None
    item2 = ledger.record_attempt(
        entry_id=None,
        run_id="run-failed-01",
        attempt=2,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=8000,
        completion_tokens=30,
        cost_usd=0.024,
        stop_reason="error",
        details={"status_code": "502"},
    )
    assert item2.entry_id is None

    # Session rollup must capture all failed attempt costs and tokens
    rollup = ledger.get_session_rollup()
    assert isinstance(rollup, SessionUsageRollup)
    assert rollup.total_records == 2
    assert rollup.total_tokens == 16080
    assert pytest.approx(rollup.total_cost_usd, 0.0001) == 0.048
    assert rollup.tokens_by_cause[UsageCause.ASSISTANT.value] == 16080
    assert pytest.approx(rollup.cost_by_model["claude-3-7-sonnet"], 0.0001) == 0.048


def test_entry_bound_read_time_aggregation() -> None:
    """Test read-time aggregation of multi-attempt and multi-cause usage under a single entry."""
    ledger = AttemptUsageLedger()
    entry_id = "entry-bound-999"

    # Attempt 1 under entry: Failed attempt
    ledger.record_attempt(
        entry_id=entry_id,
        run_id="run-1",
        attempt=1,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=1500,
        completion_tokens=20,
        cost_usd=0.005,
        stop_reason="overloaded",
    )

    # Attempt 2 under entry: Succeeded
    ledger.record_attempt(
        entry_id=entry_id,
        run_id="run-1",
        attempt=2,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=1500,
        completion_tokens=300,
        cost_usd=0.012,
        stop_reason="end_turn",
    )

    # Tool spend associated with this entry
    ledger.record_attempt(
        entry_id=entry_id,
        run_id="run-1",
        attempt=1,
        cause=UsageCause.TOOL,
        model="tool-sub-model",
        prompt_tokens=400,
        completion_tokens=100,
        cost_usd=0.003,
    )

    # Effective cost aggregation
    effective = ledger.get_effective_cost(entry_id)
    assert isinstance(effective, EffectiveEntryCost)
    assert effective.entry_id == entry_id
    assert effective.attempt_count == 3
    assert effective.total_tokens == 3820
    assert pytest.approx(effective.total_cost_usd, 0.0001) == 0.020
    assert effective.adjustment_cost_usd == 0.0

    # Non-existent entry returns zero cost
    non_existent = ledger.get_effective_cost("non-existent-entry")
    assert non_existent.attempt_count == 0
    assert non_existent.total_cost_usd == 0.0


def test_reconciliation_signed_adjustments() -> None:
    """Test positive and negative price adjustment records for audit reconciliation."""
    ledger = AttemptUsageLedger()
    entry_id = "entry-billed-001"

    # Initial assistant call
    ledger.record_attempt(
        entry_id=entry_id,
        run_id="run-adj",
        attempt=1,
        cause=UsageCause.ASSISTANT,
        model="gpt-4o",
        prompt_tokens=2000,
        completion_tokens=500,
        cost_usd=0.020,
    )

    # Positive surcharge adjustment (+0.005)
    adj_pos = ledger.record_adjustment(
        entry_id=entry_id,
        cost_usd=0.005,
        prompt_tokens=100,
        completion_tokens=0,
        reason="External rate card variance surcharge",
    )
    assert adj_pos.cause == UsageCause.ADJUSTMENT
    assert adj_pos.cost_usd == 0.005

    # Negative rebate / discount adjustment (-0.008)
    adj_neg = ledger.record_adjustment(
        entry_id=entry_id,
        cost_usd=-0.008,
        prompt_tokens=0,
        completion_tokens=0,
        reason="Tier discount rebate",
    )
    assert adj_neg.cost_usd == -0.008

    # Verify effective cost with adjustments
    effective = ledger.get_effective_cost(entry_id)
    # Expected: 0.020 + 0.005 - 0.008 = 0.017
    assert pytest.approx(effective.total_cost_usd, 0.0001) == 0.017
    assert effective.total_tokens == 2600  # 2500 + 100
    assert pytest.approx(effective.adjustment_cost_usd, 0.0001) == -0.003
    assert effective.attempt_count == 1  # 1 non-adjustment attempt

    # Verify session rollup captures all causes including adjustments
    rollup = ledger.get_session_rollup()
    assert pytest.approx(rollup.total_cost_usd, 0.0001) == 0.017
    assert pytest.approx(rollup.net_adjustment_usd, 0.0001) == -0.003
    assert rollup.total_records == 3


def test_durable_disk_persistence_and_recovery(tmp_path: Path) -> None:
    """Test that ledger records are durably written to JSONL and faithfully restored upon restart."""
    db_file = tmp_path / "usage_ledger.jsonl"

    # 1. Initialize and write records
    ledger1 = AttemptUsageLedger(journal_path=db_file)
    ledger1.record_attempt(
        entry_id="entry-durable-1",
        run_id="run-1",
        attempt=1,
        cause=UsageCause.ASSISTANT,
        model="claude-3-7-sonnet",
        prompt_tokens=500,
        completion_tokens=100,
        cost_usd=0.004,
    )
    ledger1.record_attempt(
        entry_id=None,
        run_id="run-1",
        attempt=2,
        cause=UsageCause.COMPACTION,
        model="claude-3-haiku",
        prompt_tokens=1200,
        completion_tokens=300,
        cost_usd=0.010,
    )
    ledger1.record_adjustment(
        entry_id="entry-durable-1",
        cost_usd=-0.001,
        reason="Promotional discount",
    )

    assert db_file.exists()
    assert ledger1.total_records_count == 3
    assert len(ledger1.get_records()) == 3

    # 2. Simulate process restart by reloading from the same journal_path
    ledger2 = AttemptUsageLedger(journal_path=db_file)
    assert ledger2.total_records_count == 3

    # Check effective cost for entry-durable-1
    effective = ledger2.get_effective_cost("entry-durable-1")
    assert pytest.approx(effective.total_cost_usd, 0.0001) == 0.003  # 0.004 - 0.001
    assert effective.attempt_count == 1  # 1 assistant attempt (adjustment not counted in attempt_count)
    assert len(effective.records) == 2  # 1 assistant + 1 adjustment

    # Check session rollup
    rollup = ledger2.get_session_rollup()
    assert pytest.approx(rollup.total_cost_usd, 0.0001) == 0.013  # 0.004 + 0.010 - 0.001
    assert rollup.tokens_by_cause[UsageCause.COMPACTION.value] == 1500

    # 3. Append another record after recovery
    ledger2.record_attempt(
        entry_id="entry-durable-2",
        run_id="run-2",
        attempt=1,
        cause=UsageCause.BRANCH_SUMMARY,
        model="claude-3-haiku",
        prompt_tokens=600,
        completion_tokens=80,
        cost_usd=0.005,
    )
    assert ledger2.total_records_count == 4

    # 4. Third reload to ensure newly appended record was also flushed to disk
    ledger3 = AttemptUsageLedger(journal_path=db_file)
    assert ledger3.total_records_count == 4
    eff3 = ledger3.get_effective_cost("entry-durable-2")
    assert eff3.records[0].cause == UsageCause.BRANCH_SUMMARY
