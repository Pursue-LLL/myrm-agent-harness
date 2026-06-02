from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import _tool_interceptor_middleware_inner


@pytest.mark.asyncio
async def test_tool_interceptor_coverage_various_blocks():
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )
    async def dummy_handler(req):
        return ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_pre:
        # Mock pre-hook block
        mock_pre_result = MagicMock()
        mock_pre_result.blocked = True
        mock_pre_result.reason = "test block"
        mock_pre_result.updated_input = None
        mock_pre.return_value = mock_pre_result

        res = await _tool_interceptor_middleware_inner(request, dummy_handler)
        assert "Blocked by hook: test block" in res.content

@pytest.mark.asyncio
async def test_tool_interceptor_coverage_estop():
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )
    async def dummy_handler(req):
        return ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook", return_value=MagicMock(blocked=False, updated_input=None)), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop") as mock_estop:
        mock_estop_state = MagicMock()
        mock_estop_state.level = "KILL_ALL"
        mock_estop_state.reason = "test estop"
        mock_estop.return_value = mock_estop_state

        res = await _tool_interceptor_middleware_inner(request, dummy_handler)
        assert "E-Stop active" in res.content

@pytest.mark.asyncio
async def test_tool_interceptor_coverage_loop_break():
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )
    async def dummy_handler(req):
        return ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook", return_value=MagicMock(blocked=False, updated_input=None)), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop", return_value=None), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard") as mock_guard:

        mock_guard_inst = MagicMock()
        mock_verdict = MagicMock()
        from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction
        mock_verdict.action = LoopAction.BREAK
        mock_verdict.reason = "loop break reason"
        mock_verdict.backoff_hint = "hint"
        mock_guard_inst.pre_check.return_value = mock_verdict
        mock_guard.return_value = mock_guard_inst

        res = await _tool_interceptor_middleware_inner(request, dummy_handler)
        assert "loop break reason" in res.content

@pytest.mark.asyncio
async def test_tool_interceptor_coverage_pii_block():
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )
    async def dummy_handler(req):
        return ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook", return_value=MagicMock(blocked=False, updated_input=None)), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop", return_value=None), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard") as mock_guard, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_tool_params_pii", return_value="pii block"):

        mock_guard_inst = MagicMock()
        mock_verdict = MagicMock()
        from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction
        mock_verdict.action = LoopAction.ALLOW
        mock_guard_inst.pre_check.return_value = mock_verdict
        mock_guard.return_value = mock_guard_inst

        res = await _tool_interceptor_middleware_inner(request, dummy_handler)
        assert "pii block" in res.content


@pytest.mark.asyncio
async def test_build_hook_failure_result():
    from unittest.mock import MagicMock

    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares._tool_helpers import (
        build_hook_failure_result as _build_hook_failure_result,
    )

    result = ToolMessage(content="original output", name="test_tool", tool_call_id="call_123")

    # Create a mock post_hook_result
    mock_hook_result = MagicMock()
    mock_hook_result.reason = "hook overall reason"

    mock_res1 = MagicMock()
    mock_res1.blocked = True
    mock_res1.output = "detail 1"

    mock_res2 = MagicMock()
    mock_res2.blocked = False
    mock_res2.success = False
    mock_res2.output = None
    mock_res2.reason = "detail 2"

    mock_hook_result.results = [mock_res1, mock_res2]

    error_msg = _build_hook_failure_result(result, mock_hook_result, "test_tool", "call_123", "original output")

    assert "detail 1" in error_msg.content
    assert "detail 2" in error_msg.content
    assert "original output" in error_msg.content
    assert error_msg.status == "error"

@pytest.mark.asyncio
async def test_handle_cancellation():
    import asyncio
    import time

    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_cancellation as _handle_cancellation,
    )

    e = asyncio.CancelledError("timeout occurred")
    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire, \
         patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink") as mock_sink:

        mock_sink_inst = AsyncMock()
        mock_sink.return_value = mock_sink_inst

        res = await _handle_cancellation(e, "test_tool", "call_123", {}, time.time())
        assert "timeout" in res.content
        assert mock_fire.call_count == 1
        assert mock_sink_inst.emit.call_count == 1

