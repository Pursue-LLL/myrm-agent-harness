"""Unit tests for Context Threshold Model Downshift Governor and Middleware Integration.

[INPUT]
- myrm_agent_harness.agent.context_management.downshift::*
- myrm_agent_harness.agent.context_management.strategies.session_notes.schemas::SessionNotes, NoteSection
- myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware::create_context_pipeline_middleware

[OUTPUT]
Comprehensive test coverage for downshift threshold logic, handoff memo extraction,
fallback-up circuit breaking, and middleware hook execution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from myrm_agent_harness.agent.context_management.downshift import (
    DownshiftConfig,
    DownshiftGovernor,
    DownshiftState,
    DownshiftTriggerMode,
    ModelTier,
)
from myrm_agent_harness.agent.context_management.pipeline import ContextPipeline, ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.base import BaseProcessor
from myrm_agent_harness.agent.context_management.strategies.session_notes.schemas import (
    NoteSection,
    SessionNotes,
)
from myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware import (
    create_context_pipeline_middleware,
)


class _NoOpProcessor(BaseProcessor):
    name = "noop"

    async def should_process(self, context: ProcessorContext) -> bool:
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        return context


def test_downshift_governor_disabled_by_default() -> None:
    gov = DownshiftGovernor(DownshiftConfig(enabled=False))
    triggered, state = gov.check_and_apply_downshift(
        session_id="s1",
        current_tokens=100_000,
        max_context_tokens=128_000,
        current_wu=200.0,
    )
    assert not triggered
    assert not state.is_downshifted
    assert state.current_tier == ModelTier.PREMIUM


def test_downshift_governor_token_percent_trigger() -> None:
    gov = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            trigger_mode=DownshiftTriggerMode.TOKEN_PERCENT,
            context_usage_pct_threshold=0.60,
        )
    )
    # 50k / 100k = 50% -> No trigger
    triggered, state = gov.check_and_apply_downshift(
        session_id="s1",
        current_tokens=50_000,
        max_context_tokens=100_000,
        current_model_name="claude-3-7-sonnet",
    )
    assert not triggered
    assert not state.is_downshifted

    # 65k / 100k = 65% -> Trigger
    triggered, state = gov.check_and_apply_downshift(
        session_id="s1",
        current_tokens=65_000,
        max_context_tokens=100_000,
        turn_index=5,
        current_model_name="claude-3-7-sonnet",
    )
    assert triggered
    assert state.is_downshifted
    assert state.current_tier == ModelTier.ECONOMY
    assert state.downshifted_turn == 5
    assert "65.00%" in state.downshift_reason


def test_downshift_governor_wu_trigger() -> None:
    gov = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            trigger_mode=DownshiftTriggerMode.WORK_UNITS,
            wu_threshold=50.0,
        )
    )
    # WU 30.0 -> No trigger
    triggered, state = gov.check_and_apply_downshift(
        session_id="s2",
        current_tokens=10_000,
        max_context_tokens=100_000,
        current_wu=30.0,
    )
    assert not triggered

    # WU 55.0 -> Trigger
    triggered, state = gov.check_and_apply_downshift(
        session_id="s2",
        current_tokens=10_000,
        max_context_tokens=100_000,
        current_wu=55.0,
    )
    assert triggered
    assert state.is_downshifted
    assert state.current_tier == ModelTier.ECONOMY


def test_downshift_governor_handoff_memo_from_session_notes() -> None:
    gov = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            trigger_mode=DownshiftTriggerMode.TOKEN_PERCENT,
            context_usage_pct_threshold=0.50,
        )
    )
    notes = SessionNotes(
        sections=[
            NoteSection(key="task_spec", title="Task", description="", content="Refactor auth module"),
            NoteSection(key="current_state", title="State", description="", content="Writing unit tests"),
            NoteSection(key="files_and_functions", title="Files", description="", content="auth.py::login"),
            NoteSection(key="errors_and_corrections", title="Errors", description="", content="Mock token error"),
            NoteSection(key="remaining_steps", title="Steps", description="", content="Run pytest"),
        ]
    )

    triggered, state = gov.check_and_apply_downshift(
        session_id="s3",
        current_tokens=60_000,
        max_context_tokens=100_000,
        turn_index=8,
        current_model_name="gpt-4.5",
        session_notes=notes,
    )
    assert triggered
    assert state.handoff_memo is not None
    memo = state.handoff_memo
    assert memo.source_model == "gpt-4.5"
    assert memo.target_tier == ModelTier.ECONOMY
    assert memo.task_spec == "Refactor auth module"
    assert memo.current_state == "Writing unit tests"
    assert memo.files_and_functions == "auth.py::login"
    assert memo.errors_and_corrections == "Mock token error"
    assert memo.remaining_steps == "Run pytest"

    prompt_snippet = memo.to_system_supplement()
    assert "### [CONTEXT HANDOVER MEMO" in prompt_snippet
    assert "Refactor auth module" in prompt_snippet


def test_downshift_governor_fallback_up_on_consecutive_failures() -> None:
    gov = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            max_consecutive_economy_failures=2,
            auto_fallback_up=True,
        )
    )
    # Force downshift state
    state = gov.get_or_create_state("s4")
    state.is_downshifted = True
    state.current_tier = ModelTier.ECONOMY

    # First failure -> No fallback up yet
    fallback_triggered, state = gov.record_economy_outcome("s4", success=False)
    assert not fallback_triggered
    assert state.current_tier == ModelTier.ECONOMY
    assert state.consecutive_economy_failures == 1

    # Second failure -> Fallback Up triggered!
    fallback_triggered, state = gov.record_economy_outcome("s4", success=False)
    assert fallback_triggered
    assert state.current_tier == ModelTier.PREMIUM
    assert state.fallback_up_count == 1
    assert state.consecutive_economy_failures == 0


def test_downshift_governor_manual_revocation() -> None:
    gov = DownshiftGovernor(DownshiftConfig(enabled=True))
    state = gov.get_or_create_state("s5")
    state.is_downshifted = True
    state.current_tier = ModelTier.ECONOMY

    revoked = gov.revoke_downshift("s5")
    assert revoked
    assert not state.is_downshifted
    assert state.current_tier == ModelTier.PREMIUM
    assert state.manually_revoked

    # Check that subsequent threshold check does not re-downshift
    triggered, state = gov.check_and_apply_downshift(
        session_id="s5",
        current_tokens=90_000,
        max_context_tokens=100_000,
    )
    assert not triggered
    assert state.current_tier == ModelTier.PREMIUM


@pytest.mark.asyncio
async def test_context_pipeline_middleware_downshift_callback_invocation() -> None:
    llm = MagicMock()
    llm.model = "test-premium-model"
    llm.api_base = ""

    gov = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            trigger_mode=DownshiftTriggerMode.TOKEN_PERCENT,
            context_usage_pct_threshold=0.01,  # low threshold to trigger with simple message
        )
    )
    downshift_callback_mock = AsyncMock()

    custom_pipeline = ContextPipeline([_NoOpProcessor()])
    mw = create_context_pipeline_middleware(
        llm=llm,
        pipeline=custom_pipeline,
        downshift_governor=gov,
        on_downshift=downshift_callback_mock,
    )

    req = ModelRequest(
        model=llm,
        messages=[HumanMessage(content="Hello world " * 50)],
        runtime=Runtime(
            context={
                "chat_id": "test-chat-downshift",
                "max_context_tokens": 100,  # small max tokens
                "work_units_consumed": 0.0,
            }
        ),
    )

    async def _mock_handler(r: ModelRequest) -> ModelResponse:
        return ModelResponse(result=[])

    await mw.awrap_model_call(req, _mock_handler)

    assert downshift_callback_mock.called
    called_state = downshift_callback_mock.call_args[0][0]
    assert isinstance(called_state, DownshiftState)
    assert called_state.session_id == "test-chat-downshift"
    assert called_state.is_downshifted
    assert called_state.current_tier == ModelTier.ECONOMY
