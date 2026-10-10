# ============================================================================
# Unit Tests for TransparentCompactionInspectorAndContextPinningCard (Item 146)
# Verifies zero-pruning preservation guarantee of pinned context items,
# restoration of evicted pins, and compaction inspector card data generation.
# ============================================================================

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.pinning import (
    CompactionInspectorCardData,
    PinnedContextItem,
    PinnedContextRetentionProcessor,
    PinnedItemType,
)
from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext


import pytest


@pytest.mark.asyncio
async def test_processor_should_process_decision() -> None:
    """Verifies should_process triggers on pins or compaction events."""
    proc = PinnedContextRetentionProcessor()

    # Plain context -> False
    ctx_plain = ProcessorContext(messages=[HumanMessage(content="Hello")], user_query="Hello")
    assert not await proc.should_process(ctx_plain)

    # Context with is_pinned message -> True
    msg_pinned = HumanMessage(content="Always use Type Hints", additional_kwargs={"is_pinned": True})
    ctx_with_pin = ProcessorContext(messages=[msg_pinned], user_query="Task")
    assert await proc.should_process(ctx_with_pin)

    # Context with saved tokens -> True
    ctx_compacted = ProcessorContext(messages=[HumanMessage(content="Query")], user_query="Task", tokens_saved=2500)
    assert await proc.should_process(ctx_compacted)


@pytest.mark.asyncio
async def test_zero_pruning_guarantee_and_restoration() -> None:
    """Tests that evicted pinned messages are automatically restored and protected."""
    proc = PinnedContextRetentionProcessor()

    # 3 pinned items:
    # 1 survives in messages
    # 2 were evicted by external aggressive compression
    surviving_pin = HumanMessage(
        content="Rule 1: Never use Any type",
        additional_kwargs={"is_pinned": True, "message_id": "pin-1"},
    )
    evicted_pin_item = PinnedContextItem(
        pin_id="pin-2",
        item_type=PinnedItemType.DECISION,
        content="Decision: Database schema migrated to UUIDv4",
        title="DB Migration Decision",
    )
    evicted_file_pin = PinnedContextItem(
        pin_id="pin-3",
        item_type=PinnedItemType.FILE_PATH,
        content="Keep /src/core/contracts.py in cache",
        title="Core Contracts File Pin",
    )

    ctx = ProcessorContext(
        messages=[
            SystemMessage(content="You are an AI architect."),
            surviving_pin,
            AIMessage(content="I will follow Rule 1."),
        ],
        user_query="Continue refactoring",
        tokens_saved=3200,
        metadata={
            "pinned_items": [evicted_pin_item, evicted_file_pin],
        },
    )

    result_ctx = await proc.process(ctx)

    # All 3 pins must exist in messages
    all_contents = [str(m.content) for m in result_ctx.messages]
    assert "Rule 1: Never use Any type" in all_contents
    assert any("Decision: Database schema migrated to UUIDv4" in c for c in all_contents)
    assert any("Keep /src/core/contracts.py in cache" in c for c in all_contents)

    # Verify surviving pin marked with protected_by_pin
    assert surviving_pin.additional_kwargs.get("protected_by_pin") is True

    # Verify operation logged
    assert any("pinned_context_retention" in op for op in result_ctx.operations)


