"""Tests for pre-compaction three-state decision control (Cancel/Replace/Passthrough)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.schemas import (
    CANCEL_COMPACTION_METADATA_KEY,
    PRE_COMPACT_DECISION_METADATA_KEY,
    PRE_COMPACT_INJECTION_METADATA_KEY,
    PRE_COMPACT_MESSAGE_METADATA_KEY,
    PRE_COMPACT_REPLACEMENT_SUMMARY_METADATA_KEY,
    ContextConfig,
    PreCompactAction,
    PreCompactDecision,
    PreCompactInjection,
    StructuredSummary,
    normalize_pre_compact_decision,
)
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor import (
    CompressProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.pre_compact_processor import (
    PreCompactProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
    SummarizeProcessor,
)


def test_normalize_pre_compact_decision() -> None:
    # 1. None -> Passthrough
    dec_none = normalize_pre_compact_decision(None)
    assert dec_none.action == PreCompactAction.PASSTHROUGH
    assert dec_none.injection is None

    # 2. PreCompactDecision preserved
    custom_dec = PreCompactDecision(action=PreCompactAction.CANCEL, reason="atomic_step")
    assert normalize_pre_compact_decision(custom_dec) is custom_dec

    # 3. Legacy PreCompactInjection promoted to Passthrough with injection attached
    legacy_inj = PreCompactInjection(
        message=HumanMessage(content="recalled memory"),
        recalled_ids=["id1"],
        query="test query",
        token_estimate=10,
        compaction_tier="compress",
    )
    promoted = normalize_pre_compact_decision(legacy_inj)
    assert promoted.action == PreCompactAction.PASSTHROUGH
    assert promoted.injection is legacy_inj
    assert promoted.reason == "legacy_pre_compact_injection"


@pytest.mark.asyncio
async def test_pre_compact_cancel_action_short_circuits_pipeline() -> None:
    compress_proc = CompressProcessor(max_context_tokens=100_000)
    summarize_proc = SummarizeProcessor(config=ContextConfig(max_context_tokens=100_000))

    async def cancel_callback(
        messages: list,
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactDecision:
        return PreCompactDecision(action=PreCompactAction.CANCEL, reason="atomic_transaction")

    pre_compact_proc = PreCompactProcessor(
        compress_processor=compress_proc,
        summarize_processor=summarize_proc,
        on_pre_compact=cancel_callback,
    )

    # Under 90% watermark
    context = ProcessorContext(
        messages=[HumanMessage(content="short query")] * 10,
        user_query="short query",
        chat_id="chat-1",
        metadata={"pre_compact_tier": "compress"},
    )

    processed = await pre_compact_proc.process(context)
    assert processed.metadata[CANCEL_COMPACTION_METADATA_KEY] is True
    assert processed.metadata["compaction_debt_pending"] is True
    assert processed.metadata[PRE_COMPACT_DECISION_METADATA_KEY].action == PreCompactAction.CANCEL

    # Downstream should_process must short circuit
    assert await compress_proc.should_process(processed) is False
    assert await summarize_proc.should_process(processed) is False


@pytest.mark.asyncio
async def test_pre_compact_cancel_vetoed_at_high_watermark_fence() -> None:
    compress_proc = CompressProcessor(max_context_tokens=1000)
    summarize_proc = SummarizeProcessor(config=ContextConfig(max_context_tokens=1000))

    async def cancel_callback(
        messages: list,
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactDecision:
        return PreCompactDecision(action=PreCompactAction.CANCEL, reason="unauthorized_delay")

    pre_compact_proc = PreCompactProcessor(
        compress_processor=compress_proc,
        summarize_processor=summarize_proc,
        on_pre_compact=cancel_callback,
    )

    # Create a message payload exceeding 90% of max_context_tokens (>= 900 tokens)
    huge_content = "word " * 1500
    context = ProcessorContext(
        messages=[HumanMessage(content=huge_content)],
        user_query="overflow query",
        chat_id="chat-2",
        metadata={"pre_compact_tier": "compress"},
    )

    processed = await pre_compact_proc.process(context)
    # CANCEL must be vetoed: cancel_compaction should NOT be set
    assert processed.metadata.get(CANCEL_COMPACTION_METADATA_KEY) is not True


@pytest.mark.asyncio
async def test_pre_compact_replace_action_bypasses_llm_and_applies_summary() -> None:
    compress_proc = CompressProcessor(max_context_tokens=100_000)
    summarize_proc = SummarizeProcessor(config=ContextConfig(max_context_tokens=100_000))

    fake_summary = StructuredSummary(
        user_goal="Refactor authentication system",
        completed_actions=["Implemented token verification", "Added unit tests"],
        key_findings=["Redis cache is volatile"],
        files_modified=["app/auth/verifier.py"],
    )

    async def replace_callback(
        messages: list,
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactDecision:
        return PreCompactDecision(
            action=PreCompactAction.REPLACE,
            replacement_summary=fake_summary,
            reason="cheap_external_summary",
        )

    pre_compact_proc = PreCompactProcessor(
        compress_processor=compress_proc,
        summarize_processor=summarize_proc,
        on_pre_compact=replace_callback,
    )

    context = ProcessorContext(
        messages=[
            SystemMessage(content="system prompt"),
            HumanMessage(content="old user message 1"),
            AIMessage(content="old assistant message 1"),
            HumanMessage(content="old user message 2"),
            AIMessage(content="old assistant message 2"),
            HumanMessage(content="recent user message 3"),
        ],
        user_query="recent user message 3",
        chat_id="chat-3",
        metadata={"pre_compact_tier": "summarize"},
    )

    processed = await pre_compact_proc.process(context)
    assert processed.metadata.get(PRE_COMPACT_REPLACEMENT_SUMMARY_METADATA_KEY) is fake_summary
    assert processed.structured_summary is fake_summary

    # CompressProcessor should bypass since full summary replacement is queued
    assert await compress_proc.should_process(processed) is False

    # SummarizeProcessor should_process must return True to apply replacement summary
    assert await summarize_proc.should_process(processed) is True

    # Run summarize_proc.process without any LLM configured; it should succeed and replace messages
    final_context = await summarize_proc.process(processed)
    assert final_context.metadata.get("pre_compact_replacement_applied") is True
    assert final_context.structured_summary is fake_summary
    assert any("SUMMARY_JSON" in m.content for m in final_context.messages if hasattr(m, "content"))


@pytest.mark.asyncio
async def test_pre_compact_passthrough_with_injection() -> None:
    compress_proc = CompressProcessor(max_context_tokens=100_000)
    summarize_proc = SummarizeProcessor(config=ContextConfig(max_context_tokens=100_000))

    injection = PreCompactInjection(
        message=HumanMessage(content="semantic memory recall context"),
        recalled_ids=["doc_1", "doc_2"],
        query="recall search",
        token_estimate=50,
        compaction_tier="summarize",
    )

    async def inject_callback(
        messages: list,
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactDecision:
        return PreCompactDecision(
            action=PreCompactAction.PASSTHROUGH,
            injection=injection,
            reason="semantic_recall",
        )

    pre_compact_proc = PreCompactProcessor(
        compress_processor=compress_proc,
        summarize_processor=summarize_proc,
        on_pre_compact=inject_callback,
    )

    context = ProcessorContext(
        messages=[SystemMessage(content="sys"), HumanMessage(content="hello")],
        user_query="hello",
        chat_id="chat-4",
        metadata={"pre_compact_tier": "summarize"},
    )

    processed = await pre_compact_proc.process(context)
    assert processed.metadata.get(PRE_COMPACT_MESSAGE_METADATA_KEY) is injection.message
    assert processed.metadata.get(PRE_COMPACT_INJECTION_METADATA_KEY) is injection
    assert processed.metadata.get(CANCEL_COMPACTION_METADATA_KEY) is None


@pytest.mark.asyncio
async def test_pre_compact_respects_runtime_llm_max_context_tokens_and_records_operations() -> None:
    # Base config is 128,000, but runtime model window is 2,000 (e.g. small local model)
    compress_proc = CompressProcessor(max_context_tokens=128_000)
    summarize_proc = SummarizeProcessor(config=ContextConfig(max_context_tokens=128_000))

    recorded_pressure: list[float] = []

    async def cancel_callback(
        messages: list,
        chat_id: str | None,
        user_id: str | None,
        compaction_tier: str,
        token_pressure_ratio: float,
        user_goal_hint: str,
    ) -> PreCompactDecision:
        recorded_pressure.append(token_pressure_ratio)
        return PreCompactDecision(action=PreCompactAction.CANCEL, reason="postpone_compaction")

    pre_compact_proc = PreCompactProcessor(
        compress_processor=compress_proc,
        summarize_processor=summarize_proc,
        on_pre_compact=cancel_callback,
    )

    # 1850 tokens with physical ceiling of 2000 => 92.5% pressure
    # Under hardcoded 128,000 this would be 1.4% (and would erroneously pass Cancel).
    # With llm_max_context_tokens dynamically resolved, it must trigger 90% Safety Veto!
    context = ProcessorContext(
        messages=[HumanMessage(content="word " * 1850)],
        user_query="test",
        chat_id="chat-small-model",
        metadata={
            "pre_compact_tier": "compress",
            "llm_max_context_tokens": 2000,
        },
    )

    processed = await pre_compact_proc.process(context)
    assert len(recorded_pressure) == 1
    assert recorded_pressure[0] >= 0.90
    assert processed.metadata.get(CANCEL_COMPACTION_METADATA_KEY) is not True
    assert any("cancel VETOED by 90% safety fence" in op for op in processed.operations)


@pytest.mark.asyncio
async def test_compress_processor_process_entry_bypasses_on_replacement_summary() -> None:
    compress_proc = CompressProcessor(max_context_tokens=1000)
    fake_summary = StructuredSummary(
        user_goal="Task",
        completed_actions=["Done"],
        key_findings=[],
        files_modified=[],
    )

    context = ProcessorContext(
        messages=[HumanMessage(content="word " * 500)],
        user_query="test",
        chat_id="chat-5",
        metadata={
            PRE_COMPACT_REPLACEMENT_SUMMARY_METADATA_KEY: fake_summary,
        },
    )

    # Calling process directly must bypass without pruning messages
    original_len = len(context.messages)
    processed = await compress_proc.process(context)
    assert len(processed.messages) == original_len

