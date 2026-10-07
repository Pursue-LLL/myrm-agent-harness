"""Unit tests for PrefixAnchorPreservingCompactor and prefix cache continuity.

[INPUT]
Conversational turn message sequences with diverse roles and token distributions.

[OUTPUT]
Verification of Turn-1 bearing wall preservation, non-linear intermediate tool folding,
prefix overlap ratios, and thread safety.

[POS]
Quality gate for Item 124 in topic_06 roadmap.
"""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.runtime.context.prefix_anchor_compaction_types import (
    AnchoredMessageDescriptor,
    AnchorLockTier,
    MessageRoleKind,
)
from myrm_agent_harness.runtime.context.prefix_anchor_compactor import (
    PrefixAnchorPreservingCompactor,
)


def test_tier_classification_boundary_assignment() -> None:
    compactor = PrefixAnchorPreservingCompactor(
        turn1_protected_turns=1,
        recent_tail_protected_turns=2,
    )
    messages = (
        AnchoredMessageDescriptor(
            message_id="m_sys",
            turn_index=0,
            role=MessageRoleKind.SYSTEM,
            content="System prompt baseline",
            token_count=100,
        ),
        AnchoredMessageDescriptor(
            message_id="m_t1_user",
            turn_index=1,
            role=MessageRoleKind.USER,
            content="Initial user objective",
            token_count=50,
        ),
        AnchoredMessageDescriptor(
            message_id="m_t2_tool",
            turn_index=2,
            role=MessageRoleKind.TOOL,
            content="Mid-session huge file payload...",
            token_count=1500,
        ),
        AnchoredMessageDescriptor(
            message_id="m_t3_user",
            turn_index=3,
            role=MessageRoleKind.USER,
            content="Tail question penultimate",
            token_count=40,
        ),
        AnchoredMessageDescriptor(
            message_id="m_t4_assistant",
            turn_index=4,
            role=MessageRoleKind.ASSISTANT,
            content="Tail answer latest",
            token_count=60,
        ),
    )

    classified = compactor.classify_message_tiers(messages)
    assert len(classified) == 5

    # System and Turn 1 are immutable anchors
    assert classified[0].tier == AnchorLockTier.TURN1_IMMUTABLE
    assert classified[0].is_turn1_anchor is True
    assert classified[1].tier == AnchorLockTier.TURN1_IMMUTABLE
    assert classified[1].is_turn1_anchor is True

    # Turn 2 is intermediate compactible
    assert classified[2].tier == AnchorLockTier.INTERMEDIATE_COMPACTIBLE
    assert classified[2].is_protected is False

    # Turn 3 and 4 (max_turn=4, threshold=3) are recent tail preserved
    assert classified[3].tier == AnchorLockTier.RECENT_WINDOW_PRESERVED
    assert classified[4].tier == AnchorLockTier.RECENT_WINDOW_PRESERVED


def test_under_budget_no_compaction_pass_through() -> None:
    compactor = PrefixAnchorPreservingCompactor()
    messages = (
        AnchoredMessageDescriptor(
            message_id="m_sys",
            turn_index=0,
            role=MessageRoleKind.SYSTEM,
            content="System",
            token_count=100,
        ),
        AnchoredMessageDescriptor(
            message_id="m_u1",
            turn_index=1,
            role=MessageRoleKind.USER,
            content="Hello",
            token_count=20,
        ),
    )
    result = compactor.compact_context(messages, target_token_budget=500)
    assert result.compacted_tokens == 120
    assert result.tokens_reclaimed == 0
    assert result.prefix_overlap_ratio == 1.0
    assert result.turn1_preserved is True
    assert result.folded_tool_count == 0


