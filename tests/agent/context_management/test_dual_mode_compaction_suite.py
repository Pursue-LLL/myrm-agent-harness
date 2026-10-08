"""Unit tests for DualModeCompactionAndOverflowSelfHealingSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    CompactableMessage,
    CompactionTriggerKind,
    ContextWindowBudgetConfig,
    DualModeCompactionAndOverflowSelfHealingSuite,
    ProviderOverflowDetector,
    ProviderOverflowKind,
    SelfHealingAuditReceipt,
)


def test_proactive_watermark_compaction_and_token_reduction() -> None:
    """Test proactive watermark threshold triggering folding of oldest unpinned messages."""
    config = ContextWindowBudgetConfig(
        context_window_tokens=1000,
        proactive_threshold_ratio=0.8,  # 800 tokens watermark
        emergency_trim_ratio=0.5,
    )
    suite = DualModeCompactionAndOverflowSelfHealingSuite(session_id="sess-comp-001", config=config)

    # Construct message list totaling 900 tokens (exceeds 800)
    messages = [
        CompactableMessage(message_id="m1", role="user", content="Step 1 data", estimated_tokens=300),
        CompactableMessage(message_id="m2", role="assistant", content="Step 2 processing", estimated_tokens=300),
        CompactableMessage(message_id="m3", role="user", content="Step 3 inspection", estimated_tokens=300),
    ]

    assert suite.estimate_total_tokens(messages) == 900
    assert suite.should_proactively_compact(messages) is True

    compacted_messages, result = suite.compact_context(
        messages,
        trigger_kind=CompactionTriggerKind.PROACTIVE_WATERMARK,
    )

    assert result.trigger_kind == CompactionTriggerKind.PROACTIVE_WATERMARK
    assert result.original_tokens == 900
    assert result.compacted_tokens < 900
    assert result.tokens_saved > 0
    assert "<compacted_context" in result.compacted_summary
    # Older message folded into summary
    assert any(m.role == "system" and "Folded" in m.content for m in compacted_messages)


def test_pinned_invariants_and_system_prompts_absolute_preservation() -> None:
    """Test that pinned workspace rules and system invariant prompts are never compressed."""
    config = ContextWindowBudgetConfig(context_window_tokens=1000, proactive_threshold_ratio=0.5)
    suite = DualModeCompactionAndOverflowSelfHealingSuite(session_id="sess-pin-002", config=config)

    system_rule = CompactableMessage(
        message_id="sys_rule",
        role="system",
        content="CRITICAL: Never delete production tables",
        estimated_tokens=200,
        is_pinned=True,
        is_system_invariant=True,
    )
    pinned_user = CompactableMessage(
        message_id="pin_user",
        role="user",
        content="Keep this goal in focus: Refactor authentication",
        estimated_tokens=200,
        is_pinned=True,
    )
    unpinned_1 = CompactableMessage(message_id="u1", role="user", content="Log 1", estimated_tokens=200)
    unpinned_2 = CompactableMessage(message_id="u2", role="assistant", content="Log 2", estimated_tokens=200)
    unpinned_3 = CompactableMessage(message_id="u3", role="assistant", content="Log 3", estimated_tokens=200)

    messages = [system_rule, pinned_user, unpinned_1, unpinned_2, unpinned_3]
    compacted_messages, result = suite.compact_context(messages)

    # Verify pinned count preserved
    assert result.preserved_pinned_count == 2
    # Both pinned messages must exist unchanged in compacted list
    retained_ids = [m.message_id for m in compacted_messages]
    assert "sys_rule" in retained_ids
    assert "pin_user" in retained_ids


def test_provider_400_overflow_detection_and_in_place_self_healing() -> None:
    """Test capturing provider 400 ContextWindowExceeded and performing in-place self-healing retry."""
    config = ContextWindowBudgetConfig(
        context_window_tokens=2000,
        proactive_threshold_ratio=0.9,
        emergency_trim_ratio=0.5,
        max_self_healing_retries=2,
    )
    suite = DualModeCompactionAndOverflowSelfHealingSuite(session_id="sess-heal-003", config=config)

    messages = [
        CompactableMessage(message_id="m1", role="user", content="Analyze payload A", estimated_tokens=400),
        CompactableMessage(message_id="m2", role="assistant", content="Analysis chunk 1", estimated_tokens=400),
        CompactableMessage(message_id="m3", role="assistant", content="Analysis chunk 2", estimated_tokens=400),
        CompactableMessage(message_id="m4", role="user", content="Final question", estimated_tokens=200),
    ]

    attempt_counter = [0]

    def mock_llm_provider(curr_messages: list[CompactableMessage]) -> str:
        attempt_counter[0] += 1
        # First attempt fails with 400 Context Window Exceeded error
        if attempt_counter[0] == 1:
            raise RuntimeError(
                "400 Bad Request: maximum context length is 1000 tokens. However, your messages resulted in 1400 tokens."
            )
        # Second attempt succeeds after self-healing compaction
        return f"Model successfully replied to {len(curr_messages)} items."

    response, final_messages = suite.execute_with_overflow_self_healing(messages, mock_llm_provider)

    assert attempt_counter[0] == 2
    assert "Model successfully replied" in response
    assert len(final_messages) < len(messages)

    receipts = suite.get_audit_receipts()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.session_id == "sess-heal-003"
    assert receipt.detected_overflow_kind == ProviderOverflowKind.CONTEXT_WINDOW_EXCEEDED
    assert receipt.recovered_successfully is True
    assert len(receipt.audit_hash) == 16


def test_non_overflow_error_propagation_and_retry_exhaustion() -> None:
    """Test non-overflow error immediate propagation and retry exhaustion safety."""
    suite = DualModeCompactionAndOverflowSelfHealingSuite(
        session_id="sess-err-004",
        config=ContextWindowBudgetConfig(max_self_healing_retries=1),
    )

    messages = [
        CompactableMessage(message_id="m1", role="user", content="Ping", estimated_tokens=100),
        CompactableMessage(message_id="m2", role="assistant", content="Pong", estimated_tokens=100),
        CompactableMessage(message_id="m3", role="assistant", content="Pong", estimated_tokens=100),
    ]

    # Case 1: Non-overflow error (e.g., 401 Unauthorized)
    def failing_auth_call(_: list[CompactableMessage]) -> str:
        raise PermissionError("401 Unauthorized: Invalid API key")

    with pytest.raises(PermissionError, match="401 Unauthorized"):
        suite.execute_with_overflow_self_healing(messages, failing_auth_call)

    # Case 2: Permanent overflow exhausting retries
    def always_overflowing_call(_: list[CompactableMessage]) -> str:
        raise ValueError("context_length_exceeded: prompt exceeds maximum allowable window")

    with pytest.raises(ValueError, match="context_length_exceeded"):
        suite.execute_with_overflow_self_healing(messages, always_overflowing_call)

    receipts = suite.get_audit_receipts()
    failed_receipts = [r for r in receipts if not r.recovered_successfully]
    assert len(failed_receipts) == 1
