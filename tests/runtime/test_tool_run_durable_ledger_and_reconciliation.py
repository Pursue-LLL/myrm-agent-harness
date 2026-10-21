"""Unit tests for DurableToolLedger, PreRetryReconciler, and StreamDbReconciler.

Tests benchmarked against Mobie CC 0.3.7, durable-pi, and Hermes Desktop assistant-tail-recovery:
1. Tool run lifecycle: started -> succeeded (artifact stored) / failed -> result reuse.
2. In-flight unknown barrier on crash/disconnect.
3. Pre-retry action reconciliation: completed reuse vs unknown mutation blockage.
4. Stream and DB tail reconciliation: optimistic message retention and lossy reasoning collapse.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from myrm_agent_harness.runtime.tool_ledger import (
    DbMessage,
    DurableToolLedger,
    PreRetryReconciler,
    ReconciliationActionStatus,
    StreamDbReconciler,
    StreamedMessage,
    ToolExecutionStatus,
)


def test_durable_tool_ledger_lifecycle() -> None:
    """Test full lifecycle of durable tool ledger with artifact offloading and bounded preview."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ledger.sqlite"
        ledger = DurableToolLedger(db_path)

        # 1. Record started
        call_id = "call_abc123"
        entry_start = ledger.record_started(
            call_id=call_id,
            tool_name="web_search",
            arguments_json=json.dumps({"query": "Antigravity CLI"}),
            is_external_side_effect=False,
        )
        assert entry_start.status == ToolExecutionStatus.STARTED
        assert entry_start.tool_name == "web_search"

        # 2. Record succeeded with large payload (> 200 chars)
        large_content = "X" * 500
        entry_succ = ledger.record_succeeded(
            call_id=call_id,
            full_result=large_content,
            preview_max_chars=50,
        )
        assert entry_succ.status == ToolExecutionStatus.SUCCEEDED
        assert len(entry_succ.result_preview) <= 53  # 50 + "..."
        assert entry_succ.result_preview.endswith("...")
        assert entry_succ.artifact_id is not None

        # 3. Retrieve full cached result for zero-cost reuse
        reused_result = ledger.get_completed_result(call_id)
        assert reused_result == large_content

        # 4. Record a failed call
        fail_id = "call_fail789"
        ledger.record_started(
            call_id=fail_id,
            tool_name="api_mutation",
            arguments_json="{}",
            is_external_side_effect=True,
        )
        ledger.record_failed(fail_id, "Connection timeout")
        fail_entry = ledger.get_entry(fail_id)
        assert fail_entry is not None
        assert fail_entry.status == ToolExecutionStatus.FAILED
        assert "Connection timeout" in fail_entry.result_preview

        ledger.close()


def test_mark_in_flight_as_unknown() -> None:
    """Test safety barrier converting hanging 'started' runs to 'unknown' upon recovery."""
    ledger = DurableToolLedger(":memory:")

    ledger.record_started("call_1", "t1", "{}")
    ledger.record_started("call_2", "t2", "{}")
    ledger.record_succeeded("call_1", "done")

    # Only call_2 is still 'started'
    affected = ledger.mark_in_flight_as_unknown()
    assert affected == 1

    entry_2 = ledger.get_entry("call_2")
    assert entry_2 is not None
    assert entry_2.status == ToolExecutionStatus.UNKNOWN

    ledger.close()


def test_pre_retry_reconciler_safe_and_reusable() -> None:
    """Test pre-retry auditing when all prior actions are completed or pending."""
    ledger = DurableToolLedger(":memory:")
    reconciler = PreRetryReconciler(ledger)

    ledger.record_started("call_c1", "search", "{}")
    ledger.record_succeeded("call_c1", "search result")

    ledger.record_started("call_c2", "read_file", "{}")
    ledger.record_failed("call_c2", "file not found")

    planned_actions = [
        ("call_c1", "search", "{}", False),
        ("call_c2", "read_file", "{}", False),
        ("call_c3", "execute_code", "{}", False),  # Pending
    ]

    report = reconciler.audit_planned_actions("sess_1", "task_1", planned_actions)
    assert report.safe_to_auto_resume is True
    assert report.completed_reused_count == 1
    assert report.failed_count == 1
    assert report.pending_count == 1
    assert report.unknown_danger_count == 0

    md_card = reconciler.render_markdown_card(report)
    assert "### 🔄 断线重试工具对账审计卡片" in md_card
    assert "🟢 已复用" in md_card
    assert "🟡 待重试" in md_card
    assert "⚪ 待执行" in md_card
    assert "✅ 允许" in md_card

    json_summary = reconciler.render_json_summary(report)
    assert json_summary["safe_to_auto_resume"] is True
    assert len(json_summary["items"]) == 3  # type: ignore[arg-type]

    ledger.close()


