"""Tests for moa_advisor_middleware — skip gates and transient injection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
    _inject_advisor_block_cache_safe,
    create_moa_advisor_middleware,
)
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import (
    MoAOverlayConfig,
)
from myrm_agent_harness.toolkits.llms.consensus.types import ReferenceResponse


@pytest.mark.asyncio
async def test_middleware_skips_when_unattended() -> None:
    mock_llm = MagicMock()
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(),
        unattended=True,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))

    with patch(
        "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
        new_callable=AsyncMock,
    ) as run_mock:
        await middleware.awrap_model_call(request, handler)
        run_mock.assert_not_called()
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_emits_overlay_active_before_fanout() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=1, fanout="user_turn"),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    active_mock = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_active",
            active_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    active_mock.assert_awaited_once()
    assert active_mock.await_args.args[0] == ["ref-a"]
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_emits_ref_done_via_callback() -> None:
    mock_llm = MagicMock()
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=1),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))

    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Advice A",
            elapsed_seconds=0.5,
            success=True,
        ),
        ReferenceResponse(
            model="ref-b",
            content="Advice B",
            elapsed_seconds=0.6,
            success=True,
        ),
    ]
    emit_mock = AsyncMock()

    async def run_with_callback(_messages, *, on_ref_done=None):
        if on_ref_done is not None:
            for ref in refs:
                await on_ref_done(ref)
        return refs

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            side_effect=run_with_callback,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_ref_done",
            emit_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    assert emit_mock.await_count == 2
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_emits_overlay_skipped_on_budget_pressure() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="user_turn"),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    skip_mock = AsyncMock()
    run_mock = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._budget_pressure_active",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_skipped",
            skip_mock,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            run_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    skip_mock.assert_awaited_once_with("budget_pressure")
    run_mock.assert_not_called()
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_middleware_budget_skip_toast_emits_once_per_turn() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="per_iteration"),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    skip_mock = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._budget_pressure_active",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_skipped",
            skip_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)
        await middleware.awrap_model_call(request, handler)

    skip_mock.assert_awaited_once_with("budget_pressure")


@pytest.mark.asyncio
async def test_middleware_injects_advisor_block_on_success() -> None:
    mock_llm = MagicMock()
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=1),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))

    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Use incremental approach",
            elapsed_seconds=0.5,
            success=True,
        )
    ]

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=refs,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_ref_done",
            new_callable=AsyncMock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    handler.assert_awaited_once()
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "Use incremental approach" in str(last_msg.content)
    assert "hello" in str(last_msg.content)


@pytest.mark.asyncio
async def test_middleware_emits_overlay_skipped_on_insufficient_refs() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=2, fanout="user_turn"),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    skip_mock = AsyncMock()

    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Advice A",
            elapsed_seconds=0.5,
            success=True,
        ),
        ReferenceResponse(
            model="ref-b",
            content="",
            elapsed_seconds=0.6,
            success=False,
        ),
    ]

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=refs,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_skipped",
            skip_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    skip_mock.assert_awaited_once_with("insufficient_refs")
    handler.assert_awaited_once()
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert last_msg.content == "hello"


@pytest.mark.asyncio
async def test_emit_ref_done_no_sink_is_noop() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _emit_ref_done,
    )

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_ref_done("ref-a", success=True, elapsed=0.1, content="x")


@pytest.mark.asyncio
async def test_emit_overlay_active_no_sink_is_noop() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _emit_overlay_active,
    )

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_overlay_active(["ref-a"])


@pytest.mark.asyncio
async def test_emit_overlay_skipped_no_sink_is_noop() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _emit_overlay_skipped,
    )

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_overlay_skipped("budget_pressure")


def test_budget_pressure_active_tracker_none() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _budget_pressure_active,
    )

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=None,
    ):
        assert _budget_pressure_active() is False


def test_budget_pressure_active_status_ok() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _budget_pressure_active,
    )

    tracker = MagicMock()
    tracker.last_budget_status = "ok"
    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker,
    ):
        assert _budget_pressure_active() is False


def test_budget_pressure_active_status_pressure() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _budget_pressure_active,
    )

    tracker = MagicMock()
    tracker.last_budget_status = "high"
    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker,
    ):
        assert _budget_pressure_active() is True


def test_budget_pressure_active_exception_safe() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        _budget_pressure_active,
    )

    def _raise():
        raise RuntimeError("tracker down")

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        side_effect=_raise,
    ):
        assert _budget_pressure_active() is False


@pytest.mark.asyncio
async def test_injection_empty_skips_override() -> None:
    """When injection block is empty, the original request must be used."""
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        create_moa_advisor_middleware as _create,
    )

    mock_llm = MagicMock()
    middleware = _create(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=1),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Advice",
            elapsed_seconds=0.5,
            success=True,
        )
    ]

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=refs,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.build_advisor_injection_block",
            return_value="",
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    handler.assert_awaited_once()
    passed_request = handler.await_args.args[0]
    assert passed_request is request


@pytest.mark.asyncio
async def test_middleware_privacy_redaction_applied() -> None:
    """When privacy_filter is enabled and privacy_redactor is supplied, reference output must be redacted."""
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
        create_moa_advisor_middleware as _create,
    )

    mock_llm = MagicMock()
    fake_redactor = MagicMock(side_effect=lambda text: text.replace("sk-secret1234567890", "[redacted secret]"))

    middleware = _create(
        [mock_llm],
        config=MoAOverlayConfig(min_successful=1, privacy_filter="full"),
        unattended=False,
        privacy_redactor=fake_redactor,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))

    raw_content = "Here is my key: sk-secret1234567890 for testing."
    refs = [
        ReferenceResponse(
            model="ref-a",
            content=raw_content,
            elapsed_seconds=0.5,
            success=True,
        )
    ]

    with patch(
        "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
        new_callable=AsyncMock,
        return_value=refs,
    ):
        await middleware.awrap_model_call(request, handler)

    handler.assert_awaited_once()
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert "[redacted secret]" in str(last_msg.content)
    assert "sk-secret1234567890" not in str(last_msg.content)
    assert fake_redactor.called


@pytest.mark.asyncio
async def test_risk_triggered_skips_when_no_risk() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="risk_triggered"),
        unattended=False,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    run_mock = AsyncMock()

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            run_mock,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
            return_value=0,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_replan_error_summary",
            return_value={},
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    run_mock.assert_not_called()
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_risk_triggered_fires_and_records_trigger() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    mock_router = MagicMock()
    from myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router import (
        RiskTriggerDecision,
        RiskTriggerReason,
    )

    mock_router.evaluate_trigger.return_value = RiskTriggerDecision(
        should_trigger=True,
        reason=RiskTriggerReason.CONSECUTIVE_TOOL_FAILURES,
        detail="Tool failed 2 times",
        risk_score=0.9,
    )

    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="risk_triggered", min_successful=1),
        unattended=False,
        risk_router=mock_router,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    active_mock = AsyncMock()

    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Advisor advice",
            elapsed_seconds=0.2,
            success=True,
        )
    ]

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=refs,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_active",
            active_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    mock_router.evaluate_trigger.assert_called_once()
    mock_router.record_trigger.assert_called_once()
    active_mock.assert_awaited_once_with(["ref-a"], trigger_reason="consecutive_tool_failures")
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_risk_triggered_hard_timeout_silent_fallback() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    mock_router = MagicMock()
    from myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router import (
        RiskTriggerDecision,
        RiskTriggerReason,
    )

    mock_router.evaluate_trigger.return_value = RiskTriggerDecision(
        should_trigger=True,
        reason=RiskTriggerReason.CONSECUTIVE_TOOL_FAILURES,
    )

    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="risk_triggered", risk_trigger_timeout=0.01),
        unattended=False,
        risk_router=mock_router,
    )
    request = ModelRequest(messages=[HumanMessage(content="hello")], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))
    skip_mock = AsyncMock()

    async def slow_fanout(*args, **kwargs):
        await asyncio.sleep(0.5)
        return []

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            side_effect=slow_fanout,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_overlay_skipped",
            skip_mock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    skip_mock.assert_awaited_once_with("risk_trigger_timeout")
    handler.assert_awaited_once()


def test_inject_advisor_block_cache_safe_unit() -> None:
    # 1. Empty messages
    res_empty = _inject_advisor_block_cache_safe([], "advice 1")
    assert len(res_empty) == 1
    assert isinstance(res_empty[0], HumanMessage)
    assert res_empty[0].content == "advice 1"

    # 2. Trailing HumanMessage (single user turn)
    orig_human = HumanMessage(content="initial query", id="msg-0")
    res_human = _inject_advisor_block_cache_safe([orig_human], "advice 2")
    assert len(res_human) == 1
    assert isinstance(res_human[0], HumanMessage)
    assert res_human[0].id == "msg-0"
    assert res_human[0].content == "initial query\n\nadvice 2"

    # 3. Tool loop with trailing ToolMessage -> MUST NOT rewrite index 0 HumanMessage
    h0 = HumanMessage(content="initial query", id="msg-0")
    ai1 = AIMessage(content="calling tool", id="msg-1")
    t2 = ToolMessage(content="tool output", tool_call_id="call-1", id="msg-2")
    res_loop = _inject_advisor_block_cache_safe([h0, ai1, t2], "advice 3")

    assert len(res_loop) == 4
    # Prefix messages are 100% untouched for KV-cache matching
    assert res_loop[0] is h0
    assert res_loop[0].content == "initial query"
    assert res_loop[1] is ai1
    assert res_loop[2] is t2
    # Appended at tail
    assert isinstance(res_loop[3], HumanMessage)
    assert res_loop[3].content == "advice 3"

    # 4. Multimodal HumanMessage tail
    multi_human = HumanMessage(content=[{"type": "text", "text": "look at this"}], id="msg-multi")
    res_multi = _inject_advisor_block_cache_safe([multi_human], "advice 4")
    assert len(res_multi) == 1
    assert isinstance(res_multi[0], HumanMessage)
    assert isinstance(res_multi[0].content, list)
    assert len(res_multi[0].content) == 2
    assert res_multi[0].content[1] == {"type": "text", "text": "\n\nadvice 4"}


@pytest.mark.asyncio
async def test_middleware_preserves_prefix_cache_in_tool_loop() -> None:
    mock_llm = MagicMock(model_name="ref-a")
    middleware = create_moa_advisor_middleware(
        [mock_llm],
        config=MoAOverlayConfig(fanout="per_iteration"),
        unattended=False,
    )

    h0 = HumanMessage(content="Do task", id="h0")
    ai1 = AIMessage(content="", id="ai1")
    t2 = ToolMessage(content="error result", tool_call_id="c1", id="t2")
    request = ModelRequest(messages=[h0, ai1, t2], model=mock_llm)
    handler = AsyncMock(return_value=ModelResponse(result=MagicMock()))

    refs = [
        ReferenceResponse(
            model="ref-a",
            content="Try a different flag",
            elapsed_seconds=0.2,
            success=True,
        ),
    ]

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware.AdvisorFanoutRunner.run",
            new_callable=AsyncMock,
            return_value=refs,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.moa_advisor_middleware._emit_ref_done",
            new_callable=AsyncMock,
        ),
    ):
        await middleware.awrap_model_call(request, handler)

    handler.assert_awaited_once()
    passed_request = handler.await_args.args[0]
    # Verify index 0 was NOT touched (preserving prompt cache)
    assert passed_request.messages[0].content == "Do task"
    assert passed_request.messages[1] is ai1
    assert passed_request.messages[2] is t2
    # Verify tail has the advisor guidance
    assert len(passed_request.messages) == 4
    last_msg = passed_request.messages[3]
    assert isinstance(last_msg, HumanMessage)
    assert "Try a different flag" in str(last_msg.content)