@pytest.mark.asyncio
async def test_handle_execution_error():
    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_execution_error as _handle_execution_error,
    )

    e = ValueError("something bad")
    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire:
        res = await _handle_execution_error(e, "test_tool", "call_123", {})
        assert "ValueError" in res.content or "something bad" in res.content
        assert mock_fire.call_count == 1

    @pytest.mark.asyncio
    async def test_run_post_call_guards():
        from langchain_core.messages import ToolMessage

        from myrm_agent_harness.agent.middlewares._tool_guards import run_post_call_guards as _run_post_call_guards

        result = ToolMessage(content="test output", name="test_tool", tool_call_id="call_123")

        with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire, \
             patch("myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii") as mock_pii, \
             patch("myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker"):

            mock_hook_result = MagicMock()
            mock_hook_result.blocked = False
            mock_fire.return_value = mock_hook_result

            mock_pii.return_value = (result, "test output")

            mock_guard_inst = MagicMock()
            mock_guard_inst.record_result.return_value = MagicMock(action="allow")

            mock_loop_verdict = MagicMock()
            mock_steering_token = MagicMock()

            res = await _run_post_call_guards(result, "test_tool", "call_123", {}, mock_guard_inst, mock_loop_verdict, mock_steering_token)
            assert res == result

@pytest.mark.asyncio
async def test_emit_hook_failure_event():
    from myrm_agent_harness.agent.middlewares._tool_helpers import emit_hook_failure_event as _emit_hook_failure_event

    mock_hook_result = MagicMock()
    mock_hook_result.reason = "test reason"

    mock_res1 = MagicMock()
    mock_res1.blocked = True
    mock_res1.hook_name = "hook1"
    mock_res1.output = "output1"
    mock_res1.reason = "reason1"

    mock_hook_result.results = [mock_res1]

    mock_agent_event_type = MagicMock()
    mock_agent_event_type.HOOK_FAILED.value = "hook_failed"

    with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink") as mock_sink:
        mock_sink_inst = AsyncMock()
        mock_sink.return_value = mock_sink_inst

        await _emit_hook_failure_event("test_tool", mock_hook_result, mock_agent_event_type)

        assert mock_sink_inst.emit.call_count == 1

    def test_check_circuit_breaker():
        from myrm_agent_harness.agent.middlewares._tool_guards import _check_circuit_breaker

        with patch("myrm_agent_harness.agent.middlewares._tool_guards.get_terminal_errors") as mock_cb:
            mock_cb_inst = MagicMock()
            mock_cb_inst.get_all.return_value = {"any": "error"}
            mock_cb.return_value = mock_cb_inst

            res = _check_circuit_breaker("test_tool", "call_123")
            assert res is not None
            assert "circuit breaker" in res.content.lower()

def test_record_skill_execution():
    from myrm_agent_harness.agent.middlewares._skill_failure_tracking import (
        track_skill_execution as _track_skill_execution,
    )

    with patch("myrm_agent_harness.agent._skill_agent_context.get_loaded_skills") as mock_skills, \
         patch("myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration") as mock_evo:

        mock_skill = MagicMock()
        mock_skill.name = "test_tool"
        mock_skill.storage_skill_id = "skill_123"
        mock_skills.return_value = [mock_skill]

        mock_evo_inst = MagicMock()
        mock_evo.return_value = mock_evo_inst

        _track_skill_execution("test_tool", tool_call_id="call_123", tool_args={}, success=True, error_message="")
        mock_evo_inst.record_execution.assert_called_once()

@pytest.mark.asyncio
async def test_run_pre_call_guards_blocks():
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from myrm_agent_harness.agent.middlewares._tool_guards import run_pre_call_guards as _run_pre_call_guards

    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire:
        mock_hook_result = MagicMock()
        mock_hook_result.blocked = True
        mock_hook_result.reason = "test reason"
        mock_fire.return_value = mock_hook_result

        res = await _run_pre_call_guards(request, "test_tool", "call_123", {})
        assert "test reason" in res.content

@pytest.mark.asyncio
async def test_run_pre_call_guards_updated_input():
    from langgraph.prebuilt.tool_node import ToolCallRequest

    from myrm_agent_harness.agent.middlewares._tool_guards import run_pre_call_guards as _run_pre_call_guards

    request = ToolCallRequest(
        tool_call={"name": "test_tool", "id": "call_123", "args": {"old": 1}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock()
    )

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards._check_circuit_breaker", return_value=False), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop", return_value=None), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard") as mock_guard, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_tool_params_pii", return_value=None):

        mock_hook_result = MagicMock()
        mock_hook_result.blocked = False
        mock_hook_result.updated_input = {"new": 2}
        mock_fire.return_value = mock_hook_result

        mock_guard_inst = MagicMock()
        mock_verdict = MagicMock()
        from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction
        mock_verdict.action = LoopAction.ALLOW
        mock_guard_inst.pre_check.return_value = mock_verdict
        mock_guard.return_value = mock_guard_inst

        await _run_pre_call_guards(request, "test_tool", "call_123", {"old": 1})
        assert request.tool_call["args"] == {"new": 2}

