"""
[INPUT]:
- DurableBudgetLedgerManager, DurableSpendLedgerRecord, SpendCategory, DurableBudgetRecoverySummary

[OUTPUT]:
- Pytest verification for durable budget spend recovery, discarded branch reconciliation, and underestimation gap protection.

[POS]:
tests/observability/test_durable_budget_ledger.py — 持久化每日预算账本单元测试。
"""

import pytest

from myrm_agent_harness.observability.durable_budget_ledger import (
    DurableBudgetLedgerManager,
    DurableBudgetRecoverySummary,
    DurableSpendLedgerRecord,
    SessionActualBilledStatement,
    SpendCategory,
)


def test_durable_spend_recovery_across_restarts() -> None:
    mgr = DurableBudgetLedgerManager()
    mgr.reset()

    # Record 3 expenditures for today
    mgr.record_spend(cost_usd=0.012, category=SpendCategory.CHAT, session_id="sess-1")
    mgr.record_spend(cost_usd=0.005, category=SpendCategory.AUXILIARY, session_id="sess-1")
    mgr.record_spend(cost_usd=0.003, category=SpendCategory.CACHE_WARM)

    # Recover today's total spend: must equal 0.020 USD
    today_spent = mgr.get_today_spent()
    assert today_spent == 0.020


def test_discarded_branch_reconciliation_and_actual_billed() -> None:
    mgr = DurableBudgetLedgerManager()
    mgr.reset()

    session_id = "sess-rewind-99"

    # 1. Turn 1 (successful)
    mgr.record_spend(
        cost_usd=0.010,
        category=SpendCategory.CHAT,
        session_id=session_id,
        message_id="msg-1",
        is_active_branch=True,
    )

    # 2. Turn 2 (aborted/regenerated turn, subsequently rewound)
    mgr.record_spend(
        cost_usd=0.015,
        category=SpendCategory.CHAT,
        session_id=session_id,
        message_id="msg-2-rewound",
        is_active_branch=True,
    )

    # User rewinds or edits message -> mark msg-2-rewound as discarded branch
    updated = mgr.mark_branch_discarded(message_id="msg-2-rewound")
    assert updated == 1

    # 3. Turn 2 retry (current active branch)
    mgr.record_spend(
        cost_usd=0.012,
        category=SpendCategory.CHAT,
        session_id=session_id,
        message_id="msg-2-retry",
        is_active_branch=True,
    )

    # Today's spent MUST include all 3 real provider invocations = 0.010 + 0.015 + 0.012 = 0.037
    assert mgr.get_today_spent() == 0.037

    # Check session actual billed statement
    statement = mgr.get_session_actual_billed(session_id=session_id)
    assert statement.actual_billed_cost_usd == 0.037
    assert statement.visible_branch_cost_usd == 0.022  # msg-1 (0.010) + msg-2-retry (0.012)
    assert statement.discarded_diff_cost_usd == 0.015  # msg-2-rewound


def test_recovery_summary_identifies_underestimation_gap() -> None:
    mgr = DurableBudgetLedgerManager()
    mgr.reset()

    # Record chat and auxiliary spend
    mgr.record_spend(cost_usd=0.040, category=SpendCategory.CHAT, message_id="m1", is_active_branch=True)
    mgr.record_spend(cost_usd=0.025, category=SpendCategory.CHAT, message_id="m2", is_active_branch=False)
    mgr.record_spend(cost_usd=0.010, category=SpendCategory.AUXILIARY)

    # Fragile surviving messages sum is only $0.040 (m1) because m2 was deleted upon retry
    summary = mgr.get_recovery_summary(surviving_message_cost_usd=0.040)

    assert summary.total_durable_cost_usd == 0.075
    assert summary.total_surviving_message_cost_usd == 0.040
    assert summary.discarded_branch_cost_usd == 0.025
    assert summary.records_count == 3
    assert summary.budget_underestimation_gap_usd == 0.035
    assert summary.category_breakdown[SpendCategory.CHAT.value] == 0.065
    assert summary.category_breakdown[SpendCategory.AUXILIARY.value] == 0.010

    # Reset
    mgr.reset()
    assert len(mgr.get_all_records()) == 0
