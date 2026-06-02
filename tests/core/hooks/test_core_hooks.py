"""Tests for core.hooks — framework-agnostic hook type definitions."""

from typing import get_args

from myrm_agent_harness.core.hooks import (
    EMPTY_RESULT,
    AggregatedHookResult,
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HookEvent,
    HookRegistryProtocol,
    HookResult,
    HttpHookDefinition,
    LLMHookDefinition,
    MemoryArchivedPayload,
    PostToolUseFailurePayload,
    PostToolUsePayload,
    PreCompactPayload,
    PreToolUsePayload,
    SessionEndPayload,
    SessionStartPayload,
    SubagentMergeConflictPayload,
    SubagentStartPayload,
    SubagentStopPayload,
    UserTurnPayload,
)


class TestHookEvent:
    def test_is_str_enum(self) -> None:
        assert isinstance(HookEvent.SESSION_START, str)
        assert HookEvent.SESSION_START == "session_start"

    def test_key_events_exist(self) -> None:
        required = {
            "SESSION_START", "SESSION_END", "USER_TURN",
            "PRE_TOOL_USE", "POST_TOOL_USE", "POST_TOOL_USE_FAILURE",
        }
        actual = {e.name for e in HookEvent}
        assert required.issubset(actual)


class TestHookResult:
    def test_basic_creation(self) -> None:
        r = HookResult(hook_type="callable", success=True)
        assert r.hook_type == "callable"
        assert r.success is True
        assert r.output == ""
        assert r.blocked is False
        assert r.reason == ""
        assert r.updated_input is None

    def test_blocking_result(self) -> None:
        r = HookResult(
            hook_type="http", success=True, blocked=True, reason="policy violation"
        )
        assert r.blocked is True
        assert r.reason == "policy violation"

    def test_with_updated_input(self) -> None:
        r = HookResult(
            hook_type="llm",
            success=True,
            updated_input={"sanitized": "input"},
        )
        assert r.updated_input == {"sanitized": "input"}

    def test_frozen(self) -> None:
        r = HookResult(hook_type="cmd", success=False)
        import pytest
        with pytest.raises(AttributeError):
            r.success = True  # type: ignore[misc]


class TestEmptyResult:
    def test_is_aggregated_hook_result(self) -> None:
        assert isinstance(EMPTY_RESULT, AggregatedHookResult)
        assert EMPTY_RESULT.blocked is False
        assert EMPTY_RESULT.results == ()


class TestAggregatedHookResult:
    def test_default_empty(self) -> None:
        r = AggregatedHookResult()
        assert r.blocked is False
        assert r.reason == ""
        assert r.updated_input is None
        assert r.additional_contexts == []
        assert r.all_succeeded is True

    def test_with_blocking_result(self) -> None:
        results = (
            HookResult(hook_type="a", success=True),
            HookResult(hook_type="b", success=True, blocked=True, reason="deny"),
        )
        r = AggregatedHookResult(results=results)
        assert r.blocked is True
        assert r.reason == "deny"

    def test_updated_input_last_wins(self) -> None:
        results = (
            HookResult(hook_type="a", success=True, updated_input={"first": True}),
            HookResult(hook_type="b", success=True, updated_input={"second": True}),
        )
        r = AggregatedHookResult(results=results)
        assert r.updated_input == {"second": True}

    def test_additional_contexts(self) -> None:
        results = (
            HookResult(hook_type="a", success=True, additional_context="ctx1"),
            HookResult(hook_type="b", success=True),
            HookResult(hook_type="c", success=True, additional_context="ctx2"),
        )
        r = AggregatedHookResult(results=results)
        assert r.additional_contexts == ["ctx1", "ctx2"]

    def test_all_succeeded_false(self) -> None:
        results = (
            HookResult(hook_type="a", success=True),
            HookResult(hook_type="b", success=False),
        )
        r = AggregatedHookResult(results=results)
        assert r.all_succeeded is False


class TestHookDefinitions:
    def test_callable_definition(self) -> None:
        async def handler(event: str, data: dict[str, object]) -> HookResult:
            return HookResult(hook_type="callable", success=True)

        d = CallableHookDefinition(fn=handler)
        assert d.type == "callable"
        assert d.fn is handler

    def test_http_definition(self) -> None:
        d = HttpHookDefinition(url="https://hook.example.com")
        assert d.url == "https://hook.example.com"
        assert d.type == "http"
        assert d.headers == {}

    def test_command_definition(self) -> None:
        d = CommandHookDefinition(command="echo test")
        assert d.command == "echo test"
        assert d.type == "command"

    def test_llm_definition(self) -> None:
        d = LLMHookDefinition(prompt="Analyze: $ARGUMENTS")
        assert "Analyze" in d.prompt
        assert d.type == "llm"
        assert d.depth == "quick"

    def test_shared_base_defaults(self) -> None:
        d = CommandHookDefinition(command="ls")
        assert d.matcher is None
        assert d.block_on_failure is False
        assert d.timeout_seconds == 30

    def test_hook_definition_is_union(self) -> None:
        args = get_args(HookDefinition)
        expected = {
            CallableHookDefinition,
            CommandHookDefinition,
            HttpHookDefinition,
            LLMHookDefinition,
        }
        assert set(args) == expected


