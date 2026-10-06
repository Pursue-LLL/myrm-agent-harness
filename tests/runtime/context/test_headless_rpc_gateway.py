"""Tests for Unified Headless RPC/JSON Mode & Stdout Event Framing Gateway (Pi Harness v2 Item 23)."""

from __future__ import annotations

import io
import json
import threading
import time

from myrm_agent_harness.runtime.context.headless_rpc_gateway import (
    HeadlessRpcGateway,
    RpcCommand,
    RpcCommandType,
    RpcResponseFrame,
    RpcUIResponseFrame,
)


def test_command_parsing_and_handler_dispatch() -> None:
    """Test parsing commands from JSON line and dispatching to registered handlers."""
    out_buf = io.StringIO()
    gateway = HeadlessRpcGateway(output_stream=out_buf)

    # Register handler for prompt command
    def on_prompt(cmd: RpcCommand) -> RpcResponseFrame:
        msg = str(cmd.payload.get("message", ""))
        return RpcResponseFrame(
            command="prompt",
            success=True,
            command_id=cmd.command_id,
            data={"echo": f"processed: {msg}"},
        )

    gateway.register_handler(RpcCommandType.PROMPT, on_prompt)

    # Ingest prompt line
    input_line = '{"id": "req-101", "type": "prompt", "message": "hello agent"}\n'
    res = gateway.handle_input_line(input_line)

    assert res is not None
    assert res.success is True
    assert res.command == "prompt"
    assert res.command_id == "req-101"

    # Verify stdout buffer contains valid JSON line
    output_str = out_buf.getvalue()
    assert output_str.endswith("\n")
    decoded = json.loads(output_str.strip())
    assert decoded["type"] == "response"
    assert decoded["id"] == "req-101"
    assert decoded["data"]["echo"] == "processed: hello agent"


def test_event_emission() -> None:
    """Test emitting asynchronous lifecycle event frames over stdout."""
    out_buf = io.StringIO()
    gateway = HeadlessRpcGateway(output_stream=out_buf)

    gateway.emit_event(
        "tool_call_started",
        {"tool": "bash", "command": "pytest -v", "turn": 2},
    )

    output_str = out_buf.getvalue()
    decoded = json.loads(output_str.strip())
    assert decoded["type"] == "event"
    assert decoded["event"] == "tool_call_started"
    assert decoded["payload"]["tool"] == "bash"
    assert decoded["payload"]["turn"] == 2
    assert "timestamp_ms" in decoded


def test_stdout_guard_captures_unformatted_print() -> None:
    """Test stdout guard intercepts unformatted print() and wraps into raw_stdout event frame."""
    out_buf = io.StringIO()
    gateway = HeadlessRpcGateway(output_stream=out_buf)

    gateway.install_stdout_guard()
    try:
        # Simulate arbitrary library chatty print
        print("Diagnostic chatter from library internals")
    finally:
        gateway.restore_stdout()

    output_str = out_buf.getvalue()
    lines = [line.strip() for line in output_str.splitlines() if line.strip()]
    assert len(lines) == 1

    # Invariant: Output must remain valid JSON line
    decoded = json.loads(lines[0])
    assert decoded["type"] == "event"
    assert decoded["event"] == "raw_stdout"
    assert "Diagnostic chatter from library internals" in decoded["payload"]["text"]


def test_extension_ui_request_and_response_loop() -> None:
    """Test bidirectional extension UI approval flow with external host."""
    out_buf = io.StringIO()
    gateway = HeadlessRpcGateway(output_stream=out_buf)

    ui_result_container: list[RpcUIResponseFrame] = []

    def run_worker() -> None:
        # Worker emits UI interaction request and waits
        resp = gateway.request_ui_interaction(
            method="confirm",
            title="Dangerous Operation",
            message="Delete temporary database?",
            timeout_seconds=5.0,
        )
        ui_result_container.append(resp)

    th = threading.Thread(target=run_worker)
    th.start()

    # Give worker time to emit request frame
    time.sleep(0.1)

    # Inspect the emitted request frame on stdout
    output_str = out_buf.getvalue()
    lines = [line.strip() for line in output_str.splitlines() if line.strip()]
    req_frame = json.loads(lines[0])
    assert req_frame["type"] == "extension_ui_request"
    assert req_frame["method"] == "confirm"
    req_id = req_frame["id"]

    # External host answers via stdin with extension_ui_response
    answer_line = json.dumps({
        "type": "extension_ui_response",
        "id": req_id,
        "confirmed": True,
    }) + "\n"
    gateway.handle_input_line(answer_line)

    th.join(timeout=3.0)

    # Worker unblocks with response
    assert len(ui_result_container) == 1
    ui_resp = ui_result_container[0]
    assert ui_resp.request_id == req_id
    assert ui_resp.confirmed is True
    assert ui_resp.cancelled is False


def test_malformed_input_json_graceful_error() -> None:
    """Test malformed stdin frame produces error response without gateway crash."""
    out_buf = io.StringIO()
    gateway = HeadlessRpcGateway(output_stream=out_buf)

    # Broken JSON
    res = gateway.handle_input_line("{broken_json\n")
    assert res is not None
    assert res.success is False
    assert "Malformed command frame" in str(res.error)

    # Unknown command type
    res2 = gateway.handle_input_line('{"type": "non_existent_command"}\n')
    assert res2 is not None
    assert res2.success is False
    assert "Unknown RPC command type" in str(res2.error)