def test_get_loop_guard():
    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        _loop_guard_var,
        get_loop_guard,
    )

    # Clear context var if set
    token = None
    try:
        _loop_guard_var.get()
        token = _loop_guard_var.set(None)
    except LookupError:
        pass

    try:
        # Should create new
        guard1 = get_loop_guard()
        assert guard1 is not None

        # Should return existing
        guard2 = get_loop_guard()
        assert guard1 is guard2
    finally:
        if token:
            _loop_guard_var.reset(token)

def test_reset_loop_guard():
    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        get_loop_guard,
        reset_loop_guard,
    )

    # Test with existing guard
    guard = get_loop_guard()
    with patch.object(guard, 'reset') as mock_reset:
        reset_loop_guard()
        mock_reset.assert_called_once()

    # Test with no guard
    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._loop_guard_var") as mock_var:
        mock_var.get.side_effect = LookupError
        reset_loop_guard() # Should pass silently

@pytest.mark.asyncio
async def test_tool_interceptor_middleware_success():
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import tool_interceptor_middleware

    request = MagicMock()
    request.tool_call = {"name": "test_tool", "args": {}, "id": "call_123"}
    result_msg = ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    async def mock_handler(req):
        return result_msg

    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._tool_interceptor_middleware_inner", return_value=result_msg), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._track_skill_execution") as mock_track, \
         patch("myrm_agent_harness.observability.metrics.registry.metrics_registry") as mock_registry:

        mock_registry.enabled = True

        # We need to unwrap the decorator for testing, or just call it directly.
        # Since it's decorated with @wrap_tool_call, we might need to call the underlying function.
        # Let's try calling it directly first.
        # Wait, @wrap_tool_call returns a Runnable. We can invoke it or just call the __wrapped__ function.

        # Actually, if we just call the __wrapped__ function:
        res = await tool_interceptor_middleware.awrap_tool_call(request, mock_handler)
        assert res == result_msg
        mock_track.assert_called_once_with("test_tool", tool_call_id="call_123", tool_args={}, success=True, error_message="", error_category=None, loop_kind=None)
        mock_registry.record_tool_call.assert_called_once_with(agent_id="base_agent", tool_name="test_tool", status="success")

@pytest.mark.asyncio
async def test_tool_interceptor_middleware_error():

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import tool_interceptor_middleware

    request = MagicMock()
    request.tool_call = {"name": "test_tool", "args": {}, "id": "call_123"}

    async def mock_handler(req):
        raise ValueError("test error")

    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._tool_interceptor_middleware_inner", side_effect=ValueError("test error")), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware._track_skill_execution") as mock_track, \
         patch("myrm_agent_harness.observability.metrics.registry.metrics_registry") as mock_registry:

        mock_registry.enabled = True

        with pytest.raises(ValueError):
            await tool_interceptor_middleware.awrap_tool_call(request, mock_handler)

        mock_track.assert_called_once_with("test_tool", tool_call_id="call_123", tool_args={}, success=False, error_message="test error", error_category=None, loop_kind=None)
        mock_registry.record_tool_call.assert_called_once_with(agent_id="base_agent", tool_name="test_tool", status="error")

def test_check_circuit_breaker_network():
    from myrm_agent_harness.agent.middlewares._tool_guards import _check_circuit_breaker

    with patch("myrm_agent_harness.agent.middlewares._tool_guards.get_terminal_errors") as mock_cb:
        mock_cb_inst = MagicMock()
        mock_cb_inst.get_all.return_value = {"network_blocked": "error"}
        mock_cb.return_value = mock_cb_inst

        res = _check_circuit_breaker("web_search", "call_123")
        assert res is not None
        assert "network_blocked" in res.content.lower()

        res_allow = _check_circuit_breaker("safe_tool", "call_123")
        assert res_allow is None

def test_check_circuit_breaker_write():
    from myrm_agent_harness.agent.middlewares._tool_guards import _check_circuit_breaker

    with patch("myrm_agent_harness.agent.middlewares._tool_guards.get_terminal_errors") as mock_cb:
        mock_cb_inst = MagicMock()
        mock_cb_inst.get_all.return_value = {"sandbox_ro": "error"}
        mock_cb.return_value = mock_cb_inst

        res = _check_circuit_breaker("file_write", "call_123")
        assert res is not None
        assert "sandbox_ro" in res.content.lower()

        res_allow = _check_circuit_breaker("safe_tool", "call_123")
        assert res_allow is None

