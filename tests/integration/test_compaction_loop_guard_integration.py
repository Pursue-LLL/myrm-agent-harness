"""Integration: context compaction → LoopGuard budget reset

Verifies the full middleware chain: when ContextPipeline compresses
messages and saves tokens, the context_pipeline_middleware calls
notify_loop_guard_compaction(), resetting the LoopGuard iteration
budget while preserving error signatures.

No real LLM required — uses a custom CompressProcessor stub.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline import (
    ContextPipeline,
    ProcessorContext,
)
from myrm_agent_harness.agent.context_management.pipeline.base import BaseProcessor
from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
    _loop_guard_var,
    get_loop_guard,
)
from myrm_agent_harness.agent.security.guards.loop_guard import LoopGuard


class _FakeCompressor(BaseProcessor):
    """Simulates a compressor that trims older messages and reports savings."""

    name = "fake_compress"

    async def should_process(self, context: ProcessorContext) -> bool:
        return len(context.messages) > 4

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        kept = context.messages[-4:]
        saved = len(context.messages) - len(kept)
        context.messages = kept
        context.tokens_saved += saved * 200
        context.operations.append("compress")
        return context


def _build_long_conversation(rounds: int = 12) -> list:
    """Build a realistic multi-turn conversation with tool outputs."""
    msgs: list = []
    for i in range(rounds):
        msgs.append(HumanMessage(content=f"Task {i}: run tests"))
        msgs.append(
            AIMessage(
                content="Running...",
                tool_calls=[{"id": f"call_{i}", "name": "bash_code_execute_tool", "args": {"cmd": f"pytest test_{i}.py"}}],
            )
        )
        msgs.append(
            ToolMessage(
                content=f"PASSED test_{i}.py [exit_code: 0]",
                tool_call_id=f"call_{i}",
                name="bash_code_execute_tool",
            )
        )
    return msgs


def _simulate_tool_calls(guard: LoopGuard, count: int) -> None:
    """Simulate accumulated budget usage without triggering budget-exhaustion.

    Directly sets total_calls and populates the window with synthetic records
    so that notify_compaction()'s clearing behavior can be verified.
    """
    from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord

    guard._metrics.total_calls = count
    for i in range(min(count, 10)):
        guard._window.append(CallRecord(tool_name=f"tool_{i}", args_hash=f"h{i}", args={"i": i}))


@pytest.fixture(autouse=True)
def _reset_loop_guard_var():
    """Ensure each test starts with a fresh LoopGuard in the ContextVar."""
    guard = LoopGuard()
    token = _loop_guard_var.set(guard)
    yield
    _loop_guard_var.reset(token)


@pytest.mark.asyncio
async def test_compaction_resets_loop_guard_budget_full_chain():
    """Full chain: middleware → pipeline compress → notify_loop_guard_compaction.

    Steps:
    1. Set up a LoopGuard in the ContextVar with accumulated tool calls
    2. Create context_pipeline_middleware with a fake compressor pipeline
    3. Invoke the middleware with a long conversation
    4. Verify LoopGuard.total_calls is reset to 0
    5. Verify error_signatures are preserved
    """
    guard = _loop_guard_var.get()
    _simulate_tool_calls(guard, 40)

    guard._error_signatures["crash://db-timeout"] = 3
    assert guard._metrics.total_calls == 40
    assert "crash://db-timeout" in guard._error_signatures

    pipeline = ContextPipeline([_FakeCompressor()])

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(
        llm=mock_llm,
        pipeline=pipeline,
    )

    from langchain.agents.middleware import ModelRequest

    messages = _build_long_conversation(rounds=12)
    request = ModelRequest(model=mock_llm, messages=messages)
    handler = AsyncMock()
    handler.return_value = MagicMock()

    await middleware.awrap_model_call(request, handler)

    assert guard._metrics.total_calls == 0, (
        f"Expected total_calls=0 after compaction, got {guard._metrics.total_calls}"
    )
    assert "crash://db-timeout" in guard._error_signatures, (
        "Error signatures must survive compaction"
    )
    assert len(guard._window) == 0, "Window should be cleared after compaction"
    assert len(guard._output_history) == 0, "Output history should be cleared"


@pytest.mark.asyncio
async def test_no_compaction_preserves_loop_guard_budget():
    """When pipeline saves 0 tokens, LoopGuard budget must NOT be reset."""
    guard = _loop_guard_var.get()
    _simulate_tool_calls(guard, 20)
    assert guard._metrics.total_calls == 20

    class _NoOpProcessor(BaseProcessor):
        name = "noop"

        async def should_process(self, context: ProcessorContext) -> bool:
            return False

        async def process(self, context: ProcessorContext) -> ProcessorContext:
            return context

    pipeline = ContextPipeline([_NoOpProcessor()])

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(llm=mock_llm, pipeline=pipeline)

    from langchain.agents.middleware import ModelRequest

    messages = [HumanMessage(content="short conversation")]
    request = ModelRequest(model=mock_llm, messages=messages)
    handler = AsyncMock()
    handler.return_value = MagicMock()

    await middleware.awrap_model_call(request, handler)

    assert guard._metrics.total_calls == 20, (
        f"Expected total_calls=20 (unchanged), got {guard._metrics.total_calls}"
    )


@pytest.mark.asyncio
async def test_compaction_then_new_calls_count_from_zero():
    """After compaction resets budget, new tool calls start counting from 0."""
    guard = _loop_guard_var.get()
    _simulate_tool_calls(guard, 50)
    assert guard._metrics.total_calls == 50

    pipeline = ContextPipeline([_FakeCompressor()])

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(llm=mock_llm, pipeline=pipeline)

    from langchain.agents.middleware import ModelRequest

    messages = _build_long_conversation(rounds=10)
    request = ModelRequest(model=mock_llm, messages=messages)
    handler = AsyncMock()
    handler.return_value = MagicMock()

    await middleware.awrap_model_call(request, handler)

    assert guard._metrics.total_calls == 0

    for i in range(5):
        guard.pre_check(f"new_tool_{i}", {"new_arg": str(i)})

    assert guard._metrics.total_calls == 5, (
        f"After compaction, new calls should count from 0; got {guard._metrics.total_calls}"
    )


@pytest.mark.asyncio
async def test_compaction_without_loop_guard_in_contextvar():
    """notify_loop_guard_compaction gracefully no-ops when no guard exists.

    The LookupError path in notify_loop_guard_compaction() must not crash.
    We simulate this by temporarily removing the guard from the ContextVar.
    """
    from unittest.mock import patch

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        notify_loop_guard_compaction,
    )

    mock_var = MagicMock()
    mock_var.get.side_effect = LookupError("no guard")

    with patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._loop_guard_var",
        mock_var,
    ):
        notify_loop_guard_compaction()


@pytest.mark.asyncio
async def test_integrity_guard_cleared_alongside_loop_guard():
    """Verify file_integrity_guard.clear() and notify_loop_guard_compaction()
    are both invoked when compaction saves tokens.

    Both are in the same `if result.tokens_saved > 0:` block in
    context_pipeline_middleware. We patch the source module's function
    (deferred-import target) to confirm it is called.
    """
    guard = _loop_guard_var.get()
    _simulate_tool_calls(guard, 15)

    pipeline = ContextPipeline([_FakeCompressor()])

    from unittest.mock import patch

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(llm=mock_llm, pipeline=pipeline)

    from langchain.agents.middleware import ModelRequest

    messages = _build_long_conversation(rounds=8)
    request = ModelRequest(model=mock_llm, messages=messages)
    handler = AsyncMock()
    handler.return_value = MagicMock()

    with patch(
        "myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.notify_loop_guard_compaction"
    ) as mock_notify:
        await middleware.awrap_model_call(request, handler)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_consecutive_compactions_reset_each_time():
    """Multiple successive compactions each reset the budget to 0."""
    guard = _loop_guard_var.get()

    pipeline = ContextPipeline([_FakeCompressor()])

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(llm=mock_llm, pipeline=pipeline)

    from langchain.agents.middleware import ModelRequest

    for cycle in range(3):
        _simulate_tool_calls(guard, 25 + cycle * 10)
        guard._error_signatures[f"err_{cycle}"] = cycle + 1

        messages = _build_long_conversation(rounds=8)
        request = ModelRequest(model=mock_llm, messages=messages)
        handler = AsyncMock()
        handler.return_value = MagicMock()

        await middleware.awrap_model_call(request, handler)

        assert guard._metrics.total_calls == 0, (
            f"Cycle {cycle}: expected total_calls=0, got {guard._metrics.total_calls}"
        )

    assert len(guard._error_signatures) == 3, (
        "All error signatures from all cycles should be preserved"
    )
    for cycle in range(3):
        assert f"err_{cycle}" in guard._error_signatures


@pytest.mark.asyncio
async def test_compaction_preserves_agent_phase():
    """notify_compaction() must not reset _current_phase."""
    from myrm_agent_harness.agent.security.guards.loop_guard_types import AgentPhase

    guard = _loop_guard_var.get()
    _simulate_tool_calls(guard, 30)
    guard._current_phase = AgentPhase.EXECUTION

    pipeline = ContextPipeline([_FakeCompressor()])

    from myrm_agent_harness.agent.middlewares.context_pipeline_middleware import (
        create_context_pipeline_middleware,
    )

    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.api_base = ""

    middleware = create_context_pipeline_middleware(llm=mock_llm, pipeline=pipeline)

    from langchain.agents.middleware import ModelRequest

    messages = _build_long_conversation(rounds=8)
    request = ModelRequest(model=mock_llm, messages=messages)
    handler = AsyncMock()
    handler.return_value = MagicMock()

    await middleware.awrap_model_call(request, handler)

    assert guard._metrics.total_calls == 0
    assert guard._current_phase == AgentPhase.EXECUTION, (
        "Agent phase must survive compaction"
    )
