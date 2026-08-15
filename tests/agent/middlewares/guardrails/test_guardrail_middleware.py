import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares.guardrails.core import (
    GuardrailDecision,
    GuardrailProvider,
    GuardrailReason,
    GuardrailRequest,
)
from myrm_agent_harness.agent.middlewares.guardrails.middleware import (
    GuardrailMiddleware,
)


class MockAllowProvider(GuardrailProvider):
    name = "mock_allow"

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(allow=True)

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(allow=True)


class MockDenyProvider(GuardrailProvider):
    name = "mock_deny"

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(
            allow=False,
            reasons=[GuardrailReason(code="mock.denied", message="Mock denial")],
        )

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        return GuardrailDecision(
            allow=False,
            reasons=[GuardrailReason(code="mock.denied", message="Mock denial")],
        )


class MockExceptionProvider(GuardrailProvider):
    name = "mock_exception"

    async def aevaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        raise ValueError("Simulated provider failure")

    def evaluate(self, request: GuardrailRequest) -> GuardrailDecision:
        raise ValueError("Simulated provider failure")


from unittest.mock import MagicMock


@pytest.fixture
def mock_request() -> ToolCallRequest:
    return ToolCallRequest(
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
        tool_call={"name": "test_tool", "args": {"arg1": "value1"}, "id": "call_123"},
    )


async def mock_handler(req: ToolCallRequest) -> ToolMessage:
    return ToolMessage(content="Success", tool_call_id=req.tool_call["id"])


@pytest.mark.asyncio
async def test_guardrail_allow_all(mock_request: ToolCallRequest) -> None:
    middleware = GuardrailMiddleware(providers=[MockAllowProvider()])
    result = await middleware.awrap_tool_call(mock_request, mock_handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "Success"


@pytest.mark.asyncio
async def test_guardrail_deny(mock_request: ToolCallRequest) -> None:
    middleware = GuardrailMiddleware(providers=[MockAllowProvider(), MockDenyProvider()])
    result = await middleware.awrap_tool_call(mock_request, mock_handler)

    assert isinstance(result, ToolMessage)
    assert "Mock denial" in str(result.content)
    assert result.status == "error"
    assert result.additional_kwargs.get("error_category") == "guardrail_blocked"
    assert result.additional_kwargs.get("guardrail_code") == "mock.denied"


@pytest.mark.asyncio
async def test_guardrail_fail_closed_on_exception(
    mock_request: ToolCallRequest,
) -> None:
    middleware = GuardrailMiddleware(providers=[MockExceptionProvider()], fail_closed=True)
    result = await middleware.awrap_tool_call(mock_request, mock_handler)

    assert isinstance(result, ToolMessage)
    assert "guardrail error in mock_exception (fail-closed)" in str(result.content)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_guardrail_fail_open_on_exception(mock_request: ToolCallRequest) -> None:
    middleware = GuardrailMiddleware(providers=[MockExceptionProvider()], fail_closed=False)
    result = await middleware.awrap_tool_call(mock_request, mock_handler)

    assert isinstance(result, ToolMessage)
    assert result.content == "Success"


def test_guardrail_sync_wrap_tool_call_allow(mock_request: ToolCallRequest) -> None:
    """Sync wrap_tool_call parity for signoff clarify ToolNode _func path (R142/R103)."""
    middleware = GuardrailMiddleware(providers=[MockAllowProvider()])

    def sync_handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="SyncSuccess", tool_call_id=req.tool_call["id"])

    result = middleware.wrap_tool_call(mock_request, sync_handler)
    assert isinstance(result, ToolMessage)
    assert result.content == "SyncSuccess"


def test_guardrail_sync_wrap_tool_call_deny(mock_request: ToolCallRequest) -> None:
    """Sync path deny should return a blocked ToolMessage without calling handler."""
    middleware = GuardrailMiddleware(providers=[MockDenyProvider()])

    def sync_handler(req: ToolCallRequest) -> ToolMessage:
        raise AssertionError("handler must not be called when denied")

    result = middleware.wrap_tool_call(mock_request, sync_handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "Mock denial" in result.content


def test_guardrail_sync_fail_closed_on_exception(mock_request: ToolCallRequest) -> None:
    """Sync path provider exception with fail_closed=True blocks."""
    middleware = GuardrailMiddleware(providers=[MockExceptionProvider()], fail_closed=True)
    result = middleware.wrap_tool_call(mock_request, lambda req: ToolMessage(content="x", tool_call_id="c"))
    assert isinstance(result, ToolMessage)
    assert "fail-closed" in result.content


def test_guardrail_sync_fail_open_on_exception(mock_request: ToolCallRequest) -> None:
    """Sync path provider exception with fail_closed=False proceeds to handler."""
    middleware = GuardrailMiddleware(providers=[MockExceptionProvider()], fail_closed=False)

    def sync_handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="SyncOK", tool_call_id=req.tool_call["id"])

    result = middleware.wrap_tool_call(mock_request, sync_handler)
    assert result.content == "SyncOK"


def test_guardrail_sync_empty_providers(mock_request: ToolCallRequest) -> None:
    """Sync path with no providers passes through."""
    middleware = GuardrailMiddleware(providers=[])
    result = middleware.wrap_tool_call(mock_request, lambda req: ToolMessage(content="ok", tool_call_id="c"))
    assert result.content == "ok"


def test_guardrail_build_request_non_dict_args(mock_request: ToolCallRequest) -> None:
    """Non-dict args are normalized to {} in the built request."""
    middleware = GuardrailMiddleware(providers=[MockAllowProvider()])
    request = ToolCallRequest(
        tool=mock_request.tool,
        state={},
        runtime=MagicMock(),
        tool_call={"name": "t", "args": "bad-args", "id": "c1"},
    )
    gr = middleware._build_request(request)
    assert gr.tool_input == {}


def test_guardrail_build_denied_message_defaults() -> None:
    """Missing id/name in tool_call produce safe defaults in denied message."""
    middleware = GuardrailMiddleware(providers=[MockDenyProvider()])
    request = ToolCallRequest(tool=MagicMock(), state={}, runtime=MagicMock(), tool_call={})
    msg = middleware._build_denied_message(
        request,
        GuardrailDecision(allow=False),
    )
    assert "unknown_tool" in msg.content
    assert msg.tool_call_id == "missing_id"
    assert msg.additional_kwargs["guardrail_code"] == "oap.denied"


def test_guardrail_on_tool_start_returns_none() -> None:
    """Legacy on_tool_start hook always returns None."""
    import asyncio

    middleware = GuardrailMiddleware(providers=[MockAllowProvider()])
    assert asyncio.run(middleware.on_tool_start("tool", "input")) is None
