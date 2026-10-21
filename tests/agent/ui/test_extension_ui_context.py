"""Unit tests for the reverse-push ExtensionUIContext implementation.

[INPUT]
- ReversePushUIContext from myrm_agent_harness.agent.ui
- UIRequest, UIResponse, UISelectOption, ExtensionUICancelledError, ExtensionUITimeoutError, ExtensionUIError from myrm_agent_harness.agent.ui

[OUTPUT]
- Pytest test cases covering the ReversePush bi-directional handshake

[POS]
Unit test suite for Item 28 TransportAgnosticUIContextAndReversePushSubProtocol.
File length < 250 lines. Zero `Any`.
"""

import asyncio

import pytest

from myrm_agent_harness.agent.ui import (
    ExtensionUICancelledError,
    ExtensionUIError,
    ExtensionUITimeoutError,
    ReversePushUIContext,
    UIRequest,
    UIResponse,
    UISelectOption,
)


@pytest.mark.asyncio
async def test_reverse_push_ui_context_select_and_resolve() -> None:
    """Tests bi-directional push and resolution for select."""
    dispatched_requests: list[UIRequest] = []

    async def mock_push_sink(req: UIRequest) -> None:
        dispatched_requests.append(req)

    ui = ReversePushUIContext(push_sink=mock_push_sink)

    options = [
        UISelectOption(label="Production", value="prod"),
        UISelectOption(label="Staging", value="staging"),
    ]

    async def simulate_client_reply() -> None:
        await asyncio.sleep(0.05)
        assert len(dispatched_requests) == 1
        req = dispatched_requests[0]
        assert req.request_type == "select"
        assert req.title == "Select environment"

        # Client responds with chosen value
        resp = UIResponse(request_id=req.request_id, value="staging")
        assert await ui.resolve_response(resp) is True

    client_task = asyncio.create_task(simulate_client_reply())
    selected = await ui.select("Select environment", options, default="prod", timeout_s=2.0)
    await client_task

    assert selected == "staging"
    assert ui.pending_count == 0


@pytest.mark.asyncio
async def test_reverse_push_ui_context_confirm_and_input() -> None:
    """Tests confirm and input interactions."""
    dispatched_requests: list[UIRequest] = []

    async def mock_push_sink(req: UIRequest) -> None:
        dispatched_requests.append(req)

    ui = ReversePushUIContext(push_sink=mock_push_sink)

    # Confirm test
    async def reply_confirm() -> None:
        await asyncio.sleep(0.05)
        req = dispatched_requests[-1]
        assert req.request_type == "confirm"
        await ui.resolve_response(UIResponse(request_id=req.request_id, value=True))

    confirm_task = asyncio.create_task(reply_confirm())
    confirmed = await ui.confirm("Confirm deletion", "Delete item?", default=False, timeout_s=2.0)
    await confirm_task
    assert confirmed is True

    # Input test
    async def reply_input() -> None:
        await asyncio.sleep(0.05)
        req = dispatched_requests[-1]
        assert req.request_type == "input"
        await ui.resolve_response(UIResponse(request_id=req.request_id, value="custom_input_val"))

    input_task = asyncio.create_task(reply_input())
    input_res = await ui.input("Enter key", placeholder="api_key", timeout_s=2.0)
    await input_task
    assert input_res == "custom_input_val"


@pytest.mark.asyncio
async def test_reverse_push_ui_context_cancel_handling() -> None:
    """Tests user cancellation triggers ExtensionUICancelledError."""
    dispatched_requests: list[UIRequest] = []

    async def mock_push_sink(req: UIRequest) -> None:
        dispatched_requests.append(req)

    ui = ReversePushUIContext(push_sink=mock_push_sink)

    async def simulate_cancel() -> None:
        await asyncio.sleep(0.05)
        req = dispatched_requests[0]
        await ui.cancel_request(req.request_id, reason="User clicked Cancel")

    cancel_task = asyncio.create_task(simulate_cancel())

    with pytest.raises(ExtensionUICancelledError) as exc_info:
        await ui.editor("Edit config", "key=1", timeout_s=2.0)
    await cancel_task

    assert "User clicked Cancel" in str(exc_info.value)
    assert ui.pending_count == 0


@pytest.mark.asyncio
async def test_reverse_push_ui_context_timeout_handling() -> None:
    """Tests interaction timeout raises ExtensionUITimeoutError and cleans up pending registry."""
    dispatched_requests: list[UIRequest] = []

    async def mock_push_sink(req: UIRequest) -> None:
        dispatched_requests.append(req)

    ui = ReversePushUIContext(push_sink=mock_push_sink)

    with pytest.raises(ExtensionUITimeoutError) as exc_info:
        # Timeout set to 0.1s, no response sent
        await ui.confirm("Fast timeout", "Wait for answer", timeout_s=0.1)

    assert "timed out after 0.1s" in str(exc_info.value)
    assert ui.pending_count == 0


@pytest.mark.asyncio
async def test_reverse_push_ui_context_error_handling() -> None:
    """Tests client error response raises ExtensionUIError."""
    dispatched_requests: list[UIRequest] = []

    async def mock_push_sink(req: UIRequest) -> None:
        dispatched_requests.append(req)

    ui = ReversePushUIContext(push_sink=mock_push_sink)

    async def simulate_error() -> None:
        await asyncio.sleep(0.05)
        req = dispatched_requests[0]
        await ui.resolve_response(UIResponse(request_id=req.request_id, error="Terminal UI rendering crashed"))

    err_task = asyncio.create_task(simulate_error())

    with pytest.raises(ExtensionUIError) as exc_info:
        await ui.input("Prompt", timeout_s=2.0)
    await err_task

    assert "Terminal UI rendering crashed" in str(exc_info.value)
    assert ui.pending_count == 0
