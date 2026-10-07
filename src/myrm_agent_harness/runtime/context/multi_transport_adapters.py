"""Multi-transport adapters for the unified AgentSession kernel.

Implements the "One Kernel, Three Faces" architecture:
1. InteractiveTransportAdapter: Real-time streaming for WebUI, Desktop, and CLI.
2. PrintBatchTransportAdapter: Non-interactive batch execution for CI/CD and scripts.
3. AsyncAckRpcTransportGateway: Asynchronous handshake RPC protocol with instant
   Async-Ack frame response, independent event streaming, and reattach/resume replay.
Strict 0 Any, thread-safe, single file <400 lines.

[INPUT]
- runtime.context.agent_session_kernel::AgentSessionKernel (POS: Unified AgentSession Kernel
  implementation.)
- runtime.context.single_kernel_transport_types::AsyncAckFrame, KernelCommandRequest, KernelEventFrame,
  KernelEventType, TransportModeKind (POS: Type contracts for single-kernel multi-transport decoupling and
  async-ack RPC protocol.)

[OUTPUT]
- InteractiveTransportAdapter: Real-time streaming adapter for interactive UI and desktop sessions.
- PrintBatchTransportAdapter: Non-interactive batch executor returning final synthesized output and exit
  codes.
- AsyncAckRpcTransportGateway: Asynchronous Ack RPC protocol gateway decoupling network connections from
  task execution.

[POS]
Multi-transport adapters for the unified AgentSession kernel.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections.abc import Callable

from .agent_session_kernel import AgentSessionKernel
from .single_kernel_transport_types import (
    AsyncAckFrame,
    KernelCommandRequest,
    KernelEventFrame,
    KernelEventType,
    TransportModeKind,
)

logger = logging.getLogger(__name__)


class InteractiveTransportAdapter:
    """Real-time streaming adapter for interactive UI and desktop sessions."""

    def __init__(self, kernel: AgentSessionKernel) -> None:
        self._kernel = kernel

    @property
    def mode(self) -> TransportModeKind:
        """Return the transport mode identifier."""
        return TransportModeKind.INTERACTIVE

    def run_interactive(
        self,
        prompt: str,
        *,
        on_text_delta: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        timeout_seconds: float = 30.0,
    ) -> str:
        """Execute a prompt interactively, streaming chunks and blocking until final completion."""
        event_q: queue.Queue[KernelEventFrame] = queue.Queue()
        sub_token = self._kernel.subscribe(event_q.put)

        accumulated_text: list[str] = []
        request = KernelCommandRequest(prompt=prompt)

        ack = self._kernel.submit_prompt(request)
        if not ack.accepted:
            self._kernel.unsubscribe(sub_token)
            raise RuntimeError(f"Prompt rejected by kernel: {ack.message}")

        try:
            done = False
            while not done:
                try:
                    frame = event_q.get(timeout=timeout_seconds)
                except queue.Empty as err:
                    raise TimeoutError(f"Interactive execution timed out after {timeout_seconds}s") from err

                if frame.task_id != ack.task_id:
                    continue

                if frame.event_type == KernelEventType.THINKING_CHUNK:
                    chunk = frame.payload.get("chunk", "")
                    if on_thinking and chunk:
                        on_thinking(chunk)
                elif frame.event_type == KernelEventType.TEXT_DELTA:
                    delta = frame.payload.get("delta", "")
                    if delta:
                        accumulated_text.append(delta)
                        if on_text_delta:
                            on_text_delta(delta)
                elif frame.event_type in (
                    KernelEventType.TASK_COMPLETED,
                    KernelEventType.TASK_ABORTED,
                    KernelEventType.TASK_FAILED,
                ):
                    done = True
        finally:
            self._kernel.unsubscribe(sub_token)

        return "".join(accumulated_text)


class PrintBatchTransportAdapter:
    """Non-interactive batch executor returning final synthesized output and exit codes."""

    def __init__(self, kernel: AgentSessionKernel) -> None:
        self._kernel = kernel

    @property
    def mode(self) -> TransportModeKind:
        """Return the transport mode identifier."""
        return TransportModeKind.PRINT_BATCH

    def run_batch(
        self,
        prompt: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> tuple[str, int]:
        """Execute prompt in headless batch mode.

        Returns (final_output, exit_code), where exit_code 0 represents success.
        """
        result_event = threading.Event()
        output_chunks: list[str] = []
        exit_code = 0

        request = KernelCommandRequest(prompt=prompt)

        def _on_event(frame: KernelEventFrame) -> None:
            nonlocal exit_code
            if frame.task_id != request.task_id:
                return
            if frame.event_type == KernelEventType.TEXT_DELTA:
                chunk = frame.payload.get("delta", "")
                if chunk:
                    output_chunks.append(chunk)
            elif frame.event_type == KernelEventType.TASK_COMPLETED:
                result_event.set()
            elif frame.event_type in (KernelEventType.TASK_ABORTED, KernelEventType.TASK_FAILED):
                exit_code = 1
                result_event.set()

        sub_token = self._kernel.subscribe(_on_event)
        ack = self._kernel.submit_prompt(request)
        if not ack.accepted:
            self._kernel.unsubscribe(sub_token)
            return ack.message, 1

        try:
            signaled = result_event.wait(timeout=timeout_seconds)
            if not signaled:
                return "Execution timed out", 124
            return "".join(output_chunks), exit_code
        finally:
            self._kernel.unsubscribe(sub_token)


class AsyncAckRpcTransportGateway:
    """Asynchronous Ack RPC protocol gateway decoupling network connections from task execution."""

    def __init__(
        self,
        kernel: AgentSessionKernel,
        event_sink: Callable[[str], None] | None = None,
    ) -> None:
        self._kernel = kernel
        self._event_sink = event_sink
        self._sub_token = self._kernel.subscribe(self._forward_event_to_sink)

    @property
    def mode(self) -> TransportModeKind:
        """Return the transport mode identifier."""
        return TransportModeKind.RPC

    def dispatch_rpc_frame(self, line: str) -> str:
        """Process incoming LF-delimited JSON command line and return immediate response frame."""
        try:
            data = json.loads(line.strip())
        except Exception as exc:
            return json.dumps({"type": "error", "message": f"Malformed JSON: {exc}"}) + "\n"

        if not isinstance(data, dict):
            return json.dumps({"type": "error", "message": "RPC payload must be a JSON object"}) + "\n"

        cmd_type = str(data.get("type", "")).lower()

        if cmd_type == "prompt":
            return self._handle_prompt_cmd(data)
        if cmd_type == "reattach" or cmd_type == "resume":
            return self._handle_reattach_cmd(data)
        if cmd_type == "abort":
            return self._handle_abort_cmd(data)
        if cmd_type == "get_state":
            return self._handle_get_state_cmd()

        return json.dumps({"type": "error", "message": f"Unknown RPC command type: {cmd_type}"}) + "\n"

    def _handle_prompt_cmd(self, data: dict[str, object]) -> str:
        prompt_text = str(data.get("prompt", ""))
        task_id = str(data.get("task_id") or "")
        req = (
            KernelCommandRequest(prompt=prompt_text, task_id=task_id)
            if task_id
            else KernelCommandRequest(prompt=prompt_text)
        )
        # Immediate sub-millisecond handshake response
        ack: AsyncAckFrame = self._kernel.submit_prompt(req)
        response_data: dict[str, object] = {
            "type": "ack",
            "task_id": ack.task_id,
            "accepted": ack.accepted,
            "status": ack.status.value,
            "initial_seq_id": ack.initial_seq_id,
            "session_id": ack.session_id,
            "message": ack.message,
            "timestamp_ms": ack.timestamp_ms,
        }
        return json.dumps(response_data) + "\n"

    def _handle_reattach_cmd(self, data: dict[str, object]) -> str:
        last_seq = int(str(data.get("last_seen_seq_id", 0)))
        task_id = str(data.get("task_id", "")) or None
        replayed_frames = self._kernel.replay_events(last_seq, task_id=task_id)
        response_data: dict[str, object] = {
            "type": "replayed_events",
            "count": len(replayed_frames),
            "events": [
                {
                    "event_id": f.event_id,
                    "seq_id": f.seq_id,
                    "task_id": f.task_id,
                    "event_type": f.event_type.value,
                    "payload": f.payload,
                    "timestamp_ms": f.timestamp_ms,
                }
                for f in replayed_frames
            ],
        }
        return json.dumps(response_data) + "\n"

    def _handle_abort_cmd(self, data: dict[str, object]) -> str:
        task_id = str(data.get("task_id", "")) or None
        success = self._kernel.abort(task_id)
        return json.dumps({"type": "abort_ack", "success": success, "task_id": task_id}) + "\n"

    def _handle_get_state_cmd(self) -> str:
        return json.dumps({
            "type": "state",
            "state": self._kernel.state.value,
            "session_id": self._kernel.session_id,
            "active_task_id": self._kernel.active_task_id,
        }) + "\n"

    def _forward_event_to_sink(self, frame: KernelEventFrame) -> None:
        if self._event_sink is None:
            return
        payload: dict[str, object] = {
            "type": "event",
            "event_id": frame.event_id,
            "seq_id": frame.seq_id,
            "task_id": frame.task_id,
            "event_type": frame.event_type.value,
            "payload": frame.payload,
            "timestamp_ms": frame.timestamp_ms,
        }
        try:
            self._event_sink(json.dumps(payload) + "\n")
        except Exception as exc:
            logger.warning("Error forwarding event frame to sink: %s", exc)

    def dispose(self) -> None:
        """Tear down subscription listeners."""
        self._kernel.unsubscribe(self._sub_token)
