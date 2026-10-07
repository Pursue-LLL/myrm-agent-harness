"""Unit test suite for SingleKernelMultiTransportDecouplingAndAsyncAckRpcProtocol (Item 106).

Verifies the "One Kernel, Three Faces" architecture:
- Sub-millisecond Async-Ack handshake decoupling network connections from task execution.
- Monotonically sequenced event frames and disconnect/reattach event replay.
- Interactive, Print/Batch, and RPC transport presentation adapters.
"""

from __future__ import annotations

import json
import time

from myrm_agent_harness.runtime.context.agent_session_kernel import (
    AgentSessionKernel,
)
from myrm_agent_harness.runtime.context.multi_transport_adapters import (
    AsyncAckRpcTransportGateway,
    InteractiveTransportAdapter,
    PrintBatchTransportAdapter,
)
from myrm_agent_harness.runtime.context.single_kernel_transport_types import (
    KernelCommandRequest,
    KernelEventType,
    KernelLifecycleState,
    TransportModeKind,
)


def test_kernel_immediate_async_ack_and_sequenced_lifecycle() -> None:
    """Verify kernel immediately acknowledges prompts without blocking execution."""
    kernel = AgentSessionKernel(session_id="test-session-001")
    collected_events = []

    sub_token = kernel.subscribe(collected_events.append)

    req = KernelCommandRequest(prompt="Analyze database migration schema", task_id="task-1001")

    # Sub-millisecond immediate handshake
    start_time = time.perf_counter()
    ack = kernel.submit_prompt(req)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert elapsed_ms < 50.0  # Handshake must be instantaneous
    assert ack.accepted is True
    assert ack.task_id == "task-1001"
    assert ack.session_id == "test-session-001"
    assert ack.status == KernelLifecycleState.QUEUED

    # Wait for background worker to complete execution
    deadline = time.time() + 3.0
    while kernel.state != KernelLifecycleState.IDLE and time.time() < deadline:
        time.sleep(0.01)

    assert kernel.state == KernelLifecycleState.IDLE
    assert len(collected_events) >= 4

    # Verify event types and monotonic sequence ordering
    seq_ids = [e.seq_id for e in collected_events]
    assert seq_ids == sorted(seq_ids)
    assert len(set(seq_ids)) == len(seq_ids)

    types = [e.event_type for e in collected_events]
    assert types[0] == KernelEventType.TASK_ACCEPTED
    assert types[1] == KernelEventType.TASK_STARTED
    assert types[-1] == KernelEventType.TASK_COMPLETED

    kernel.unsubscribe(sub_token)
    kernel.dispose()


def test_client_reattach_and_event_replay_zero_loss() -> None:
    """Verify disconnected clients can reattach and replay missed events without loss."""
    kernel = AgentSessionKernel(session_id="replay-session")
    req = KernelCommandRequest(prompt="Refactor authentication middleware", task_id="task-2002")

    ack = kernel.submit_prompt(req)
    assert ack.accepted is True

    deadline = time.time() + 3.0
    while kernel.state != KernelLifecycleState.IDLE and time.time() < deadline:
        time.sleep(0.01)

    # Client lost connection after seeing seq_id = 1 (TASK_ACCEPTED)
    missed_events = kernel.replay_events(last_seen_seq_id=1, task_id="task-2002")
    assert len(missed_events) >= 3

    # Every replayed frame must have seq_id > 1
    assert all(f.seq_id > 1 for f in missed_events)
    # The first replayed frame should be TASK_STARTED
    assert missed_events[0].event_type == KernelEventType.TASK_STARTED

    kernel.dispose()


def test_interactive_transport_adapter_streaming() -> None:
    """Verify InteractiveTransportAdapter streams chunks and resolves full response."""
    kernel = AgentSessionKernel(session_id="interactive-session")
    adapter = InteractiveTransportAdapter(kernel)

    assert adapter.mode == TransportModeKind.INTERACTIVE

    received_deltas: list[str] = []
    received_thinking: list[str] = []

    result = adapter.run_interactive(
        prompt="Draft pull request summary",
        on_text_delta=received_deltas.append,
        on_thinking=received_thinking.append,
    )

    assert len(received_thinking) > 0
    assert len(received_deltas) > 0
    assert "Resolved: processed 'Draft pull request summary'" in result

    kernel.dispose()


