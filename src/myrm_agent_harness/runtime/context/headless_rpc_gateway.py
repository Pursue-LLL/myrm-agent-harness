"""Unified Headless RPC/JSON Mode & Stdout Event Framing Gateway (Pi Harness v2 Item 23).

Implements the Pi Harness v2 headless operation architecture:
1. Standard I/O RPC Framing Protocol:
   - Commands ingested as strict LF-delimited JSON lines from stdin.
   - Responses and events emitted as strict LF-delimited JSON lines on stdout.
2. Stdout Guard & Stream Isolation:
   Intercepts unformatted raw prints or library chatter, wrapping them in structured
   `raw_stdout` event frames to prevent JSONL parsing crashes on external hosts.
3. Bidirectional Extension UI Contract:
   Emits `extension_ui_request` frames (confirm, select, input) to external host
   (IDE plugins, CI pipelines) and resolves on incoming `extension_ui_response` frames.

[INPUT]
- stdin lines / RpcCommand payloads

[OUTPUT]
- RpcCommandType
- RpcCommand
- RpcResponseFrame
- RpcEventFrame
- RpcUIRequestFrame
- RpcUIResponseFrame
- HeadlessRpcGateway

[POS]
Harness runtime context layer. Powers automated pipelines, IDE extensions,
and headless agent execution modes (--mode rpc / --mode json).
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable


class RpcCommandType(StrEnum):
    """Supported RPC command types over stdin."""

    PROMPT = "prompt"
    STEER = "steer"
    FOLLOW_UP = "follow_up"
    ABORT = "abort"
    SET_MODEL = "set_model"
    SET_THINKING_LEVEL = "set_thinking_level"
    GET_STATE = "get_state"
    EXTENSION_UI_RESPONSE = "extension_ui_response"


@dataclass(slots=True, frozen=True)
class RpcCommand:
    """Parsed command arriving from stdin."""

    command_id: str
    command_type: RpcCommandType
    payload: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_json(cls, line: str) -> RpcCommand:
        """Parse strict JSON line into RpcCommand."""
        data = json.loads(line.strip())
        if not isinstance(data, dict):
            raise ValueError("RPC command line must be a JSON object.")

        cmd_id = str(data.get("id") or f"cmd-{uuid.uuid4().hex[:8]}")
        cmd_type_raw = str(data.get("type", ""))
        try:
            cmd_type = RpcCommandType(cmd_type_raw)
        except ValueError as exc:
            raise ValueError(f"Unknown RPC command type: {cmd_type_raw}") from exc

        return cls(command_id=cmd_id, command_type=cmd_type, payload=data)


@dataclass(slots=True, frozen=True)
class RpcResponseFrame:
    """Synchronous command acknowledgment or result frame."""

    command: str
    success: bool
    command_id: str | None = None
    data: dict[str, object] | None = None
    error: str | None = None

    def to_json(self) -> str:
        """Serialize response frame to strict LF-delimited JSON line."""
        body: dict[str, object] = {
            "type": "response",
            "command": self.command,
            "success": self.success,
        }
        if self.command_id is not None:
            body["id"] = self.command_id
        if self.data is not None:
            body["data"] = self.data
        if self.error is not None:
            body["error"] = self.error
        return json.dumps(body, ensure_ascii=False) + "\n"


@dataclass(slots=True, frozen=True)
class RpcEventFrame:
    """Asynchronous streaming lifecycle event frame."""

    event: str
    timestamp_ms: int
    payload: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize event frame to strict LF-delimited JSON line."""
        body = {
            "type": "event",
            "event": self.event,
            "timestamp_ms": self.timestamp_ms,
            "payload": self.payload,
        }
        return json.dumps(body, ensure_ascii=False) + "\n"


@dataclass(slots=True, frozen=True)
class RpcUIRequestFrame:
    """Bidirectional human-in-the-loop interaction request frame."""

    request_id: str
    method: str  # "confirm", "select", "input"
    title: str
    message: str = ""
    options: tuple[str, ...] = field(default_factory=tuple)
    timeout_seconds: float = 30.0

    def to_json(self) -> str:
        """Serialize UI request frame to strict LF-delimited JSON line."""
        body = {
            "type": "extension_ui_request",
            "id": self.request_id,
            "method": self.method,
            "title": self.title,
            "message": self.message,
            "options": list(self.options),
            "timeout_seconds": self.timeout_seconds,
        }
        return json.dumps(body, ensure_ascii=False) + "\n"


@dataclass(slots=True, frozen=True)
class RpcUIResponseFrame:
    """External host response to an extension UI request."""

    request_id: str
    confirmed: bool | None = None
    value: str | None = None
    cancelled: bool = False


class _GuardedStdoutStream(io.TextIOBase):
    """Intercepts raw print() calls and wraps them in structured raw_stdout frames."""

    def __init__(self, gateway: HeadlessRpcGateway) -> None:
        super().__init__()
        self._gateway = gateway

    def write(self, s: str) -> int:
        if s and not s.isspace():
            self._gateway.emit_event("raw_stdout", {"text": s})
        return len(s)

    def flush(self) -> None:
        pass


