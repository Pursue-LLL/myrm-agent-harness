# [POS]: tests/unit/toolkits/memory/test_ephemeral_delta_memory_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.ephemeral_delta
# [OUTPUT]: Unit test suite for EphemeralDeltaMemorySuite (Item 98)

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.memory.ephemeral_delta import (
    DeltaActionKind,
    EphemeralDeltaItem,
    EphemeralDeltaReconciler,
    EphemeralDeltaStore,
    HumanTailDeltaInjector,
)


@pytest.mark.asyncio
async def test_ephemeral_delta_store_recording_and_lww_compaction() -> None:
    """Validate delta recording and Last-Write-Wins (LWW) resolution across turns."""
    store = EphemeralDeltaStore()
    session_id = "sess-test-001"
    store.bind_frozen_snapshot(session_id, "snap-frozen-v1")

    # Turn 1: user prefers pnpm
    d1 = EphemeralDeltaItem(
        delta_id="delta-1",
        target_key="package_manager",
        content="Use pnpm exclusively for all commands.",
        action=DeltaActionKind.OVERRIDE,
        turn_index=1,
    )
    store.record_delta(session_id, d1)

    # Turn 2: user adds testing framework preference
    d2 = EphemeralDeltaItem(
        delta_id="delta-2",
        target_key="test_runner",
        content="Always run tests with pytest.",
        action=DeltaActionKind.ADD_FACT,
        turn_index=2,
    )
    store.record_delta(session_id, d2)

    # Turn 3: user corrects package_manager again (LWW override)
    d3 = EphemeralDeltaItem(
        delta_id="delta-3",
        target_key="package_manager",
        content="Actually use bun instead of pnpm.",
        action=DeltaActionKind.OVERRIDE,
        turn_index=3,
    )
    store.record_delta(session_id, d3)

    raw_history = store.get_all_raw_deltas(session_id)
    assert len(raw_history) == 3

    # Compaction should collapse package_manager to d3
    active = store.get_active_deltas(session_id)
    assert len(active) == 2

    active_keys = {item.target_key: item.content for item in active}
    assert active_keys["package_manager"] == "Actually use bun instead of pnpm."
    assert active_keys["test_runner"] == "Always run tests with pytest."

    # Turn 4: user retracts test_runner preference
    d4 = EphemeralDeltaItem(
        delta_id="delta-4",
        target_key="test_runner",
        content="Retracted",
        action=DeltaActionKind.RETRACT,
        turn_index=4,
    )
    store.record_delta(session_id, d4)

    active_after_retract = store.get_active_deltas(session_id)
    assert len(active_after_retract) == 1
    assert active_after_retract[0].target_key == "package_manager"

    snapshot = store.get_snapshot(session_id)
    assert snapshot.frozen_snapshot_id == "snap-frozen-v1"
    assert not snapshot.is_reconciled


def test_human_tail_delta_injector_preserves_prompt_cache() -> None:
    """Ensure SystemPrompt and history remain 100% untouched to preserve prefix cache."""
    injector = HumanTailDeltaInjector()

    system_prompt = SystemMessage(
        content="You are a frozen baseline agent. Never alter this prefix."
    )
    history_h1 = HumanMessage(content="Hello world")
    history_a1 = AIMessage(content="Hi there!")
    current_human = HumanMessage(content="Please build the package.")

    messages = [system_prompt, history_h1, history_a1, current_human]

    deltas = [
        EphemeralDeltaItem(
            delta_id="d-10",
            target_key="tool_choice",
            content="Use bun build.",
            action=DeltaActionKind.OVERRIDE,
        )
    ]

    injected = injector.inject_deltas(messages, deltas)

    # Invariants
    assert len(injected) == 4
    # Prefix SystemPrompt MUST be strictly identical object or byte-equal content
    assert injected[0].content == system_prompt.content
    assert injected[1].content == history_h1.content
    assert injected[2].content == history_a1.content

    # Final HumanMessage has deltas appended at tail
    tail_content = str(injected[3].content)
    assert "Please build the package." in tail_content
    assert "<ephemeral_session_deltas>" in tail_content
    assert 'key="tool_choice"' in tail_content
    assert "Use bun build." in tail_content
    assert "</ephemeral_session_deltas>" in tail_content


def test_human_tail_delta_injector_budget_and_escaping() -> None:
    """Test XML character escaping and budget boundary enforcement."""
    injector = HumanTailDeltaInjector(max_delta_chars=200)

    # Test escaping of XML characters in delta
    special_delta = EphemeralDeltaItem(
        delta_id="d-spec",
        target_key="x & y",
        content="Use <Component attr='value'> & avoid breaks",
        action=DeltaActionKind.OVERRIDE,
    )
    formatted = injector.format_deltas_block([special_delta])
    assert "x &amp; y" in formatted
    assert "&lt;Component" in formatted
    assert "&amp; avoid breaks" in formatted

    # Test budget truncation
    long_deltas = [
        EphemeralDeltaItem(
            delta_id=f"d-{i}",
            target_key=f"key_{i}",
            content="X" * 80,
            action=DeltaActionKind.OVERRIDE,
        )
        for i in range(5)
    ]
    truncated_block = injector.format_deltas_block(long_deltas)
    assert "Remaining deltas truncated due to budget constraints" in truncated_block


@pytest.mark.asyncio
async def test_ephemeral_delta_reconciler_batch_persistence() -> None:
    """Test asynchronous reconciliation loop flushing to durable persistence."""
    store = EphemeralDeltaStore()
    reconciler = EphemeralDeltaReconciler()
    session_id = "sess-reconcile-99"

    d1 = EphemeralDeltaItem(
        delta_id="d-1",
        target_key="city",
        content="San Francisco",
        action=DeltaActionKind.OVERRIDE,
    )
    d2 = EphemeralDeltaItem(
        delta_id="d-2",
        target_key="city",
        content="Tokyo",
        action=DeltaActionKind.OVERRIDE,
    )
    d3 = EphemeralDeltaItem(
        delta_id="d-3",
        target_key="role",
        content="Software Architect",
        action=DeltaActionKind.ADD_FACT,
    )
    store.record_delta(session_id, d1)
    store.record_delta(session_id, d2)
    store.record_delta(session_id, d3)

    persisted_items: list[EphemeralDeltaItem] = []

    async def mock_persist(items: list[EphemeralDeltaItem]) -> None:
        persisted_items.extend(items)

    report = await reconciler.reconcile_session(
        session_id, store, persist_callback=mock_persist
    )

    assert report.session_id == session_id
    assert report.reconciled_count == 2
    assert report.overridden_count == 1
    assert set(report.persisted_keys) == {"city", "role"}

    assert len(persisted_items) == 2
    tokyo_item = next(it for it in persisted_items if it.target_key == "city")
    assert tokyo_item.content == "Tokyo"

    snapshot = store.get_snapshot(session_id)
    assert snapshot.is_reconciled
