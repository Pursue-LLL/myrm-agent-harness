# ============================================================================
# Unit Tests for Cross-Device Session Handover & Attachment Hub (Item 159)
# ============================================================================

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.handover import (
    ActiveSessionAttachmentHub,
    AttachmentCatchupSnapshot,
    AttachmentMode,
    DeviceInfo,
    DeviceKind,
    HandoverSessionHandle,
    SessionExecutionState,
    TerminalOutputChunk,
    TerminalOutputRingBuffer,
)


def test_ring_buffer_fifo_and_delta_catchup() -> None:
    """Validate ring buffer FIFO capacity and incremental delta polling."""
    ring = TerminalOutputRingBuffer(max_chunks=5)

    # 1. Append 3 chunks
    c1 = ring.append(stream="stdout", content="line 1")
    c2 = ring.append(stream="stderr", content="warn 2")
    c3 = ring.append(stream="stdout", content="line 3")

    assert c1.chunk_id == 1
    assert c2.chunk_id == 2
    assert c3.chunk_id == 3
    assert ring.latest_chunk_id == 3

    # Snapshot check
    snap = ring.get_snapshot()
    assert len(snap) == 3
    assert [c.content for c in snap] == ["line 1", "warn 2", "line 3"]

    # Incremental polling after chunk 1
    delta = ring.get_chunks_since(last_chunk_id=1)
    assert len(delta) == 2
    assert [c.content for c in delta] == ["warn 2", "line 3"]

    # 2. Append more chunks to trigger FIFO wrap
    c4 = ring.append(stream="stdout", content="line 4")
    c5 = ring.append(stream="stdout", content="line 5")
    c6 = ring.append(stream="stdout", content="line 6")  # c1 evicted!

    snap_wrapped = ring.get_snapshot()
    assert len(snap_wrapped) == 5
    assert snap_wrapped[0].chunk_id == 2
    assert snap_wrapped[-1].chunk_id == 6


def test_active_session_registration_and_list() -> None:
    """Validate registering session and retrieving from active sessions catalog."""
    hub = ActiveSessionAttachmentHub()
    dev_mobile = DeviceInfo(
        device_id="dev-phone-001",
        kind=DeviceKind.MOBILE,
        device_name="iPhone 15 Pro",
    )

    handle = hub.register_session(
        session_id="session-job-99",
        title="Data Migration Task",
        initial_device=dev_mobile,
    )

    assert handle.session_id == "session-job-99"
    assert handle.active_controller_device_id == "dev-phone-001"
    assert handle.state == SessionExecutionState.RUNNING

    active_list = hub.list_active_sessions()
    assert len(active_list) == 1
    assert active_list[0].session_id == "session-job-99"

    retrieved = hub.get_session("session-job-99")
    assert retrieved is not None
    assert retrieved.title == "Data Migration Task"


def test_cross_device_handover_exclusive_steer() -> None:
    """Validate full handover flow: mobile starts -> detaches to background -> desktop attaches."""
    hub = ActiveSessionAttachmentHub()
    dev_mobile = DeviceInfo(
        device_id="dev-phone-001",
        kind=DeviceKind.MOBILE,
        device_name="iPhone 15 Pro",
    )
    dev_desktop = DeviceInfo(
        device_id="dev-macbook-002",
        kind=DeviceKind.DESKTOP,
        device_name="MacBook Pro M3",
    )

    # 1. Mobile registers and executes
    hub.register_session("session-long-build", "Rust Kernel Build", initial_device=dev_mobile)
    hub.broadcast_terminal_output("session-long-build", "stdout", "cargo build --release\n")
    hub.broadcast_terminal_output("session-long-build", "stdout", "Compiling kernel v0.1.0\n")

    # 2. User walks out and mobile detaches (background persistence)
    handle_detached = hub.detach_device("session-long-build", dev_mobile.device_id, keep_background=True)
    assert handle_detached.state == SessionExecutionState.DETACHED_BACKGROUND
    assert handle_detached.active_controller_device_id is None

    # Server continues outputting in background while detached
    hub.broadcast_terminal_output("session-long-build", "stdout", "Linking target binaries...\n")

    # 3. User arrives at office and attaches from Desktop
    catchup = hub.attach_device(
        session_id="session-long-build",
        device=dev_desktop,
        mode=AttachmentMode.EXCLUSIVE_STEER,
    )

    # Instantaneous snapshot replayed to desktop
    assert catchup.state == SessionExecutionState.RUNNING
    assert catchup.active_controller_device_id == "dev-macbook-002"
    assert len(catchup.history_output_chunks) == 3
    assert catchup.history_output_chunks[0].content == "cargo build --release\n"
    assert catchup.history_output_chunks[-1].content == "Linking target binaries...\n"
    assert catchup.last_chunk_id == 3

    # Hub handle updated
    session_now = hub.get_session("session-long-build")
    assert session_now is not None
    assert session_now.active_controller_device_id == "dev-macbook-002"
    assert session_now.state == SessionExecutionState.RUNNING


def test_shared_observation_and_incremental_polling() -> None:
    """Validate shared observer mirroring and real-time output stream polling."""
    hub = ActiveSessionAttachmentHub()
    dev_desktop = DeviceInfo(
        device_id="dev-macbook-001",
        kind=DeviceKind.DESKTOP,
        device_name="MacBook Pro",
    )
    dev_web = DeviceInfo(
        device_id="dev-web-viewer",
        kind=DeviceKind.WEB,
        device_name="Chrome WebUI",
    )

    hub.register_session("session-test-eval", "Workflow Eval", initial_device=dev_desktop)
    hub.broadcast_terminal_output("session-test-eval", "stdout", "Step 1: Init\n")

    # Web client connects in shared observe mode
    snap = hub.attach_device("session-test-eval", dev_web, mode=AttachmentMode.SHARED_OBSERVE)
    assert snap.active_controller_device_id == "dev-macbook-001"  # Desktop still controls!
    assert len(snap.history_output_chunks) == 1

    session_handle = hub.get_session("session-test-eval")
    assert session_handle is not None
    assert "dev-web-viewer" in session_handle.attached_observers

    # Desktop continues executing
    hub.broadcast_terminal_output("session-test-eval", "stdout", "Step 2: Testing\n")
    hub.broadcast_terminal_output("session-test-eval", "stdout", "Step 3: Done\n")

    # Web client polls incrementally since last chunk id (1)
    new_chunks = hub.poll_incremental_output("session-test-eval", last_chunk_id=snap.last_chunk_id)
    assert len(new_chunks) == 2
    assert [c.content for c in new_chunks] == ["Step 2: Testing\n", "Step 3: Done\n"]