@pytest.mark.asyncio
async def test_transparent_compaction_inspector_card_generation() -> None:
    """Verifies structured inspection card metadata emitted for UI inspection."""
    proc = PinnedContextRetentionProcessor()

    pin_rule = PinnedContextItem(
        pin_id="p-rule",
        item_type=PinnedItemType.FACT,
        content="Strict Zero-Warning Policy",
        title="Zero-Warning Policy",
    )

    ctx = ProcessorContext(
        messages=[
            SystemMessage(content="System"),
            HumanMessage(content="User query"),
            AIMessage(content="Summary of previous rounds..."),
        ],
        user_query="User query",
        chat_id="chat-alpha-123",
        tokens_saved=4800,
        metadata={
            "pinned_items": [pin_rule],
        },
    )
    # Add dummy structured summary
    @dataclass
    class DummySummary:
        summary: str = "Refactored payment gateway; extracted retry ledger."
        key_decisions: list[str] = field(
            default_factory=lambda: ["Use exponential backoff", "Isolate Stripe webhook secrets"]
        )

    ctx.structured_summary = DummySummary()  # type: ignore[assignment]

    result_ctx = await proc.process(ctx)
    card_dict = result_ctx.metadata.get("compaction_inspector_card")
    assert isinstance(card_dict, dict)

    assert card_dict["chat_id"] == "chat-alpha-123"
    assert card_dict["saved_tokens"] == 4800
    assert card_dict["savings_ratio"] > 0.0
    assert card_dict["preserved_pinned_count"] == 1
    assert card_dict["is_user_editable"] is True
    assert card_dict["structured_summary_text"] == "Refactored payment gateway; extracted retry ledger."
    assert "Use exponential backoff" in card_dict["key_decisions"]
    assert any("Strict Zero-Warning Policy" in p for p in card_dict["pinned_items_preview"])


def test_card_data_serialization_and_defaults() -> None:
    """Verifies CompactionInspectorCardData serialization and PinnedContextItem serialization."""
    card = CompactionInspectorCardData(
        card_id="c1",
        chat_id="chat-1",
        pre_tokens=10000,
        post_tokens=3000,
        saved_tokens=7000,
        savings_ratio=0.7,
        compacted_turns_count=5,
        preserved_pinned_count=2,
        structured_summary_text="Summary text",
        key_decisions=["D1"],
        pinned_items_preview=["P1"],
    )
    cd = card.to_dict()
    assert cd["card_id"] == "c1"
    assert cd["savings_ratio"] == 0.7
    assert cd["saved_tokens"] == 7000

    item = PinnedContextItem(
        pin_id="pi-1",
        item_type=PinnedItemType.MESSAGE,
        content="Important context",
    )
    idict = item.to_dict()
    assert idict["pin_id"] == "pi-1"
    assert idict["item_type"] == "message"


import pytest

from myrm_agent_harness.agent.context_management.pipeline import ContextPipeline, build_default_processors


@pytest.mark.asyncio
async def test_pipeline_e2e_pinned_context_retention_and_compaction_card() -> None:
    """Verifies that ContextPipeline with default processors guarantees zero-pruning of pinned items

    and attaches transparent compaction inspector card to context metadata.
    """
    pipeline = ContextPipeline(build_default_processors(max_context_tokens=2048))

    # Pinned architectural decision
    pinned_msg = HumanMessage(
        content="CRITICAL ARCH CONTRACT: All services must use UUIDv7 IDs.",
        additional_kwargs={"is_pinned": True, "message_id": "pin-arch-contract"},
    )

    ctx = ProcessorContext(
        messages=[
            SystemMessage(content="You are a principal engineer."),
            pinned_msg,
            HumanMessage(content="First exploratory question"),
            AIMessage(content="First response..."),
        ],
        user_query="Please proceed with database setup",
        chat_id="chat-e2e-pinning-1",
        tokens_saved=3500,
    )

    result_ctx = await pipeline.process(ctx)

    # 1. Zero-pruning guarantee: pinned message survives
    all_contents = [str(m.content) for m in result_ctx.messages]
    assert "CRITICAL ARCH CONTRACT: All services must use UUIDv7 IDs." in all_contents

    # 2. Pinned message is flagged as protected
    found_protected = False
    for m in result_ctx.messages:
        if "CRITICAL ARCH CONTRACT" in str(m.content):
            if getattr(m, "additional_kwargs", {}).get("protected_by_pin") is True:
                found_protected = True
    assert found_protected is True

    # 3. Transparent compaction inspector card was generated in metadata
    card = result_ctx.metadata.get("compaction_inspector_card")
    assert card is not None
    assert isinstance(card, dict)
    assert card["chat_id"] == "chat-e2e-pinning-1"
    assert card["saved_tokens"] == 3500
    assert card["preserved_pinned_count"] >= 1
    assert any("CRITICAL ARCH CONTRACT" in preview for preview in card["pinned_items_preview"])

