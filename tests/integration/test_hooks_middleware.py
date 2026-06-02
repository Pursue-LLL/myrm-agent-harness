"""Hooks middleware integration tests — new API.

Tests the integration of hooks with tool_interceptor_middleware,
stream_executor, and sub_agents/manager via fire_hook.
"""

import pytest

from myrm_agent_harness.agent.hooks import (
    EMPTY_RESULT,
    CallableHookDefinition,
    HookEvent,
    HookExecutor,
    HookRegistry,
    HookResult,
    fire_hook,
    set_hook_executor,
)


@pytest.fixture(autouse=True)
def _cleanup_executor():
    """Ensure ContextVar is reset between tests."""
    set_hook_executor(None)
    yield
    set_hook_executor(None)


class TestFireHookIntegration:
    @pytest.mark.asyncio
    async def test_fire_hook_no_executor(self):
        result = await fire_hook(HookEvent.SESSION_START, {"session_id": "s1"})
        assert result is EMPTY_RESULT

    @pytest.mark.asyncio
    async def test_fire_hook_with_executor(self):
        call_log: list[str] = []

        async def log_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_log.append(event)
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CallableHookDefinition(fn=log_hook))
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(HookEvent.SESSION_START, {"session_id": "s1"})
        assert len(call_log) == 1
        assert call_log[0] == HookEvent.SESSION_START.value
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_pre_tool_use_blocking(self):
        async def deny_hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(
                hook_type="callable",
                success=False,
                blocked=True,
                reason="Policy violation",
            )

        registry = HookRegistry()
        registry.register(
            HookEvent.PRE_TOOL_USE,
            CallableHookDefinition(fn=deny_hook, block_on_failure=True),
        )
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
        )
        assert result.blocked
        assert "Policy violation" in result.reason

    @pytest.mark.asyncio
    async def test_post_tool_use_does_not_block(self):
        async def observe_hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(hook_type="callable", success=True, output="logged")

        registry = HookRegistry()
        registry.register(HookEvent.POST_TOOL_USE, CallableHookDefinition(fn=observe_hook))
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "Read", "tool_output": "file content"},
        )
        assert not result.blocked
        assert result.results[0].output == "logged"

    @pytest.mark.asyncio
    async def test_multiple_hooks_all_run(self):
        call_order: list[str] = []

        async def hook_a(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("a")
            return HookResult(hook_type="callable", success=True)

        async def hook_b(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("b")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_END, CallableHookDefinition(fn=hook_a))
        registry.register(HookEvent.SESSION_END, CallableHookDefinition(fn=hook_b))
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(HookEvent.SESSION_END, {})
        assert len(result.results) == 2
        assert set(call_order) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_crash(self):
        async def bad_hook(event: str, payload: dict[str, object]) -> HookResult:
            raise RuntimeError("Hook exploded")

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CallableHookDefinition(fn=bad_hook))
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success
        assert "RuntimeError" in result.results[0].reason


class TestUpdatedInput:
    @pytest.mark.asyncio
    async def test_updated_input_propagated(self):
        async def modify_hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(
                hook_type="callable",
                success=True,
                updated_input={"command": "ls -la", "safe": True},
            )

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=modify_hook))
        set_hook_executor(HookExecutor(registry))

        result = await fire_hook(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
        )
        assert result.updated_input is not None
        assert result.updated_input["safe"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