@pytest.mark.asyncio
async def test_run_post_call_guards_full():
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares._tool_guards import run_post_call_guards as _run_post_call_guards
    from myrm_agent_harness.agent.security.guards.context_budget import BudgetAction
    from myrm_agent_harness.agent.security.guards.loop_guard_types import LoopAction

    result = ToolMessage(content="  ", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii") as mock_pii, \
         patch("myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker"), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.get_context_budget_guard") as mock_budget, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.run_content_validation") as mock_validation, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.emit_hook_failure_event"):

        mock_hook_result = MagicMock()
        mock_hook_result.blocked = True
        mock_hook_result.reason = "hook blocked"
        mock_hook_result.results = [MagicMock(blocked=True, success=False, output=None, reason="hook blocked")]
        mock_fire.return_value = mock_hook_result

        mock_pii.return_value = (result, "(no output)")

        mock_budget_inst = MagicMock()
        mock_budget_verdict = MagicMock()
        mock_budget_verdict.action = BudgetAction.TRUNCATED
        mock_budget_verdict.content = "truncated"
        mock_budget_verdict.reason = "too long"
        mock_budget_inst.check_and_truncate.return_value = mock_budget_verdict
        mock_budget.return_value = mock_budget_inst

        mock_validation.return_value = MagicMock(reason="poisoned")

        with patch("myrm_agent_harness.agent.middlewares._tool_guards.apply_validation_result", return_value=result):
            mock_guard_inst = MagicMock()
            mock_post_verdict = MagicMock()
            mock_post_verdict.action = LoopAction.WARN
            mock_post_verdict.reason = "looping"
            mock_guard_inst.record_result.return_value = mock_post_verdict

            mock_loop_verdict = MagicMock()
            mock_steering_token = MagicMock()
            mock_steering_token.has_pending = True

            mock_freq_guard = MagicMock()
            mock_freq_verdict = MagicMock()

            res = await _run_post_call_guards(result, "bash_code_execute_tool", "call_123", {}, mock_guard_inst, mock_loop_verdict, mock_freq_guard, mock_freq_verdict, mock_steering_token)

            # Since hook blocked is True, it returns the hook blocked message
            assert "hook blocked" in res.content

@pytest.mark.asyncio
async def test_run_post_call_guards_budget_persisted():
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares._tool_guards import run_post_call_guards as _run_post_call_guards
    from myrm_agent_harness.agent.security.guards.context_budget import BudgetAction

    result = ToolMessage(content="test", name="test_tool", tool_call_id="call_123")

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_fire, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.check_tool_result_pii") as mock_pii, \
         patch("myrm_agent_harness.agent.security.guards.taint_tracker.get_taint_tracker"), \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.get_context_budget_guard") as mock_budget, \
         patch("myrm_agent_harness.agent.middlewares._tool_guards.run_content_validation", return_value=None):

        mock_hook_result = MagicMock()
        mock_hook_result.blocked = False
        mock_fire.return_value = mock_hook_result

        mock_pii.side_effect = lambda res, text, name: (res, text)

        mock_budget_inst = MagicMock()
        mock_budget_verdict = MagicMock()
        mock_budget_verdict.action = BudgetAction.PERSISTED
        mock_budget_verdict.content = "persisted"
        mock_budget_verdict.reason = "too long"
        mock_budget_verdict.persisted_path = "/tmp/test"
        mock_budget_inst.check_and_truncate.return_value = mock_budget_verdict
        mock_budget.return_value = mock_budget_inst

        mock_guard_inst = MagicMock()
        mock_guard_inst.record_result.return_value = MagicMock(action="allow")

        mock_loop_verdict = MagicMock()
        mock_loop_verdict.action = "allow"

        mock_freq_guard = MagicMock()
        mock_freq_verdict = MagicMock()

        res = await _run_post_call_guards(result, "test_tool", "call_123", {}, mock_guard_inst, mock_loop_verdict, mock_freq_guard, mock_freq_verdict, None)
        assert res.content == "persisted"

