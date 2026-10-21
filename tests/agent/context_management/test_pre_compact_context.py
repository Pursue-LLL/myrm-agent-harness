"""Tests for pre-compaction protected zone assembly."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.schemas import PRE_COMPACT_MESSAGE_METADATA_KEY
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.strategies.compactor.pre_compact_context import (
    PRE_COMPACT_RECALL_MARKER,
    apply_pre_compact_after_protected_head,
    prepend_pre_compact_message,
)


def test_prepend_pre_compact_message_inserts_after_protected_head() -> None:
    protected = [SystemMessage(content="system")]
    summary = [HumanMessage(content="summary")]
    recent = [HumanMessage(content="latest user")]
    pre_compact = HumanMessage(content=f"{PRE_COMPACT_RECALL_MARKER}>recall</pre_compact_recall_context>")
    context = ProcessorContext(
        messages=protected + recent,
        user_query="q",
        metadata={PRE_COMPACT_MESSAGE_METADATA_KEY: pre_compact},
    )

    merged = prepend_pre_compact_message(protected, summary, recent, context=context)

    assert merged[0] is protected[0]
    assert merged[1] is pre_compact
    assert merged[2] is summary[0]
    assert merged[3] is recent[0]


def test_prepend_pre_compact_message_skips_duplicate_marker() -> None:
    protected = [SystemMessage(content="system")]
    summary = [HumanMessage(content="summary")]
    recent = [HumanMessage(content="latest user")]
    pre_compact = HumanMessage(content=f"{PRE_COMPACT_RECALL_MARKER}>recall</pre_compact_recall_context>")
    context = ProcessorContext(
        messages=protected + recent,
        user_query="q",
        metadata={PRE_COMPACT_MESSAGE_METADATA_KEY: pre_compact},
    )
    already_injected = [*protected, pre_compact, *summary, *recent]

    merged = prepend_pre_compact_message(protected, summary, recent, context=context)

    assert merged == already_injected


def test_apply_pre_compact_after_protected_head_inserts_after_head() -> None:
    protected = SystemMessage(content="system")
    recent = HumanMessage(content="latest user")
    pre_compact = HumanMessage(content=f"{PRE_COMPACT_RECALL_MARKER}>recall</pre_compact_recall_context>")
    context = ProcessorContext(
        messages=[protected, recent],
        user_query="q",
        metadata={PRE_COMPACT_MESSAGE_METADATA_KEY: pre_compact},
    )

    merged = apply_pre_compact_after_protected_head([protected, recent], context=context)

    assert merged[0] is protected
    assert merged[1] is recent
    assert merged[2] is pre_compact


def test_apply_pre_compact_after_protected_head_deduplicates_non_contiguous_head() -> None:
    """Regression: head skipping a stale summary block makes len(head) slicing overlap."""
    summary_block = HumanMessage(
        content=(
            "[Previous conversation summary]\n<!-- SUMMARY_JSON\n"
            '{"user_goal": "g", "active_task": "t", "completed_actions": [], "key_findings": [],'
            ' "errors_and_fixes": [], "files_modified": [], "last_action": "a"}\n-->'
        )
    )
    messages = [
        SystemMessage(content="system"),
        summary_block,
        HumanMessage(content="user1", id="u1"),
        AIMessage(content="AI1", id="a1"),
        HumanMessage(content="user2", id="u2"),
        AIMessage(content="AI2", id="a2"),
    ]
    pre_compact = HumanMessage(content=f"{PRE_COMPACT_RECALL_MARKER}>recall</pre_compact_recall_context>")
    context = ProcessorContext(
        messages=messages,
        user_query="q",
        metadata={PRE_COMPACT_MESSAGE_METADATA_KEY: pre_compact},
    )

    merged = apply_pre_compact_after_protected_head(messages, context=context)

    assert len({id(m) for m in merged}) == len(merged), "no message may appear twice"
    # Order: head (system + first real user turn) -> pre_compact -> summary block -> remaining tail
    assert [id(m) for m in merged] == [
        id(messages[0]),
        id(messages[2]),
        id(messages[3]),
        id(pre_compact),
        id(summary_block),
        id(messages[4]),
        id(messages[5]),
    ]
    assert any(PRE_COMPACT_RECALL_MARKER in m.content for m in merged)
