"""Unit tests for bounded initial page loading and lazy upward cursor hydration engine.

Validates ultra-fast latest page slicing, demand-driven upward pagination,
oversized tool payload detachment, sliding window eviction/rehydration, and fork alignment.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.bounded_hydration_types import (
    LightweightMessageStub,
    MessageHydrationState,
)
from myrm_agent_harness.runtime.context.bounded_initial_page_hydration_engine import (
    BoundedInitialPageHydrationEngine,
)
from myrm_agent_harness.runtime.context.heavy_tool_payload_blob_store import (
    HeavyToolPayloadBlobStore,
)


@pytest.mark.asyncio
async def test_bounded_initial_page_ultra_fast_slice() -> None:
    """Validate instant initial loading of bounded latest page (<100ms) on long session."""
    engine = BoundedInitialPageHydrationEngine(default_page_size=15)
    session_id = "sess_bound_001"

    # Seed 60 messages
    for i in range(60):
        engine.append_raw_message(
            session_id=session_id,
            message_id=f"msg_{i:03d}",
            role="user" if i % 2 == 0 else "assistant",
            content=f"Conversation turn {i} payload text",
            created_at=1000.0 + i,
        )

    # Fast initial load
    page = engine.load_bounded_initial_page(session_id, page_size=15)
    assert page.session_id == session_id
    assert page.total_messages_count == 60
    assert page.page_size == 15
    assert page.has_earlier_messages is True
    assert len(page.messages) == 15
    # Verify latest 15 messages (45 to 59)
    assert page.messages[0].message_id == "msg_045"
    assert page.messages[-1].message_id == "msg_059"
    assert page.earliest_cursor_id == "msg_045"

    # Test empty session edge case
    empty_page = engine.load_bounded_initial_page("sess_empty")
    assert empty_page.total_messages_count == 0
    assert len(empty_page.messages) == 0
    assert empty_page.has_earlier_messages is False


@pytest.mark.asyncio
async def test_lazy_upward_cursor_pagination() -> None:
    """Validate incremental upward historical pagination on upward scrolling."""
    engine = BoundedInitialPageHydrationEngine(default_page_size=10)
    session_id = "sess_bound_002"

    for i in range(35):
        engine.append_raw_message(
            session_id=session_id,
            message_id=f"m_{i:02d}",
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message {i}",
            created_at=2000.0 + i,
        )

    init_page = engine.load_bounded_initial_page(session_id, page_size=10)
    assert len(init_page.messages) == 10
    assert init_page.earliest_cursor_id == "m_25"

    # Scroll upward: load messages preceding m_25
    slice_1 = engine.hydrate_upward_page(session_id, before_cursor_id="m_25", limit=10)
    assert len(slice_1.messages) == 10
    assert slice_1.messages[0].message_id == "m_15"
    assert slice_1.messages[-1].message_id == "m_24"
    assert slice_1.has_more_earlier is True
    assert slice_1.next_upward_cursor == "m_15"

    # Scroll upward again: load preceding m_15
    slice_2 = engine.hydrate_upward_page(session_id, before_cursor_id="m_15", limit=10)
    assert len(slice_2.messages) == 10
    assert slice_2.messages[0].message_id == "m_05"
    assert slice_2.messages[-1].message_id == "m_14"
    assert slice_2.has_more_earlier is True
    assert slice_2.next_upward_cursor == "m_05"

    # Scroll to earliest boundary
    slice_3 = engine.hydrate_upward_page(session_id, before_cursor_id="m_05", limit=10)
    assert len(slice_3.messages) == 5
    assert slice_3.messages[0].message_id == "m_00"
    assert slice_3.messages[-1].message_id == "m_04"
    assert slice_3.has_more_earlier is False
    assert slice_3.next_upward_cursor is None


@pytest.mark.asyncio
async def test_heavy_tool_payload_detachment_and_lazy_fetch() -> None:
    """Ensure oversized tool outputs are detached into blob store with lossless on-demand fetch."""
    blob_store = HeavyToolPayloadBlobStore(spill_threshold_bytes=1024)
    engine = BoundedInitialPageHydrationEngine(blob_store=blob_store)
    session_id = "sess_bound_003"

    # Small message: stays full
    item_small = engine.append_raw_message(
        session_id=session_id,
        message_id="msg_small",
        role="user",
        content="Short instruction",
    )
    assert item_small.hydration_state == MessageHydrationState.FULL
    assert len(item_small.tool_blobs) == 0

    # Huge tool output (>10KB)
    huge_shell_output = "Build log line: [DEBUG] processing AST node\n" * 300
    assert len(huge_shell_output.encode("utf-8")) > 10000

    item_heavy = engine.append_raw_message(
        session_id=session_id,
        message_id="msg_heavy",
        role="assistant",
        content=huge_shell_output,
    )
    assert item_heavy.hydration_state == MessageHydrationState.BLOB_DETACHED
    assert len(item_heavy.tool_blobs) == 1
    assert "DETACHED_BLOB" in item_heavy.content
    assert len(item_heavy.content) < 200  # Only preview kept in active memory

    # Lazy on-demand retrieval of full payload
    blob_ref = item_heavy.tool_blobs[0]
    fetched_payload = blob_store.fetch_blob_payload(blob_ref.blob_id)
    assert fetched_payload == huge_shell_output


@pytest.mark.asyncio
async def test_sliding_window_memory_eviction_and_rehydration() -> None:
    """Validate that exceeding memory threshold converts oldest items into stubs and allows rehydration."""
    engine = BoundedInitialPageHydrationEngine(max_window_size=20)
    session_id = "sess_bound_004"

    # Append 35 messages
    for i in range(35):
        engine.append_raw_message(
            session_id=session_id,
            message_id=f"win_{i:02d}",
            role="user",
            content=f"Detailed message body content for item {i}",
            created_at=3000.0 + i,
        )

    # Evict oldest beyond capacity of 20
    evicted_count = engine.evict_sliding_window_stubs(session_id)
    assert evicted_count == 15

    window = engine._active_window[session_id]
    # Oldest 15 items should now be lightweight stubs
    for i in range(15):
        msg_id = f"win_{i:02d}"
        assert isinstance(window[msg_id], LightweightMessageStub)
        assert window[msg_id].hydration_state == MessageHydrationState.EVICTED_STUB

    # Remaining 20 items remain full
    for i in range(15, 35):
        msg_id = f"win_{i:02d}"
        assert not isinstance(window[msg_id], LightweightMessageStub)

    # On-demand rehydration of evicted item
    rehydrated = engine.rehydrate_stub(session_id, "win_02")
    assert rehydrated is not None
    assert rehydrated.message_id == "win_02"
    assert rehydrated.content == "Detailed message body content for item 2"
    assert rehydrated.hydration_state == MessageHydrationState.FULL


@pytest.mark.asyncio
async def test_fork_aligned_slice_with_partial_window() -> None:
    """Validate accurate branching alignment up to target message ID even on long sessions."""
    engine = BoundedInitialPageHydrationEngine()
    parent_session = "sess_parent_005"
    child_session = "sess_child_fork_005"

    for i in range(30):
        engine.append_raw_message(
            session_id=parent_session,
            message_id=f"p_{i:02d}",
            role="user" if i % 2 == 0 else "assistant",
            content=f"Parent turn {i}",
            created_at=4000.0 + i,
        )

    # Fork at turn 12
    forked_items = engine.fork_aligned_slice(
        session_id=parent_session,
        up_to_message_id="p_12",
        new_session_id=child_session,
    )

    assert len(forked_items) == 13
    assert forked_items[0].message_id == "p_00"
    assert forked_items[-1].message_id == "p_12"

    # Child session has its own independent bounded page
    child_page = engine.load_bounded_initial_page(child_session, page_size=20)
    assert child_page.total_messages_count == 13
    assert child_page.messages[-1].message_id == "p_12"