def test_pre_retry_reconciler_blocks_unknown_external_mutation() -> None:
    """Test pre-retry auditing blocks auto-resume when an external mutation is unknown."""
    ledger = DurableToolLedger(":memory:")
    reconciler = PreRetryReconciler(ledger)

    ledger.record_started("call_tx", "transfer_fund", "{}", is_external_side_effect=True)
    ledger.mark_in_flight_as_unknown()

    planned_actions = [
        ("call_tx", "transfer_fund", "{}", True),
    ]

    report = reconciler.audit_planned_actions("sess_2", "task_2", planned_actions)
    assert report.safe_to_auto_resume is False
    assert report.unknown_danger_count == 1
    assert (
        report.items[0].reconciliation_status
        == ReconciliationActionStatus.UNKNOWN_REQUIRES_CONFIRMATION
    )

    md_card = reconciler.render_markdown_card(report)
    assert "> [!CAUTION]" in md_card
    assert "检测到存在外部副作用且状态未决的工具调用" in md_card
    assert "❌ 需人工确认" in md_card

    ledger.close()


def test_stream_db_reconciler_drop_lossy_reasoning() -> None:
    """Test dropping truncated stream reasoning bubbles when authoritative DB reasoning exists."""
    # 1. Truncated stream is prefix of complete DB reasoning
    db_reasoning = "Thinking process: 1. analyze codebase; 2. run tests; 3. summarize."
    stream_lossy = "Thinking process: 1. analyze code"

    merged, dropped = StreamDbReconciler.drop_lossy_streamed_reasoning(
        stream_lossy, db_reasoning
    )
    assert dropped is True
    assert merged == db_reasoning

    # 2. Both identical
    merged, dropped = StreamDbReconciler.drop_lossy_streamed_reasoning("thought", "thought")
    assert dropped is True
    assert merged == "thought"

    # 3. Stream empty
    merged, dropped = StreamDbReconciler.drop_lossy_streamed_reasoning("", "db_thought")
    assert dropped is False
    assert merged == "db_thought"


def test_stream_db_reconciler_full_alignment() -> None:
    """Test reconciling streamed messages with persistent DB history."""
    streamed = [
        StreamedMessage(
            id="msg_1",
            role="assistant",
            content="Partial stream...",
            reasoning="Thinking: step 1",
            tool_calls=("call_1",),
        ),
        StreamedMessage(
            id="msg_user_opt",
            role="user",
            content="Send next command",
            is_optimistic=True,
        ),
    ]

    db_msgs = [
        DbMessage(
            id="msg_0",
            role="user",
            content="Initial request",
        ),
        DbMessage(
            id="msg_1",
            role="assistant",
            content="Partial stream... finished successfully.",
            reasoning="Thinking: step 1, step 2, step 3.",
            tool_calls=("call_1", "call_2"),
        ),
    ]

    reconciled = StreamDbReconciler.reconcile(streamed, db_msgs)

    # Reconciled count = 2 from DB + 1 optimistic user message
    assert len(reconciled) == 3

    # msg_0 is DB user message
    assert reconciled[0].id == "msg_0"

    # msg_1 is stitched assistant message
    stitched_assistant = reconciled[1]
    assert stitched_assistant.id == "msg_1"
    assert stitched_assistant.was_stitched is True
    assert stitched_assistant.reasoning_lossy_dropped is True
    assert stitched_assistant.content == "Partial stream... finished successfully."
    assert stitched_assistant.reasoning == "Thinking: step 1, step 2, step 3."
    assert stitched_assistant.tool_calls == ("call_1", "call_2")

    # msg_user_opt is preserved optimistic user message
    optimistic_user = reconciled[2]
    assert optimistic_user.id == "msg_user_opt"
    assert optimistic_user.is_optimistic is True
    assert optimistic_user.content == "Send next command"
