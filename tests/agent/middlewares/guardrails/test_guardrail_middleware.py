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
    middleware = GuardrailMiddleware(
        providers=[MockAllowProvider(), MockDenyProvider()]
    )
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
    middleware = GuardrailMiddleware(
        providers=[MockExceptionProvider()], fail_closed=True
    )
    result = await middleware.awrap_tool_call(mock_request, mock_handler)

    assert isinstance(result, ToolMessage)
    assert "guardrail error in mock_exception (fail-closed)" in str(result.content)
    assert result.status == "error"


@pytest.mark.asyncio
async def test_guardrail_fail_open_on_exception(mock_request: ToolCallRequest) -> None:
    middleware = GuardrailMiddleware(
        providers=[MockExceptionProvider()], fail_closed=False
    )
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