class TestPayloads:
    def test_pre_tool_use(self) -> None:
        p = PreToolUsePayload(
            tool_name="bash", tool_input={"cmd": "ls"}, tool_call_id="tc1"
        )
        assert p.tool_name == "bash"
        assert p.tool_call_id == "tc1"

    def test_post_tool_use(self) -> None:
        p = PostToolUsePayload(
            tool_name="bash",
            tool_input={"cmd": "ls"},
            tool_output="output",
            tool_call_id="tc1",
        )
        assert p.tool_output == "output"

    def test_post_tool_use_failure(self) -> None:
        p = PostToolUseFailurePayload(
            tool_name="bash",
            tool_input={"cmd": "rm"},
            error="permission denied",
            tool_call_id="tc1",
        )
        assert p.error == "permission denied"

    def test_session_start(self) -> None:
        p = SessionStartPayload(session_id="s1")
        assert p.session_id == "s1"
        assert p.workspace_path == ""

    def test_session_end(self) -> None:
        p = SessionEndPayload(session_id="s1", total_tokens=1000)
        assert p.total_tokens == 1000

    def test_pre_compact(self) -> None:
        p = PreCompactPayload(session_id="s1", message_count=10, total_tokens=5000)
        assert p.total_tokens == 5000

    def test_memory_archived(self) -> None:
        p = MemoryArchivedPayload(
            session_id="s1", agent_id="a1", archived_count=5, duration_ms=100.0
        )
        assert p.archived_count == 5

    def test_subagent_start(self) -> None:
        p = SubagentStartPayload(task_id="t1", agent_type="research", task_description="task")
        assert p.task_id == "t1"

    def test_subagent_stop(self) -> None:
        p = SubagentStopPayload(task_id="t1", agent_type="research", success=True, result="done")
        assert p.result == "done"

    def test_subagent_merge_conflict(self) -> None:
        p = SubagentMergeConflictPayload(
            task_id="t1", agent_type="code", branch="main", conflicting_files=("a.py",)
        )
        assert p.conflicting_files == ("a.py",)

    def test_user_turn(self) -> None:
        p = UserTurnPayload(session_id="s1", user_input="hello")
        assert p.user_input == "hello"


class TestReExportTypeIdentity:
    def test_hook_event_identity(self) -> None:
        from myrm_agent_harness.agent.hooks.types import HookEvent as AgentHookEvent

        assert HookEvent is AgentHookEvent

    def test_hook_result_identity(self) -> None:
        from myrm_agent_harness.agent.hooks.types import (
            HookResult as AgentHookResult,
        )

        assert HookResult is AgentHookResult

    def test_isinstance_cross_module(self) -> None:
        from myrm_agent_harness.agent.hooks.types import (
            HookResult as AgentHookResult,
        )

        r = HookResult(hook_type="test", success=True, blocked=True)
        assert isinstance(r, AgentHookResult)


class TestHookRegistryProtocol:
    """HookRegistryProtocol — runtime_checkable Protocol for cross-layer DI."""

    def test_real_hook_registry_satisfies_protocol(self) -> None:
        from myrm_agent_harness.agent.hooks import HookRegistry

        registry = HookRegistry()
        assert isinstance(registry, HookRegistryProtocol)

    def test_protocol_has_required_attrs(self) -> None:
        annotations = HookRegistryProtocol.__protocol_attrs__
        assert "register" in annotations or hasattr(HookRegistryProtocol, "register")
        assert "_hooks" in annotations or hasattr(HookRegistryProtocol, "_hooks")

    def test_non_conforming_object_rejected(self) -> None:
        class FakeRegistry:
            pass

        assert not isinstance(FakeRegistry(), HookRegistryProtocol)

    def test_duck_typed_conforming_object(self) -> None:
        class MinimalRegistry:
            def __init__(self) -> None:
                self._hooks: dict[str, list[HookDefinition]] = {}

            def register(self, event: str | HookEvent, hook: HookDefinition) -> None:
                self._hooks.setdefault(str(event), []).append(hook)

        registry = MinimalRegistry()
        assert isinstance(registry, HookRegistryProtocol)

    def test_register_and_access_hooks(self) -> None:
        from myrm_agent_harness.agent.hooks import HookRegistry

        async def dummy_hook(**kwargs: object) -> HookResult:
            return HookResult(hook_type="test", success=True)

        registry = HookRegistry()
        hook_def = CallableHookDefinition(fn=dummy_hook)
        registry.register(HookEvent.PRE_TOOL_USE, hook_def)
        assert hook_def in registry._hooks[HookEvent.PRE_TOOL_USE]