@pytest.mark.asyncio
async def test_tool_interceptor_middleware_inner_success():
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import _tool_interceptor_middleware_inner

    request = MagicMock()
    request.tool_call = {"name": "test_tool", "args": {}, "id": "call_123"}
    result_msg = ToolMessage(content="success", name="test_tool", tool_call_id="call_123")

    async def mock_handler(req):
        return result_msg

    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.run_pre_call_guards") as mock_pre, \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.execute_with_retry", return_value=result_msg), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.run_post_call_guards", return_value=result_msg), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.push_tool_context"), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.pop_tool_context"), \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_token_tracker") as mock_tracker, \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_event_logger") as mock_logger, \
         patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.emit_tool_heartbeat"):

        mock_pre_result = MagicMock()
        mock_pre_result.blocked = False
        mock_pre_result.loop_guard = MagicMock()
        mock_pre_result.loop_verdict = MagicMock()
        mock_pre_result.steering_token = MagicMock()
        mock_pre.return_value = mock_pre_result

        mock_tracker_inst = MagicMock()
        mock_tool_usage = MagicMock()
        mock_tool_usage.total_tokens = 100
        mock_tracker_inst.tool_usage = {"test_tool": mock_tool_usage}
        mock_tracker.return_value = mock_tracker_inst

        mock_logger_inst = AsyncMock()
        mock_logger.return_value = mock_logger_inst

        res = await _tool_interceptor_middleware_inner(request, mock_handler)
        assert res == result_msg

        # Simulate token usage increase
        mock_tool_usage.total_tokens = 150

        # Wait, the finally block executes before return.
        # But we didn't change total_tokens during execution.
        # Let's just assert it runs without error.

@pytest.mark.asyncio
async def test_tool_interceptor_middleware_inner_blocked():
    from langchain_core.messages import ToolMessage

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import _tool_interceptor_middleware_inner

    request = MagicMock()
    request.tool_call = {"name": "test_tool", "args": {}, "id": "call_123"}
    blocked_msg = ToolMessage(content="blocked", name="test_tool", tool_call_id="call_123")

    async def mock_handler(req):
        return None

    with patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.run_pre_call_guards") as mock_pre:
        mock_pre.return_value = blocked_msg

        res = await _tool_interceptor_middleware_inner(request, mock_handler)
        assert res == blocked_msg

@pytest.mark.asyncio
async def test_emit_tool_heartbeat():
    import asyncio

    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        emit_tool_heartbeat as _emit_tool_heartbeat,
    )

    with patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink") as mock_sink, \
         patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()]):

        mock_sink_inst = AsyncMock()
        mock_sink.return_value = mock_sink_inst

        with pytest.raises(asyncio.CancelledError):
            await _emit_tool_heartbeat("test_tool", "call_123", 0.0)

        mock_sink_inst.emit.assert_called_once()

@pytest.mark.asyncio
async def test_handle_cancellation_reasons():
    import asyncio
    import time

    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_cancellation as _handle_cancellation,
    )

    with patch("myrm_agent_harness.agent.hooks.executor.fire_hook"), \
         patch("myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink"):

        # user
        e_user = asyncio.CancelledError("user requested")
        res_user = await _handle_cancellation(e_user, "test_tool", "call_123", {}, time.time())
        assert "user_cancelled" in res_user.content

        # session
        e_session = asyncio.CancelledError("session closed")
        res_session = await _handle_cancellation(e_session, "test_tool", "call_123", {}, time.time())
        assert "session_ended" in res_session.content

        # default
        e_default = asyncio.CancelledError()
        res_default = await _handle_cancellation(e_default, "test_tool", "call_123", {}, time.time())
        assert "user_cancelled" in res_default.content

@pytest.mark.asyncio
async def test_handle_execution_error_graph_interrupt():
    from langgraph.errors import GraphInterrupt

    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_execution_error as _handle_execution_error,
    )

    e = GraphInterrupt("interrupt")
    with pytest.raises(GraphInterrupt):
        await _handle_execution_error(e, "test_tool", "call_123", {})