def test_non_linear_intermediate_tool_folding() -> None:
    compactor = PrefixAnchorPreservingCompactor(
        turn1_protected_turns=1,
        recent_tail_protected_turns=1,
        max_folded_snippet_chars=60,
    )
    messages = (
        AnchoredMessageDescriptor(
            message_id="m_sys",
            turn_index=0,
            role=MessageRoleKind.SYSTEM,
            content="System core instructions",
            token_count=500,
        ),
        AnchoredMessageDescriptor(
            message_id="m_u1",
            turn_index=1,
            role=MessageRoleKind.USER,
            content="Please analyze the codebase architecture",
            token_count=100,
        ),
        AnchoredMessageDescriptor(
            message_id="m_tool1",
            turn_index=2,
            role=MessageRoleKind.TOOL,
            content="File contents:\nclass Architecture:\n    def execute(self):\n        return 'massive_content'",
            token_count=2000,
        ),
        AnchoredMessageDescriptor(
            message_id="m_tool2",
            turn_index=3,
            role=MessageRoleKind.TOOL,
            content="Database schema:\nCREATE TABLE records (id INT, blob TEXT, created_at TIMESTAMP)",
            token_count=1800,
        ),
        AnchoredMessageDescriptor(
            message_id="m_u_tail",
            turn_index=4,
            role=MessageRoleKind.USER,
            content="Now summarize the conclusions",
            token_count=80,
        ),
    )

    # Original tokens: 500 + 100 + 2000 + 1800 + 80 = 4480
    # Set target budget to 1500 tokens -> Intermediate tools must be folded
    result = compactor.compact_context(messages, target_token_budget=1500)

    assert result.turn1_preserved is True
    assert result.folded_tool_count > 0
    assert result.compacted_tokens < result.original_tokens
    assert result.tokens_reclaimed > 0

    # Prefix overlap ratio: System + Turn 1 (600 tokens) remain completely intact
    # 600 / 4480 approx 0.133 of continuous prefix
    assert result.prefix_overlap_ratio > 0.10

    # Check folded content contains XML digest tag
    folded_tools = [m for m in result.compacted_messages if m.is_folded]
    assert len(folded_tools) >= 1
    assert "<folded_tool_result" in folded_tools[0].content


def test_empty_messages_handling() -> None:
    compactor = PrefixAnchorPreservingCompactor()
    res = compactor.compact_context((), target_token_budget=1000)
    assert res.compacted_tokens == 0
    assert res.prefix_overlap_ratio == 1.0
    assert res.turn1_preserved is True


def test_repeated_compaction_idempotence() -> None:
    compactor = PrefixAnchorPreservingCompactor(
        turn1_protected_turns=1,
        recent_tail_protected_turns=1,
    )
    messages = (
        AnchoredMessageDescriptor(
            message_id="m_sys",
            turn_index=0,
            role=MessageRoleKind.SYSTEM,
            content="System",
            token_count=100,
        ),
        AnchoredMessageDescriptor(
            message_id="m_t1",
            turn_index=1,
            role=MessageRoleKind.USER,
            content="User T1",
            token_count=50,
        ),
        AnchoredMessageDescriptor(
            message_id="m_tool",
            turn_index=2,
            role=MessageRoleKind.TOOL,
            content="A very long output string repeating ...",
            token_count=800,
        ),
        AnchoredMessageDescriptor(
            message_id="m_tail",
            turn_index=3,
            role=MessageRoleKind.USER,
            content="Tail",
            token_count=30,
        ),
    )
    res1 = compactor.compact_context(messages, target_token_budget=400)
    assert res1.folded_tool_count == 1

    # Second compaction over already compacted result
    res2 = compactor.compact_context(res1.compacted_messages, target_token_budget=400)
    assert res2.compacted_tokens == res1.compacted_tokens
    assert res2.tokens_reclaimed == 0


def test_multithreaded_compaction_thread_safety() -> None:
    compactor = PrefixAnchorPreservingCompactor(
        turn1_protected_turns=1,
        recent_tail_protected_turns=1,
    )

    def worker(worker_id: int) -> bool:
        msgs = (
            AnchoredMessageDescriptor(
                message_id=f"sys_{worker_id}",
                turn_index=0,
                role=MessageRoleKind.SYSTEM,
                content="System",
                token_count=100,
            ),
            AnchoredMessageDescriptor(
                message_id=f"u1_{worker_id}",
                turn_index=1,
                role=MessageRoleKind.USER,
                content="Task",
                token_count=50,
            ),
            AnchoredMessageDescriptor(
                message_id=f"tool_{worker_id}",
                turn_index=2,
                role=MessageRoleKind.TOOL,
                content="Huge tool output " * 50,
                token_count=1200,
            ),
            AnchoredMessageDescriptor(
                message_id=f"tail_{worker_id}",
                turn_index=3,
                role=MessageRoleKind.USER,
                content="Done",
                token_count=20,
            ),
        )
        res = compactor.compact_context(msgs, target_token_budget=500)
        return res.turn1_preserved and res.compacted_tokens < res.original_tokens

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(25)]
        results = [f.result() for f in futures]

    assert all(results)
