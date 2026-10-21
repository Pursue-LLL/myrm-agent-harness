"""Tests for _handle_allowed_tools_tool_choice_rejected oneshot recovery."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from myrm_agent_harness.agent.streaming.recovery.stream_recovery_oneshot import (
    OneshotRecoveryMixin,
)
from myrm_agent_harness.toolkits.llms.allowed_tools_capability import (
    CAPABILITY_REJECTS_ALLOWED_TOOLS,
)
from myrm_agent_harness.toolkits.llms.capability_learner import (
    ModelCapabilityLearner,
    get_capability_learner,
)


@dataclass
class _FakeStreamContext:
    agent_input: dict[str, object] = field(default_factory=dict)
    message_id: str = "test-msg-id"
    merged_context: dict[str, object] = field(default_factory=dict)
    llm_info: dict[str, str | None] | None = None


class _FakeCompactor:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def put(self, event: dict) -> None:
        self.events.append(event)


class _FakeError(Exception):
    def __init__(self, msg: str, status_code: int | None = None) -> None:
        super().__init__(msg)
        self.status_code = status_code


class _FakeRecovery(OneshotRecoveryMixin):
    def __init__(self, ctx: _FakeStreamContext, compactor: _FakeCompactor) -> None:
        self._ctx = ctx  # type: ignore[assignment]
        self._compactor = compactor  # type: ignore[assignment]
        self.streaming_final_answer = True


@pytest.fixture(autouse=True)
def _reset_learner() -> None:
    ModelCapabilityLearner._instance = None
    yield
    ModelCapabilityLearner._instance = None


class TestHandleAllowedToolsRejected:
    @pytest.mark.asyncio
    async def test_handles_allowed_tools_rejected_error(self) -> None:
        ctx = _FakeStreamContext(
            llm_info={"model_name": "openai-like/agnes-2.5-flash", "base_url": None},
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("Invalid tool_choice: allowed_tools is unsupported", status_code=400)
        result = await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)

        assert result is True
        assert recovery.streaming_final_answer is False

    @pytest.mark.asyncio
    async def test_skips_if_already_attempted(self) -> None:
        ctx = _FakeStreamContext()
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("unsupported tool_choice allowed_tools", status_code=400)
        result = await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_skips_non_tool_choice_error(self) -> None:
        ctx = _FakeStreamContext()
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("rate limit exceeded", status_code=429)
        result = await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_learns_model_capability(self) -> None:
        ctx = _FakeStreamContext(
            llm_info={"model_name": "GPT-4o-mini", "base_url": None},
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("tool_choice type allowed_tools not supported", status_code=400)
        await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)

        learner = get_capability_learner()
        assert learner.get("gpt-4o-mini", CAPABILITY_REJECTS_ALLOWED_TOOLS) is True

    @pytest.mark.asyncio
    async def test_learns_model_capability_scoped_to_api_base(self) -> None:
        ctx = _FakeStreamContext(
            llm_info={
                "model_name": "gpt-4o-mini",
                "api_base": "https://api-a.example.com/v1",
            },
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("tool_choice type allowed_tools not supported", status_code=400)
        await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)

        learner = get_capability_learner()
        assert (
            learner.get(
                "gpt-4o-mini@https://api-a.example.com/v1",
                CAPABILITY_REJECTS_ALLOWED_TOOLS,
            )
            is True
        )
        assert learner.get("gpt-4o-mini", CAPABILITY_REJECTS_ALLOWED_TOOLS) is None

    @pytest.mark.asyncio
    async def test_emits_recovery_event(self) -> None:
        ctx = _FakeStreamContext(
            llm_info={"model_name": "openai-like/agnes-2.5-flash", "base_url": None},
        )
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("allowed_tools tool_choice rejected", status_code=400)
        await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)

        assert len(compactor.events) == 1
        assert compactor.events[0]["step_key"] == "allowed_tools_rejected_recovery"
        assert compactor.events[0]["restart"] is True

    @pytest.mark.asyncio
    async def test_no_learn_when_model_name_missing(self) -> None:
        ctx = _FakeStreamContext()
        compactor = _FakeCompactor()
        recovery = _FakeRecovery(ctx, compactor)

        exc = _FakeError("unsupported allowed_tools tool_choice", status_code=400)
        result = await recovery._handle_allowed_tools_tool_choice_rejected(exc, attempted=False)

        assert result is True
        assert get_capability_learner().size() == 0