@pytest.mark.asyncio
async def test_pre_check_tool_stuck_triggers_interrupt_via_pre_call_guards():
    """ToolStuckException raised by pre_check must trigger interrupt before tool execution."""
    from langgraph.errors import GraphInterrupt

    from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
    from myrm_agent_harness.agent.middlewares._tool_guards import run_pre_call_guards as _run_pre_call_guards

    request = ToolCallRequest(
        tool_call={"name": "bash_tool", "id": "call_pre_check", "args": {"cmd": "echo"}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock(),
    )

    mock_guard = MagicMock()
    mock_guard.pre_check.side_effect = ToolStuckException(
        "TOOL_STUCK_EXCEPTION: Iteration budget exhausted (48 tool calls)"
    )

    with (
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_hook,
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard", return_value=mock_guard),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_token_tracker", return_value=None),
        patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop", return_value=None),
        patch("myrm_agent_harness.agent.middlewares._tool_guards._check_circuit_breaker", return_value=None),
        patch("langgraph.types.interrupt") as mock_interrupt,
    ):
        mock_hook_result = MagicMock()
        mock_hook_result.blocked = False
        mock_hook_result.updated_input = None
        mock_hook.return_value = mock_hook_result

        mock_interrupt.side_effect = GraphInterrupt(
            {"action_type": "tool_stuck", "tool_name": "bash_tool"}
        )

        with pytest.raises(GraphInterrupt):
            await _run_pre_call_guards(request, "bash_tool", "call_pre_check", {"cmd": "echo"})

        mock_interrupt.assert_called_once()
        payload = mock_interrupt.call_args[0][0]
        assert payload["action_type"] == "tool_stuck"
        assert "48 tool calls" in payload["error_message"]


@pytest.mark.asyncio
async def test_pre_check_tool_stuck_fallthrough_returns_error_msg():
    """If interrupt() returns in pre_check path, return error ToolMessage."""
    from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
    from myrm_agent_harness.agent.middlewares._tool_guards import run_pre_call_guards as _run_pre_call_guards

    request = ToolCallRequest(
        tool_call={"name": "bash_tool", "id": "call_pre_ft", "args": {"cmd": "echo"}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock(),
    )

    mock_guard = MagicMock()
    mock_guard.pre_check.side_effect = ToolStuckException(
        "TOOL_STUCK_EXCEPTION: stuck"
    )

    with (
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook") as mock_hook,
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_loop_guard", return_value=mock_guard),
        patch("myrm_agent_harness.agent.middlewares.tool_interceptor_middleware.get_token_tracker", return_value=None),
        patch("myrm_agent_harness.agent.middlewares._tool_guards.check_estop", return_value=None),
        patch("myrm_agent_harness.agent.middlewares._tool_guards._check_circuit_breaker", return_value=None),
        patch("langgraph.types.interrupt", return_value=None),
    ):
        mock_hook_result = MagicMock()
        mock_hook_result.blocked = False
        mock_hook_result.updated_input = None
        mock_hook.return_value = mock_hook_result

        result = await _run_pre_call_guards(request, "bash_tool", "call_pre_ft", {"cmd": "echo"})
        assert isinstance(result, ToolMessage)
        assert "TOOL_STUCK_EXCEPTION" in result.content


@pytest.mark.asyncio
async def test_handle_execution_error_tool_stuck_triggers_interrupt():
    """ToolStuckException must trigger GraphInterrupt via interrupt()."""
    from langgraph.errors import GraphInterrupt

    from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_execution_error as _handle_execution_error,
    )

    e = ToolStuckException("TOOL_STUCK_EXCEPTION: budget exhausted (48 calls)")

    with patch("langgraph.types.interrupt") as mock_interrupt:
        mock_interrupt.side_effect = GraphInterrupt(
            {"action_type": "tool_stuck", "tool_name": "bash_tool"}
        )

        with pytest.raises(GraphInterrupt):
            await _handle_execution_error(e, "bash_tool", "call_999", {"cmd": "echo"})

        mock_interrupt.assert_called_once()
        call_payload = mock_interrupt.call_args[0][0]
        assert call_payload["action_type"] == "tool_stuck"
        assert call_payload["tool_name"] == "bash_tool"
        assert "TOOL_STUCK_EXCEPTION" in call_payload["error_message"]


@pytest.mark.asyncio
async def test_handle_execution_error_tool_stuck_fallthrough_if_interrupt_returns():
    """If interrupt() returns (checkpoint mode), _handle_execution_error still returns ToolMessage."""
    from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException
    from myrm_agent_harness.agent.middlewares._tool_execution_lifecycle import (
        handle_execution_error as _handle_execution_error,
    )

    e = ToolStuckException("TOOL_STUCK_EXCEPTION: stuck")

    with patch("langgraph.types.interrupt", return_value=None):
        with patch("myrm_agent_harness.agent.hooks.executor.fire_hook"):
            result = await _handle_execution_error(e, "bash_tool", "call_999", {})
            assert "ToolStuckException" in result.content or "TOOL_STUCK_EXCEPTION" in result.content
