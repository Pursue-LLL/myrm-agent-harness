"""Tests for pre-compaction protected zone assembly."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.schemas import PRE_COMPACT_MESSAGE_METADATA_KEY
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.strategies.pre_compact_context import (
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