class HeadlessRpcGateway:
    """Full-duplex headless RPC protocol and event framing gateway."""

    def __init__(
        self,
        output_stream: TextIO | None = None,
        input_stream: TextIO | None = None,
    ) -> None:
        self._output_stream = output_stream if output_stream is not None else sys.stdout
        self._input_stream = input_stream if input_stream is not None else sys.stdin
        self._lock = threading.RLock()
        self._pending_ui_requests: dict[str, tuple[threading.Event, list[RpcUIResponseFrame]]] = {}
        self._command_handlers: dict[RpcCommandType, Callable[[RpcCommand], RpcResponseFrame]] = {}
        self._original_stdout: TextIO | None = None
        self._is_guarded = False

    def register_handler(
        self,
        cmd_type: RpcCommandType,
        handler: Callable[[RpcCommand], RpcResponseFrame],
    ) -> None:
        """Register a callback handler for a specific RPC command type."""
        with self._lock:
            self._command_handlers[cmd_type] = handler

    def emit_response(
        self,
        command: str,
        success: bool,
        command_id: str | None = None,
        data: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        """Emit a structured response frame to stdout."""
        frame = RpcResponseFrame(
            command=command,
            success=success,
            command_id=command_id,
            data=data,
            error=error,
        )
        with self._lock:
            self._output_stream.write(frame.to_json())
            self._output_stream.flush()

    def emit_event(self, event_name: str, payload: dict[str, object]) -> None:
        """Emit an asynchronous streaming lifecycle event frame to stdout."""
        frame = RpcEventFrame(
            event=event_name,
            timestamp_ms=int(time.time() * 1000),
            payload=payload,
        )
        with self._lock:
            self._output_stream.write(frame.to_json())
            self._output_stream.flush()

    def request_ui_interaction(
        self,
        method: str,
        title: str,
        message: str = "",
        options: tuple[str, ...] = (),
        timeout_seconds: float = 30.0,
    ) -> RpcUIResponseFrame:
        """Emit extension UI request and block waiting for external host response."""
        req_id = f"ui-{uuid.uuid4().hex[:12]}"
        req_frame = RpcUIRequestFrame(
            request_id=req_id,
            method=method,
            title=title,
            message=message,
            options=options,
            timeout_seconds=timeout_seconds,
        )

        event = threading.Event()
        container: list[RpcUIResponseFrame] = []

        with self._lock:
            self._pending_ui_requests[req_id] = (event, container)
            self._output_stream.write(req_frame.to_json())
            self._output_stream.flush()

        finished = event.wait(timeout=timeout_seconds)

        with self._lock:
            self._pending_ui_requests.pop(req_id, None)

        if not finished:
            return RpcUIResponseFrame(request_id=req_id, cancelled=True)

        return container[0] if container else RpcUIResponseFrame(request_id=req_id, cancelled=True)

    def handle_input_line(self, line: str) -> RpcResponseFrame | None:
        """Process a single JSON line arriving from stdin."""
        stripped = line.strip()
        if not stripped:
            return None

        try:
            cmd = RpcCommand.from_json(stripped)
        except Exception as exc:
            err_frame = RpcResponseFrame(
                command="unknown",
                success=False,
                error=f"Malformed command frame: {exc}",
            )
            with self._lock:
                self._output_stream.write(err_frame.to_json())
                self._output_stream.flush()
            return err_frame

        # Intercept UI response
        if cmd.command_type == RpcCommandType.EXTENSION_UI_RESPONSE:
            req_id = str(cmd.payload.get("id") or cmd.payload.get("request_id") or "")
            conf = cmd.payload.get("confirmed")
            val = cmd.payload.get("value")
            cancelled = bool(cmd.payload.get("cancelled", False))

            ui_resp = RpcUIResponseFrame(
                request_id=req_id,
                confirmed=bool(conf) if conf is not None else None,
                value=str(val) if val is not None else None,
                cancelled=cancelled,
            )

            with self._lock:
                if req_id in self._pending_ui_requests:
                    evt, box = self._pending_ui_requests[req_id]
                    box.append(ui_resp)
                    evt.set()

            ack = RpcResponseFrame(
                command="extension_ui_response",
                success=True,
                command_id=cmd.command_id,
            )
            with self._lock:
                self._output_stream.write(ack.to_json())
                self._output_stream.flush()
            return ack

        # Dispatch regular business command
        with self._lock:
            handler = self._command_handlers.get(cmd.command_type)

        if handler is None:
            res_frame = RpcResponseFrame(
                command=cmd.command_type.value,
                success=False,
                command_id=cmd.command_id,
                error=f"No handler registered for command: {cmd.command_type.value}",
            )
        else:
            try:
                res_frame = handler(cmd)
            except Exception as exc:
                res_frame = RpcResponseFrame(
                    command=cmd.command_type.value,
                    success=False,
                    command_id=cmd.command_id,
                    error=str(exc),
                )

        with self._lock:
            self._output_stream.write(res_frame.to_json())
            self._output_stream.flush()
        return res_frame

    def install_stdout_guard(self) -> None:
        """Redirect sys.stdout through guard to prevent unformatted prints from breaking JSONL."""
        with self._lock:
            if not self._is_guarded:
                self._original_stdout = sys.stdout
                sys.stdout = _GuardedStdoutStream(self)  # type: ignore[assignment]
                self._is_guarded = True

    def restore_stdout(self) -> None:
        """Restore original sys.stdout."""
        with self._lock:
            if self._is_guarded and self._original_stdout is not None:
                sys.stdout = self._original_stdout
                self._original_stdout = None
                self._is_guarded = False
