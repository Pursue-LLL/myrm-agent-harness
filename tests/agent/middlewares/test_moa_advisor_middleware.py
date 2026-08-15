"""Tests for moa_advisor_middleware — skip gates and transient injection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import (
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
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _emit_ref_done

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_ref_done("ref-a", success=True, elapsed=0.1, content="x")


@pytest.mark.asyncio
async def test_emit_overlay_active_no_sink_is_noop() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _emit_overlay_active

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_overlay_active(["ref-a"])


@pytest.mark.asyncio
async def test_emit_overlay_skipped_no_sink_is_noop() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _emit_overlay_skipped

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=None,
    ):
        await _emit_overlay_skipped("budget_pressure")


def test_budget_pressure_active_tracker_none() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _budget_pressure_active

    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=None,
    ):
        assert _budget_pressure_active() is False


def test_budget_pressure_active_status_ok() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _budget_pressure_active

    tracker = MagicMock()
    tracker.last_budget_status = "ok"
    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker,
    ):
        assert _budget_pressure_active() is False


def test_budget_pressure_active_status_pressure() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _budget_pressure_active

    tracker = MagicMock()
    tracker.last_budget_status = "high"
    with patch(
        "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
        return_value=tracker,
    ):
        assert _budget_pressure_active() is True


def test_budget_pressure_active_exception_safe() -> None:
    from myrm_agent_harness.agent.middlewares.moa_advisor_middleware import _budget_pressure_active

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
