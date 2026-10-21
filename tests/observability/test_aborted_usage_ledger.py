"""
[INPUT]:
- CanonicalUsageLedgerManager, CanonicalUsageLedgerRow, AuxiliaryCallKind, LedgerCallStatus, UsageAvailabilityKind

[OUTPUT]:
- Pytest verification for canonical usage ledger preventing pseudo-free zero-token representation on aborted auxiliary calls.

[POS]:
tests/observability/test_aborted_usage_ledger.py — 中止辅助调用记 usage-unknown 单元测试。
"""

import pytest

from myrm_agent_harness.observability.aborted_usage_ledger import (
    AbortedUsageUnknownStats,
    AuxiliaryCallKind,
    CanonicalUsageLedgerManager,
    CanonicalUsageLedgerRow,
    LedgerCallStatus,
    UsageAvailabilityKind,
)


def test_completed_call_records_exact_usage() -> None:
    mgr = CanonicalUsageLedgerManager()
    mgr.reset()

    row = mgr.record_call(
        session_id="sess-001",
        task_id="task-summary",
        call_kind=AuxiliaryCallKind.AUXILIARY_SUMMARY,
        call_status=LedgerCallStatus.COMPLETED,
        prompt_tokens=150,
        completion_tokens=50,
        cost_usd=0.003,
    )

    assert row.usage_availability == UsageAvailabilityKind.EXACT
    assert row.prompt_tokens == 150
    assert row.completion_tokens == 50
    assert row.total_tokens == 200
    assert row.cost_usd == 0.003


def test_aborted_auxiliary_call_strictly_records_usage_unknown_never_zero() -> None:
    mgr = CanonicalUsageLedgerManager()
    mgr.reset()

    # User aborts summarization/audit call mid-flight, provider returns no token payload
    row = mgr.record_call(
        session_id="sess-002",
        task_id="task-audit",
        call_kind=AuxiliaryCallKind.AUXILIARY_AUDIT,
        call_status=LedgerCallStatus.ABORTED,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        cost_usd=None,
        provider_raw_status="stream_cancelled_by_client",
    )

    # First principle: Must NOT fill 0 tokens or 0.0 cost (pseudo-free call illusion)
    assert row.usage_availability == UsageAvailabilityKind.USAGE_UNKNOWN
    assert row.prompt_tokens is None
    assert row.completion_tokens is None
    assert row.total_tokens is None
    assert row.cost_usd is None
    assert row.call_status == LedgerCallStatus.ABORTED
    assert row.provider_raw_status == "stream_cancelled_by_client"


def test_aggregation_isolates_known_consumption_and_flags_unknown_risk() -> None:
    mgr = CanonicalUsageLedgerManager()
    mgr.reset()

    # 1. Normal primary call
    mgr.record_call(
        session_id="sess-agg",
        task_id="task-main",
        call_kind=AuxiliaryCallKind.PRIMARY,
        call_status=LedgerCallStatus.COMPLETED,
        prompt_tokens=500,
        completion_tokens=200,
        cost_usd=0.015,
    )

    # 2. Aborted compaction auxiliary call without usage
    mgr.record_call(
        session_id="sess-agg",
        task_id="task-compaction",
        call_kind=AuxiliaryCallKind.AUXILIARY_COMPACTION,
        call_status=LedgerCallStatus.ABORTED,
        prompt_tokens=None,
    )

    # 3. Aborted call where provider still returned partial prompt tokens
    mgr.record_call(
        session_id="sess-agg",
        task_id="task-router",
        call_kind=AuxiliaryCallKind.AUXILIARY_ROUTER,
        call_status=LedgerCallStatus.ABORTED,
        prompt_tokens=100,
        completion_tokens=0,
        cost_usd=0.001,
    )

    stats = mgr.get_stats(session_id="sess-agg")
    assert stats.total_calls == 3
    assert stats.known_usage_calls == 2
    assert stats.unknown_usage_calls == 1
    assert stats.aborted_calls_count == 2
    assert stats.total_known_prompt_tokens == 600
    assert stats.total_known_completion_tokens == 200
    assert stats.total_known_tokens == 800
    assert stats.total_known_cost_usd == 0.016
    assert stats.unknown_risk_flag is True

    # Filter by USAGE_UNKNOWN
    unknown_rows = mgr.get_rows(
        session_id="sess-agg",
        usage_availability=UsageAvailabilityKind.USAGE_UNKNOWN,
    )
    assert len(unknown_rows) == 1
    assert unknown_rows[0].call_kind == AuxiliaryCallKind.AUXILIARY_COMPACTION

    # Reset
    mgr.reset()
    assert len(mgr.get_rows()) == 0
