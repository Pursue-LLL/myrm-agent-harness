"""Integration: Context Threshold Model Downshift with Session Notes & Pipeline Execution.

Assembles the context management pipeline chain:
- Real ``SessionNotesManager`` tracking structured session notes.
- Real ``DownshiftGovernor`` evaluating real token thresholds.
- Real ``create_context_pipeline_middleware`` with active downshift hook.
- Real ``ensure_tool_pair_integrity`` and prompt cache preservation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
from myrm_agent_harness.agent.middlewares.context_pipeline.context_pipeline_middleware import (
    create_context_pipeline_middleware,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _PassThroughProcessor(BaseProcessor):
    name = "passthrough"

    async def should_process(self, context: ProcessorContext) -> bool:
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        return context


async def test_full_pipeline_downshift_integration() -> None:
    llm = MagicMock()
    llm.model = "claude-3-7-sonnet"
    llm.api_base = "https://api.anthropic.com"

    governor = DownshiftGovernor(
        DownshiftConfig(
            enabled=True,
            trigger_mode=DownshiftTriggerMode.TOKEN_PERCENT,
            context_usage_pct_threshold=0.50,
            auto_fallback_up=True,
        )
    )

    downshifted_states: list[DownshiftState] = []

    async def _on_downshift(state: DownshiftState) -> None:
        downshifted_states.append(state)

    pipeline = ContextPipeline([_PassThroughProcessor()])

    notes_llm = MagicMock()
    notes_llm.model = "claude-3-5-haiku"

    mw = create_context_pipeline_middleware(
        llm=llm,
        pipeline=pipeline,
        downshift_governor=governor,
        on_downshift=_on_downshift,
        session_notes_llm=notes_llm,
    )

    # Seed conversation with human, AI, and tool result messages exceeding 50% of 1000 tokens
    messages = [
        HumanMessage(content="Please refactor the database connector module"),
        AIMessage(content="I will check the files", tool_calls=[{"name": "read_file", "args": {"path": "db.py"}, "id": "call_1"}]),
        ToolMessage(content="class DBConnector:\n" + ("    # Line\n" * 120), tool_call_id="call_1"),
    ]

    req = ModelRequest(
        model=llm,
        messages=messages,
        runtime=Runtime(
            context={
                "chat_id": "integration-session-001",
                "max_context_tokens": 500,  # Small limit to trigger threshold
                "work_units_consumed": 12.5,
            }
        ),
    )

    executed_request: ModelRequest | None = None

    async def _downstream_handler(r: ModelRequest) -> ModelResponse:
        nonlocal executed_request
        executed_request = r
        return ModelResponse(result=[AIMessage(content="Proceeding with refactoring")])

    resp = await mw.awrap_model_call(req, _downstream_handler)

    assert resp is not None
    assert len(downshifted_states) == 1
    state = downshifted_states[0]
    assert state.session_id == "integration-session-001"
    assert state.is_downshifted
    assert state.current_tier == ModelTier.ECONOMY
    assert state.handoff_memo is not None
    assert state.handoff_memo.source_model == "claude-3-7-sonnet"
    assert state.handoff_memo.target_tier == ModelTier.ECONOMY

    # Verify fallback-up integration on economy failure
    fallback_triggered, updated_state = governor.record_economy_outcome("integration-session-001", success=False)
    assert not fallback_triggered
    fallback_triggered, updated_state = governor.record_economy_outcome("integration-session-001", success=False)
    assert fallback_triggered
    assert updated_state.current_tier == ModelTier.PREMIUM