def test_print_batch_transport_adapter() -> None:
    """Verify PrintBatchTransportAdapter provides clean non-interactive batch output and exit codes."""
    kernel = AgentSessionKernel(session_id="batch-session")
    adapter = PrintBatchTransportAdapter(kernel)

    assert adapter.mode == TransportModeKind.PRINT_BATCH

    output, exit_code = adapter.run_batch("Run integration test suite")
    assert exit_code == 0
    assert "Resolved: processed 'Run integration test suite'" in output

    kernel.dispose()


def test_async_ack_rpc_transport_gateway_protocol() -> None:
    """Verify AsyncAckRpcTransportGateway instant handshake and event streaming."""
    kernel = AgentSessionKernel(session_id="rpc-session")
    emitted_frames: list[str] = []

    gateway = AsyncAckRpcTransportGateway(kernel, event_sink=emitted_frames.append)
    assert gateway.mode == TransportModeKind.RPC

    # Test 1: Immediate prompt command handshake
    cmd_line = json.dumps({"type": "prompt", "prompt": "Benchmark disk IO", "task_id": "task-rpc-1"}) + "\n"
    response_line = gateway.dispatch_rpc_frame(cmd_line)
    resp = json.loads(response_line)

    assert resp["type"] == "ack"
    assert resp["task_id"] == "task-rpc-1"
    assert resp["accepted"] is True
    assert resp["status"] == "queued"

    # Wait for execution to emit events into sink
    deadline = time.time() + 3.0
    while kernel.state != KernelLifecycleState.IDLE and time.time() < deadline:
        time.sleep(0.01)

    assert len(emitted_frames) >= 4
    # Parse first and last event from sink
    evt_first = json.loads(emitted_frames[0])
    assert evt_first["type"] == "event"
    assert evt_first["event_type"] == "task_accepted"

    # Test 2: Resume / Reattach RPC command
    reattach_cmd = json.dumps({"type": "reattach", "last_seen_seq_id": 1, "task_id": "task-rpc-1"}) + "\n"
    reattach_resp_line = gateway.dispatch_rpc_frame(reattach_cmd)
    reattach_resp = json.loads(reattach_resp_line)

    assert reattach_resp["type"] == "replayed_events"
    assert reattach_resp["count"] >= 3
    assert all(ev["seq_id"] > 1 for ev in reattach_resp["events"])

    # Test 3: Get state RPC command
    state_cmd = json.dumps({"type": "get_state"}) + "\n"
    state_resp = json.loads(gateway.dispatch_rpc_frame(state_cmd))
    assert state_resp["type"] == "state"
    assert state_resp["state"] == "idle"

    # Test 4: Malformed input defense
    malformed_resp = json.loads(gateway.dispatch_rpc_frame("NOT_JSON\n"))
    assert malformed_resp["type"] == "error"

    gateway.dispose()
    kernel.dispose()


def test_one_kernel_three_faces_shared_state_consistency() -> None:
    """Verify that multiple transport adapters seamlessly share the exact same kernel state."""
    kernel = AgentSessionKernel(session_id="unified-kernel-3faces")

    interactive = InteractiveTransportAdapter(kernel)
    batch = PrintBatchTransportAdapter(kernel)
    rpc = AsyncAckRpcTransportGateway(kernel)

    # Turn 1 via Interactive
    res_interactive = interactive.run_interactive("Task 1")
    assert "Task 1" in res_interactive

    # Turn 2 via Batch
    res_batch, code = batch.run_batch("Task 2")
    assert code == 0
    assert "Task 2" in res_batch

    # Turn 3 via RPC
    ack_raw = rpc.dispatch_rpc_frame(json.dumps({"type": "prompt", "prompt": "Task 3"}) + "\n")
    ack = json.loads(ack_raw)
    assert ack["accepted"] is True

    # Check that sequence numbering increased across all turns
    deadline = time.time() + 3.0
    while kernel.state != KernelLifecycleState.IDLE and time.time() < deadline:
        time.sleep(0.01)

    replayed = kernel.replay_events(last_seen_seq_id=0)
    # 3 tasks * ~4 events each => >= 12 total events
    assert len(replayed) >= 12
    # Ensure all tasks are recorded in monotonic sequence
    assert replayed[-1].seq_id >= 12

    rpc.dispose()
    kernel.dispose()
