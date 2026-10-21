"""[INPUT] CompositeSessionModelUsageLedger, models, and usage events.
[OUTPUT] Pytest verification of 6-dimensional composite key usage ledger, dual-track reconciliation, and summary queries.
[POS] tests/observability/test_composite_usage_ledger.py
"""

import pytest

from myrm_agent_harness.observability.composite_usage_ledger import (
    CompositeSessionModelUsageLedger,
    CostReconciliationStatus,
    get_default_composite_usage_ledger,
)


def test_composite_key_accumulation_and_task_isolation() -> None:
    ledger = CompositeSessionModelUsageLedger()

    # 1. Record usage under task: main_turn
    r1 = ledger.record_usage(
        session_id="sess_alpha",
        model="claude-3-7-sonnet",
        billing_provider="anthropic",
        billing_base_url="https://api.anthropic.com/v1",
        billing_mode="standard",
        task="main_turn",
        input_tokens=1000,
        output_tokens=300,
        cache_read_tokens=400,
        estimated_cost_usd=0.015,
    )
    assert r1.api_call_count == 1
    assert r1.input_tokens == 1000
    assert r1.output_tokens == 300
    assert r1.cost_status == CostReconciliationStatus.ESTIMATED_ONLY

    # 2. Accumulate another turn under same key
    r1_updated = ledger.record_usage(
        session_id="sess_alpha",
        model="claude-3-7-sonnet",
        billing_provider="anthropic",
        billing_base_url="https://api.anthropic.com/v1",
        billing_mode="standard",
        task="main_turn",
        input_tokens=500,
        output_tokens=200,
        estimated_cost_usd=0.008,
    )
    assert r1_updated.api_call_count == 2
    assert r1_updated.input_tokens == 1500
    assert r1_updated.output_tokens == 500
    assert round(r1_updated.estimated_cost_usd, 3) == 0.023

    # 3. Record distinct task under same session: artifact_compile
    r2 = ledger.record_usage(
        session_id="sess_alpha",
        model="claude-3-7-sonnet",
        billing_provider="anthropic",
        billing_base_url="https://api.anthropic.com/v1",
        billing_mode="standard",
        task="artifact_compile",
        input_tokens=2500,
        output_tokens=1200,
        estimated_cost_usd=0.045,
    )
    assert r2.api_call_count == 1
    assert r2.key.task == "artifact_compile"

    # Both records isolated in same session
    sess_records = ledger.get_records(session_id="sess_alpha")
    assert len(sess_records) == 2


def test_dual_track_reconciliation_tolerances() -> None:
    ledger = CompositeSessionModelUsageLedger()

    # Case 1: Reconciled within 15% tolerance
    ledger.record_usage(
        session_id="sess_beta",
        model="gpt-4o",
        billing_provider="openai",
        billing_base_url="https://api.openai.com/v1",
        billing_mode="standard",
        task="main_turn",
        estimated_cost_usd=0.10,
    )
    # Upstream invoice returns 0.11 (+10% drift)
    rec1 = ledger.reconcile_invoice(
        session_id="sess_beta",
        model="gpt-4o",
        billing_provider="openai",
        billing_base_url="https://api.openai.com/v1",
        billing_mode="standard",
        task="main_turn",
        actual_cost_usd=0.11,
    )
    assert rec1 is not None
    assert rec1.cost_status == CostReconciliationStatus.RECONCILED
    assert rec1.discrepancy_pct == 10.0

    # Case 2: Discrepancy alert (>15% divergence)
    ledger.record_usage(
        session_id="sess_beta",
        model="gpt-4o",
        billing_provider="openai",
        billing_base_url="https://api.openai.com/v1",
        billing_mode="standard",
        task="background_review",
        estimated_cost_usd=0.05,
    )
    # Upstream returns 0.08 (+60% drift)
    rec2 = ledger.reconcile_invoice(
        session_id="sess_beta",
        model="gpt-4o",
        billing_provider="openai",
        billing_base_url="https://api.openai.com/v1",
        billing_mode="standard",
        task="background_review",
        actual_cost_usd=0.08,
    )
    assert rec2 is not None
    assert rec2.cost_status == CostReconciliationStatus.DISCREPANCY_ALERT
    assert rec2.discrepancy_pct == 60.0


def test_ledger_summary_and_dimensional_breakdown() -> None:
    ledger = CompositeSessionModelUsageLedger()
    ledger.reset()

    ledger.record_usage(
        session_id="sess_gamma",
        model="claude-3-5-haiku",
        billing_provider="anthropic",
        billing_base_url="https://api.anthropic.com/v1",
        billing_mode="standard",
        task="main_turn",
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=500,
        estimated_cost_usd=0.005,
        actual_cost_usd=0.005,
    )
    ledger.record_usage(
        session_id="sess_gamma",
        model="claude-3-5-haiku",
        billing_provider="anthropic",
        billing_base_url="https://api.anthropic.com/v1",
        billing_mode="standard",
        task="title_gen",
        input_tokens=300,
        output_tokens=50,
        estimated_cost_usd=0.001,
        actual_cost_usd=0.001,
    )

    summary = ledger.get_summary(session_id="sess_gamma")
    assert summary.total_records == 2
    assert summary.total_calls == 2
    assert summary.total_input_tokens == 1300
    assert summary.total_output_tokens == 250
    assert summary.total_cache_tokens == 500
    assert round(summary.total_actual_usd, 3) == 0.006
    assert summary.reconciled_records_count == 2
    assert "main_turn" in summary.task_spend_distribution
    assert "title_gen" in summary.task_spend_distribution


def test_ledger_reset_and_singleton() -> None:
    l1 = get_default_composite_usage_ledger()
    l2 = get_default_composite_usage_ledger()
    assert l1 is l2

    l1.record_usage(
        session_id="sess_clean",
        model="m1",
        billing_provider="p1",
        billing_base_url="u1",
        billing_mode="standard",
        task="t1",
    )
    assert len(l1.get_records(session_id="sess_clean")) == 1

    l1.reset(session_id="sess_clean")
    assert len(l1.get_records(session_id="sess_clean")) == 0
