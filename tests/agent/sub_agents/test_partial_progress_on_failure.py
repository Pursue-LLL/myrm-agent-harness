"""Tests for Item #5: Subagent Partial Progress Return on Failure.

Covers:
- executor_attempt_mixin: partial_output attached to exceptions
- executor_retry_mixin: structured SubAgentResult with partial on failure paths
- Truncation logic for oversized partial output
- SUBAGENT_STOP hook firing on all failure paths
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.sub_agents.executor import SubagentExecutor
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentBudgetExceededError,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.toolkits.llms.errors.exceptions import MyrmLLMError


@pytest.fixture
def executor() -> SubagentExecutor:
    return SubagentExecutor()


@pytest.fixture
def config() -> SubagentConfig:
    return SubagentConfig(
        system_prompt="test",
        timeout_seconds=10,
        max_retries=1,
        retry_backoff_seconds=0,
        max_error_chars=100,
    )


# ---------------------------------------------------------------------------
# executor_attempt_mixin: partial_output attachment
# ---------------------------------------------------------------------------


class TestAttemptMixinPartialOutput:
    """Verify _run_single_attempt attaches partial_output to exceptions."""

    @pytest.mark.asyncio
    async def test_error_event_raises_myrm_llm_error_with_partial(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """ERROR event → MyrmLLMError with partial_output containing prior messages."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": "step1 "}
            yield {"type": AgentEventType.MESSAGE.value, "data": "step2 "}
            yield {"type": AgentEventType.ERROR.value, "error": "rate limited"}

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(MyrmLLMError) as exc_info:
                await executor._run_single_attempt(
                    task_id="partial-err",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert exc_info.value.partial_output == "step1 step2 "

    @pytest.mark.asyncio
    async def test_generic_exception_gets_partial_output_attached(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Generic exception during iteration → partial_output attached."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": "partial-data"}
            raise ConnectionError("network down")

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(ConnectionError) as exc_info:
                await executor._run_single_attempt(
                    task_id="conn-err",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert exc_info.value.partial_output == "partial-data"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_exception_with_existing_partial_output_not_overwritten(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """If exception already has partial_output, don't overwrite it."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        class CustomError(Exception):
            def __init__(self) -> None:
                super().__init__("custom")
                self.partial_output = "original-partial"

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": "new-data"}
            raise CustomError()

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(CustomError) as exc_info:
                await executor._run_single_attempt(
                    task_id="custom-err",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert exc_info.value.partial_output == "original-partial"

    @pytest.mark.asyncio
    async def test_empty_messages_yields_empty_partial_output(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """No messages accumulated before error → empty string partial_output."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.ERROR.value, "error": "immediate fail"}

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(MyrmLLMError) as exc_info:
                await executor._run_single_attempt(
                    task_id="no-msg",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert exc_info.value.partial_output == ""

    @pytest.mark.asyncio
    async def test_cancelled_error_not_caught_by_except_exception(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """CancelledError bypasses except Exception (Python semantics)."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": "before-cancel"}
            raise asyncio.CancelledError()

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(asyncio.CancelledError):
                await executor._run_single_attempt(
                    task_id="cancel",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )


# ---------------------------------------------------------------------------
# executor_retry_mixin: SubAgentResult with partial on failure
# ---------------------------------------------------------------------------


class TestRetryMixinPartialProgress:
    """Verify run_with_retry returns SubAgentResult(result=partial) on failure."""

    @pytest.mark.asyncio
    async def test_myrm_llm_error_returns_result_with_partial(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """MyrmLLMError exhausts retries → SubAgentResult with partial output."""
        exc = MyrmLLMError(error_code=FailoverReason.UNKNOWN, default_msg="rate limit")
        exc.partial_output = "partial from subagent"  # type: ignore[attr-defined]

        fire_hook_mock = AsyncMock()

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            fire_hook_mock,
        ):
            result = await executor.run_with_retry(
                task_id="llm-fail",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.FAILED
        assert result.result == "partial from subagent"
        assert "rate limit" in result.error
        fire_hook_mock.assert_called()

    @pytest.mark.asyncio
    async def test_budget_exceeded_returns_result_with_partial(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """SubagentBudgetExceededError → SubAgentResult with partial output."""
        exc = SubagentBudgetExceededError("token budget exceeded")
        exc.partial_output = "budget partial"  # type: ignore[attr-defined]

        fire_hook_mock = AsyncMock()

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            fire_hook_mock,
        ):
            result = await executor.run_with_retry(
                task_id="budget-fail",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.CANCELLED_BY_BUDGET
        assert result.result == "budget partial"
        fire_hook_mock.assert_called()

    @pytest.mark.asyncio
    async def test_generic_exception_returns_result_with_partial(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Generic Exception exhausts retries → SubAgentResult with partial output."""
        exc = RuntimeError("unexpected crash")
        exc.partial_output = "runtime partial"  # type: ignore[attr-defined]

        fire_hook_mock = AsyncMock()

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            fire_hook_mock,
        ):
            result = await executor.run_with_retry(
                task_id="runtime-fail",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.FAILED
        assert result.result == "runtime partial"
        assert "RuntimeError" in result.error
        fire_hook_mock.assert_called()

    @pytest.mark.asyncio
    async def test_partial_output_truncation(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Partial output exceeding max_error_chars*2 is truncated."""
        long_partial = "x" * 500  # config.max_error_chars=100, threshold=200
        exc = MyrmLLMError(error_code=FailoverReason.UNKNOWN, default_msg="err")
        exc.partial_output = long_partial  # type: ignore[attr-defined]

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="trunc",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.result is not None
        assert len(result.result) < 500
        assert result.result.endswith("\n…[truncated]")
        assert result.result.startswith("x" * 200)

    @pytest.mark.asyncio
    async def test_empty_partial_output_not_truncated(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Empty partial output remains empty (no truncation marker)."""
        exc = SubagentBudgetExceededError("budget")
        exc.partial_output = ""  # type: ignore[attr-defined]

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="empty",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.result == ""

    @pytest.mark.asyncio
    async def test_no_partial_output_attr_treated_as_empty(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Exception without partial_output attr → result is empty string."""
        exc = SubagentBudgetExceededError("budget exceeded")
        # deliberately do NOT set exc.partial_output

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="no-attr",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.result == ""

    @pytest.mark.asyncio
    async def test_subagent_stop_hook_fired_on_myrm_llm_error(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """SUBAGENT_STOP hook fires with correct payload on MyrmLLMError."""
        exc = MyrmLLMError(error_code=FailoverReason.UNKNOWN, default_msg="err")
        exc.partial_output = "hook test"  # type: ignore[attr-defined]

        fire_hook_mock = AsyncMock()

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            fire_hook_mock,
        ):
            result = await executor.run_with_retry(
                task_id="hook-test",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        hook_calls = fire_hook_mock.call_args_list
        stop_calls = [
            c for c in hook_calls
            if len(c.args) >= 1 and "stop" in str(c.args[0]).lower()
        ]
        assert len(stop_calls) >= 1
        stop_payload = stop_calls[-1].args[1]
        assert stop_payload["task_id"] == "hook-test"
        assert stop_payload["success"] is False

    @pytest.mark.asyncio
    async def test_budget_exceeded_truncation(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """SubagentBudgetExceededError with oversized partial → truncated."""
        long_partial = "B" * 300
        exc = SubagentBudgetExceededError("over budget")
        exc.partial_output = long_partial  # type: ignore[attr-defined]

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="budget-trunc",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.result is not None
        assert result.result.endswith("\n…[truncated]")
        assert len(result.result) == 200 + len("\n…[truncated]")


# ---------------------------------------------------------------------------
# Edge cases: retry behavior, context recovery, non-string data, TimeoutError
# ---------------------------------------------------------------------------


class TestRetryPartialOutputBehavior:
    """Verify partial output correctness across multiple retries."""

    @pytest.mark.asyncio
    async def test_retry_uses_last_attempt_partial_not_first(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """When retries exhaust, the returned partial is from the LAST attempt."""
        config_retry = SubagentConfig(
            system_prompt="test",
            timeout_seconds=10,
            max_retries=2,
            retry_backoff_seconds=0,
            max_error_chars=200,
        )

        call_count = {"n": 0}

        async def side_effect(*args: object, **kwargs: object) -> None:
            call_count["n"] += 1
            exc = MyrmLLMError(error_code=FailoverReason.UNKNOWN, default_msg="err")
            exc.partial_output = f"attempt-{call_count['n']}-partial"  # type: ignore[attr-defined]
            raise exc

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=side_effect
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="retry-last",
                agent_type="worker",
                task_description="task",
                config=config_retry,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        assert result.result == "attempt-2-partial"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_retry_success_after_failure_returns_normal(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """First attempt fails with partial, second succeeds → normal result returned."""
        from myrm_agent_harness.agent.sub_agents.types import SubAgentResult as SAR

        config_retry = SubagentConfig(
            system_prompt="test",
            timeout_seconds=10,
            max_retries=2,
            retry_backoff_seconds=0,
        )

        call_count = {"n": 0}

        async def side_effect(*args: object, **kwargs: object) -> SAR:
            call_count["n"] += 1
            if call_count["n"] == 1:
                exc = MyrmLLMError(error_code=FailoverReason.UNKNOWN, default_msg="err")
                exc.partial_output = "partial-from-fail"  # type: ignore[attr-defined]
                raise exc
            return SAR(
                success=True,
                task_id="retry-ok",
                agent_type="worker",
                result="final-success-result",
                completed_at=0.0,
                status=SubAgentStatus.COMPLETED,
            )

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=side_effect
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="retry-ok",
                agent_type="worker",
                task_description="task",
                config=config_retry,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is True
        assert result.result == "final-success-result"
        assert "partial" not in result.result

    @pytest.mark.asyncio
    async def test_timeout_error_returns_partial(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """TimeoutError with partial_output → SubAgentResult includes partial."""
        exc = TimeoutError("request timed out")
        exc.partial_output = "timeout-partial-data"  # type: ignore[attr-defined]

        with patch.object(
            executor, "_run_single_attempt", new_callable=AsyncMock, side_effect=exc
        ), patch(
            "myrm_agent_harness.agent.hooks.executor.fire_hook",
            AsyncMock(),
        ):
            result = await executor.run_with_retry(
                task_id="timeout",
                agent_type="worker",
                task_description="task",
                config=config,
                context={},
                tool_registry_getter=lambda: [],
                start_time=0.0,
                parent_agent=MagicMock(),
                cancel_flags={},
                children_agents={},
                children_steering={},
            )

        assert result.success is False
        assert result.status == SubAgentStatus.TIMED_OUT
        assert result.result == "timeout-partial-data"
        assert "Timeout" in result.error


class TestAttemptMixinEdgeCases:
    """Edge cases for _run_single_attempt partial output collection."""

    @pytest.mark.asyncio
    async def test_non_string_message_data_converted_to_str(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """MESSAGE event with non-string data → str() conversion in partial."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": 42}
            yield {"type": AgentEventType.MESSAGE.value, "data": {"key": "val"}}
            yield {"type": AgentEventType.ERROR.value, "error": "fail"}

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(MyrmLLMError) as exc_info:
                await executor._run_single_attempt(
                    task_id="non-str",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert "42" in exc_info.value.partial_output
            assert "{'key': 'val'}" in exc_info.value.partial_output

    @pytest.mark.asyncio
    async def test_context_restored_after_exception(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """After exception, is_subagent context is restored to False."""
        from myrm_agent_harness.agent.middlewares._session_context import get_is_subagent

        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": "x"}
            raise ValueError("crash")

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(ValueError):
                await executor._run_single_attempt(
                    task_id="ctx-test",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

        assert get_is_subagent() is False

    @pytest.mark.asyncio
    async def test_partial_output_with_unicode_and_special_chars(
        self, executor: SubagentExecutor, config: SubagentConfig
    ) -> None:
        """Partial output with unicode/special chars is handled correctly."""
        parent_agent = MagicMock()
        parent_agent._subagent_manager = None
        parent_agent._last_context = {}

        child_agent = MagicMock()
        special_content = "分析结果：✅ 成功\n\t数据: «value»\x00null-byte"

        async def mock_run(**kwargs: object):
            yield {"type": AgentEventType.MESSAGE.value, "data": special_content}
            yield {"type": AgentEventType.ERROR.value, "error": "fail"}

        child_agent.run = mock_run

        with patch(
            "myrm_agent_harness.agent.sub_agents.executor_attempt_mixin.build_child_agent",
            return_value=child_agent,
        ):
            with pytest.raises(MyrmLLMError) as exc_info:
                await executor._run_single_attempt(
                    task_id="unicode",
                    agent_type="worker",
                    task_description="task",
                    config=config,
                    context={},
                    tool_registry_getter=lambda: [],
                    start_time=0.0,
                    parent_tracker=None,
                    parent_taint=MagicMock(),
                    parent_agent=parent_agent,
                    cancel_flags={},
                    children_agents={},
                    fire_hook=AsyncMock(),
                    hook_event_cls=MagicMock(),
                )

            assert exc_info.value.partial_output == special_content
