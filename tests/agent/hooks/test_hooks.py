"""Hook 系统单元测试 — 新 API"""

import json

import pytest

from myrm_agent_harness.agent.hooks import (
    EMPTY_RESULT,
    AggregatedHookResult,
    CallableHookDefinition,
    CommandHookDefinition,
    HookEvent,
    HookExecutor,
    HookRegistry,
    HookResult,
    HttpHookDefinition,
    fire_hook,
    get_hook_executor,
    set_hook_executor,
)
from myrm_agent_harness.agent.hooks.tool_name_mapping import (
    map_from_claude_tool_name,
    map_to_claude_tool_name,
    should_trigger_hook,
)


class TestToolNameMapping:
    def test_map_to_claude_tool_name(self):
        assert map_to_claude_tool_name("file_read_tool") == "Read"
        assert map_to_claude_tool_name("file_write_tool") == "Write"
        assert map_to_claude_tool_name("bash_code_execute_tool") == "Bash"

    def test_map_from_claude_tool_name(self):
        assert map_from_claude_tool_name("Read") == "file_read_tool"
        assert map_from_claude_tool_name("Write") == "file_write_tool"
        assert map_from_claude_tool_name("Bash") == "bash_code_execute_tool"

    def test_should_trigger_hook_no_restriction(self):
        assert should_trigger_hook(None, "any_tool")
        assert should_trigger_hook([], "any_tool")

    def test_should_trigger_hook_match(self):
        assert should_trigger_hook(["file_read_tool"], "file_read_tool")
        assert not should_trigger_hook(["file_write_tool"], "file_read_tool")

    def test_should_trigger_hook_claude_format(self):
        assert should_trigger_hook(["Read"], "file_read_tool")
        assert not should_trigger_hook(["Write"], "file_read_tool")


class TestHookRegistry:
    def test_register_and_get(self):
        registry = HookRegistry()
        hook = CommandHookDefinition(command="echo test")
        registry.register(HookEvent.PRE_TOOL_USE, hook)

        hooks = registry.get(HookEvent.PRE_TOOL_USE)
        assert len(hooks) == 1
        assert hooks[0] is hook

    def test_get_empty(self):
        registry = HookRegistry()
        assert registry.get(HookEvent.SESSION_START) == []

    def test_total_count(self):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="a"))
        registry.register(HookEvent.POST_TOOL_USE, CommandHookDefinition(command="b"))
        assert registry.total_count == 2

    def test_clear(self):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="a"))
        registry.clear()
        assert registry.total_count == 0


class TestHookExecutor:
    @pytest.mark.asyncio
    async def test_execute_no_hooks(self):
        registry = HookRegistry()
        executor = HookExecutor(registry)
        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result is EMPTY_RESULT

    @pytest.mark.asyncio
    async def test_execute_callable_hook(self):
        async def my_hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(hook_type="callable", success=True, output="ok")

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=my_hook))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert not result.blocked
        assert len(result.results) == 1
        assert result.results[0].success

    @pytest.mark.asyncio
    async def test_execute_blocking_hook(self):
        async def blocking_hook(event: str, payload: dict[str, object]) -> HookResult:
            return HookResult(hook_type="callable", success=False, blocked=True, reason="denied")

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=blocking_hook, block_on_failure=True))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result.blocked
        assert "denied" in result.reason

    @pytest.mark.asyncio
    async def test_blocked_hook_aborts_remaining(self):
        """When a hook blocks, subsequent hooks in the same event should not run."""
        call_order: list[str] = []

        async def first_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("first")
            return HookResult(hook_type="callable", success=False, blocked=True, reason="blocked")

        async def second_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("second")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=first_hook, block_on_failure=True))
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=second_hook))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result.blocked
        assert call_order == ["first"]
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_exception_with_block_on_failure_aborts(self):
        """Hook exception with block_on_failure=True should block and abort remaining."""
        call_order: list[str] = []

        async def crashing_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("crash")
            raise RuntimeError("hook crashed")

        async def normal_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("normal")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=crashing_hook, block_on_failure=True))
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=normal_hook))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result.blocked
        assert call_order == ["crash"]
        assert "RuntimeError" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_non_blocking_failure_continues(self):
        """Failed hook without block_on_failure should NOT block subsequent hooks."""
        call_order: list[str] = []

        async def failing_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("fail")
            return HookResult(hook_type="callable", success=False, blocked=False, reason="not blocking")

        async def next_hook(event: str, payload: dict[str, object]) -> HookResult:
            call_order.append("next")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=failing_hook, block_on_failure=False))
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=next_hook))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert not result.blocked
        assert call_order == ["fail", "next"]
        assert len(result.results) == 2

    @pytest.mark.asyncio
    async def test_matcher_filters_hooks(self):
        call_count = 0

        async def counting_hook(event: str, payload: dict[str, object]) -> HookResult:
            nonlocal call_count
            call_count += 1
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=counting_hook, matcher="Bash"))
        executor = HookExecutor(registry)

        await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "Read"})
        assert call_count == 0

        await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "Bash"})
        assert call_count == 1


class TestContextVarIsolation:
    def test_get_set_executor(self):
        set_hook_executor(None)
        assert get_hook_executor() is None

        registry = HookRegistry()
        executor = HookExecutor(registry)
        set_hook_executor(executor)
        assert get_hook_executor() is executor

        set_hook_executor(None)

    @pytest.mark.asyncio
    async def test_fire_hook_without_executor(self):
        set_hook_executor(None)
        result = await fire_hook(HookEvent.SESSION_START, {"session_id": "test"})
        assert result is EMPTY_RESULT


class TestAggregatedHookResult:
    def test_empty_result(self):
        assert not EMPTY_RESULT.blocked
        assert EMPTY_RESULT.reason == ""
        assert EMPTY_RESULT.updated_input is None

    def test_blocked_result(self):
        results = (
            HookResult(hook_type="a", success=True),
            HookResult(hook_type="b", success=False, blocked=True, reason="nope"),
        )
        agg = AggregatedHookResult(results=results)
        assert agg.blocked
        assert "nope" in agg.reason

    def test_updated_input(self):
        updated = {"key": "value"}
        results = (HookResult(hook_type="a", success=True, updated_input=updated),)
        agg = AggregatedHookResult(results=results)
        assert agg.updated_input == updated


class TestSkillParser:
    def test_parse_empty(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        hooks, tools = parse_hooks_from_skill_md("No frontmatter")
        assert hooks == []
        assert tools is None

    def test_parse_session_start(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart:
    - description: Init
      script: ./init.sh
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        event, hook_def = hooks[0]
        assert event == HookEvent.SESSION_START
        assert isinstance(hook_def, CommandHookDefinition)

    def test_parse_pre_tool_use_alias(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  PreToolUse:
    - description: Check
      script: ./check.sh
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        assert hooks[0][0] == HookEvent.PRE_TOOL_USE

    def test_parse_http_hook(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  BeforeToolUse:
    - description: Validate
      url: https://api.example.com/hook
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        assert isinstance(hooks[0][1], HttpHookDefinition)

    def test_parse_allowed_tools(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
allowed-tools: Read, Write, Bash
---

Content
"""
        _, tools = parse_hooks_from_skill_md(content)
        assert tools == ["Read", "Write", "Bash"]


class TestCommandHookExecution:
    @pytest.mark.asyncio
    async def test_command_hook_success(self, tmp_path):
        script = tmp_path / "hook.sh"
        script.write_text('#!/bin/bash\necho "hello"')
        script.chmod(0o755)

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CommandHookDefinition(command=str(script)))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert result.results[0].success
        assert "hello" in result.results[0].output

    @pytest.mark.asyncio
    async def test_command_hook_failure(self, tmp_path):
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/bash\nexit 1")
        script.chmod(0o755)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command=str(script), block_on_failure=True))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result.blocked


class TestRegistrySummary:
    def test_summary_empty(self):
        registry = HookRegistry()
        assert registry.summary() == ""

    def test_summary_with_hooks(self):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo test"))
        registry.register(HookEvent.SESSION_START, CallableHookDefinition(fn=lambda e, p: None))
        summary = registry.summary()
        assert "pre_tool_use:" in summary
        assert "session_start:" in summary
        assert "cmd=echo test" in summary


class TestUpdateRegistry:
    def test_update_registry(self):
        r1 = HookRegistry()
        r1.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo a"))
        executor = HookExecutor(r1)

        r2 = HookRegistry()
        executor.update_registry(r2)

    @pytest.mark.asyncio
    async def test_update_registry_clears_hooks(self):
        r1 = HookRegistry()
        r1.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo a"))
        executor = HookExecutor(r1)

        r2 = HookRegistry()
        executor.update_registry(r2)
        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result is EMPTY_RESULT


class TestExecuteExceptionHandler:
    @pytest.mark.asyncio
    async def test_callable_exception_becomes_failure(self):
        async def bad_hook(event: str, payload: dict) -> HookResult:
            raise RuntimeError("boom")

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CallableHookDefinition(fn=bad_hook))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success
        assert "RuntimeError" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_exception_with_block_on_failure(self):
        async def bad_hook(event: str, payload: dict) -> HookResult:
            raise ValueError("denied")

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=bad_hook, block_on_failure=True))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "t"})
        assert result.blocked
        assert "ValueError" in result.reason


class TestBlockedBreaksChain:
    @pytest.mark.asyncio
    async def test_blocked_hook_stops_subsequent(self):
        """When a hook blocks, subsequent hooks in the chain are skipped."""
        call_log: list[str] = []

        async def hook_a(event: str, payload: dict) -> HookResult:
            call_log.append("a")
            return HookResult(hook_type="callable", success=False, blocked=True, reason="blocked")

        async def hook_b(event: str, payload: dict) -> HookResult:
            call_log.append("b")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=hook_a, block_on_failure=True))
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=hook_b))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert result.blocked
        assert call_log == ["a"]
        assert len(result.results) == 1

    @pytest.mark.asyncio
    async def test_non_blocked_continues_chain(self):
        call_log: list[str] = []

        async def hook_a(event: str, payload: dict) -> HookResult:
            call_log.append("a")
            return HookResult(hook_type="callable", success=True)

        async def hook_b(event: str, payload: dict) -> HookResult:
            call_log.append("b")
            return HookResult(hook_type="callable", success=True)

        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=hook_a))
        registry.register(HookEvent.PRE_TOOL_USE, CallableHookDefinition(fn=hook_b))
        executor = HookExecutor(registry)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "test"})
        assert not result.blocked
        assert call_log == ["a", "b"]
        assert len(result.results) == 2


class TestFireHookWithExecutor:
    @pytest.mark.asyncio
    async def test_fire_hook_delegates_to_executor(self):
        async def ok_hook(event: str, payload: dict) -> HookResult:
            return HookResult(hook_type="callable", success=True, output="fired")

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CallableHookDefinition(fn=ok_hook))
        executor = HookExecutor(registry)
        set_hook_executor(executor)
        try:
            result = await fire_hook(HookEvent.SESSION_START, {"session_id": "s1"})
            assert len(result.results) == 1
            assert result.results[0].success
        finally:
            set_hook_executor(None)


class TestPayloadFromDataclass:
    def test_converts_dataclass_to_dict(self):
        from dataclasses import dataclass

        from myrm_agent_harness.agent.hooks import payload_from_dataclass

        @dataclass(frozen=True)
        class FakePayload:
            tool_name: str
            args: dict

        payload = FakePayload(tool_name="test", args={"k": "v"})
        result = payload_from_dataclass(payload)
        assert result == {"tool_name": "test", "args": {"k": "v"}}


class TestParseHookJson:
    def test_valid_json_ok_true(self):
        from myrm_agent_harness.agent.hooks.executor import _parse_hook_json

        assert _parse_hook_json('{"ok": true}')["ok"] is True

    def test_valid_json_ok_false(self):
        from myrm_agent_harness.agent.hooks.executor import _parse_hook_json

        result = _parse_hook_json('{"ok": false, "reason": "nope"}')
        assert result["ok"] is False
        assert result["reason"] == "nope"

    def test_plain_text_ok(self):
        from myrm_agent_harness.agent.hooks.executor import _parse_hook_json

        assert _parse_hook_json("ok")["ok"] is True
        assert _parse_hook_json("true")["ok"] is True
        assert _parse_hook_json("yes")["ok"] is True

    def test_plain_text_reject(self):
        from myrm_agent_harness.agent.hooks.executor import _parse_hook_json

        result = _parse_hook_json("something else")
        assert result["ok"] is False

    def test_invalid_json_dict_no_ok_key(self):
        from myrm_agent_harness.agent.hooks.executor import _parse_hook_json

        result = _parse_hook_json('{"result": "good"}')
        assert result["ok"] is False


class TestInjectArguments:
    def test_basic_injection(self):
        from myrm_agent_harness.agent.hooks.executor import _inject_arguments

        result = _inject_arguments("payload=$ARGUMENTS", {"key": "val"})
        assert '"key"' in result
        assert '"val"' in result

    def test_shell_escape(self):
        from myrm_agent_harness.agent.hooks.executor import _inject_arguments

        result = _inject_arguments("echo $ARGUMENTS", {"a": "b"}, shell_escape=True)
        assert "'" in result or '"' in result


class TestMatchesHook:
    def test_no_matcher_matches_all(self):
        from myrm_agent_harness.agent.hooks.executor import _matches_hook

        hook = CommandHookDefinition(command="echo")
        assert _matches_hook(hook, {"tool_name": "anything"})

    def test_glob_matcher(self):
        from myrm_agent_harness.agent.hooks.executor import _matches_hook

        hook = CommandHookDefinition(command="echo", matcher="file_*")
        assert _matches_hook(hook, {"tool_name": "file_read"})
        assert not _matches_hook(hook, {"tool_name": "bash"})


class TestHookDetail:
    def test_callable_detail(self):
        from myrm_agent_harness.agent.hooks.executor import _hook_detail

        hook = CallableHookDefinition(fn=lambda e, p: None)
        detail = _hook_detail(hook)
        assert "fn=" in detail

    def test_command_detail(self):
        from myrm_agent_harness.agent.hooks.executor import _hook_detail

        hook = CommandHookDefinition(command="echo hello world")
        detail = _hook_detail(hook)
        assert "cmd=echo hello world" in detail

    def test_http_detail(self):
        from myrm_agent_harness.agent.hooks.executor import _hook_detail

        hook = HttpHookDefinition(url="https://example.com/hook")
        detail = _hook_detail(hook)
        assert "url=https://example.com/hook" in detail

    def test_llm_detail(self):
        from myrm_agent_harness.agent.hooks.executor import _hook_detail
        from myrm_agent_harness.agent.hooks.types import LLMHookDefinition

        hook = LLMHookDefinition(prompt="check this", depth="quick")
        detail = _hook_detail(hook)
        assert "depth=quick" in detail
        assert "prompt=check this" in detail


class TestHotReload:
    def test_missing_file_returns_empty_registry(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        reloader = HookReloader(tmp_path / "nonexistent.json")
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_load_valid_config(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"pre_tool_use": [{"type": "command", "command": "echo check"}]}}))

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 1

    def test_reload_on_mtime_change(self, tmp_path):
        import time

        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"pre_tool_use": [{"type": "command", "command": "echo v1"}]}}))

        reloader = HookReloader(config)
        r1 = reloader.current_registry()
        assert r1.total_count == 1

        r1_again = reloader.current_registry()
        assert r1_again is r1

        time.sleep(0.01)
        config.write_text(
            json.dumps(
                {
                    "hooks": {
                        "pre_tool_use": [
                            {"type": "command", "command": "echo v2"},
                            {"type": "command", "command": "echo v3"},
                        ]
                    }
                }
            )
        )

        r2 = reloader.current_registry()
        assert r2.total_count == 2
        assert r2 is not r1

    def test_file_deleted_clears_registry(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"session_start": [{"type": "command", "command": "echo hi"}]}}))

        reloader = HookReloader(config)
        r1 = reloader.current_registry()
        assert r1.total_count == 1

        config.unlink()
        r2 = reloader.current_registry()
        assert r2.total_count == 0

    def test_invalid_json_returns_empty(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text("not valid json {{{")

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_unknown_hook_type_skipped(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"pre_tool_use": [{"type": "unknown_type", "command": "echo"}]}}))

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_hooks_section_not_dict(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": "not a dict"}))

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_hook_list_not_list(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"pre_tool_use": "not a list"}}))

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_hook_data_not_dict(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(json.dumps({"hooks": {"pre_tool_use": ["not a dict"]}}))

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 0

    def test_http_hook_from_config(self, tmp_path):
        from myrm_agent_harness.agent.hooks.hot_reload import HookReloader

        config = tmp_path / "hooks.json"
        config.write_text(
            json.dumps({"hooks": {"post_tool_use": [{"type": "http", "url": "https://audit.example.com/hook"}]}})
        )

        reloader = HookReloader(config)
        registry = reloader.current_registry()
        assert registry.total_count == 1


class TestSkillParserExtended:
    def test_parse_yaml_error(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = "---\n: invalid: yaml: [broken\n---\nContent"
        hooks, tools = parse_hooks_from_skill_md(content)
        assert hooks == []
        assert tools is None

    def test_parse_non_dict_metadata(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = "---\n- just a list\n---\nContent"
        hooks, tools = parse_hooks_from_skill_md(content)
        assert hooks == []
        assert tools is None

    def test_parse_unknown_hook_event(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  UnknownEvent:
    - description: Missing
      script: ./run.sh
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert hooks == []

    def test_parse_hook_config_not_list(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart: not_a_list
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert hooks == []

    def test_parse_hook_config_item_not_dict(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart:
    - just_a_string
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert hooks == []

    def test_parse_missing_script_and_url(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart:
    - description: No script or url
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert hooks == []

    def test_parse_both_script_and_url_prefers_url(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart:
    - description: Both
      script: ./run.sh
      url: https://example.com/hook
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        assert isinstance(hooks[0][1], HttpHookDefinition)

    def test_parse_with_failure_mode(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  PreToolUse:
    - description: Strict
      script: ./check.sh
      failure_mode: fail_closed
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        assert hooks[0][1].block_on_failure is True

    def test_parse_with_tools_string(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  PreToolUse:
    - description: Single tool
      script: ./check.sh
      tools: bash_tool
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        assert hooks[0][1].matcher == "bash_tool"

    def test_parse_auth_env_var(self):
        import os

        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        os.environ["TEST_HOOK_TOKEN"] = "Bearer test123"
        try:
            content = """---
name: test
hooks:
  SessionStart:
    - description: Auth
      url: https://example.com/hook
      auth: ${TEST_HOOK_TOKEN}
---

Content
"""
            hooks, _ = parse_hooks_from_skill_md(content)
            assert len(hooks) == 1
            hook_def = hooks[0][1]
            assert isinstance(hook_def, HttpHookDefinition)
            assert hook_def.headers.get("Authorization") == "Bearer test123"
        finally:
            del os.environ["TEST_HOOK_TOKEN"]

    def test_parse_auth_literal(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
hooks:
  SessionStart:
    - description: Auth literal
      url: https://example.com/hook
      auth: Bearer literal_token
---

Content
"""
        hooks, _ = parse_hooks_from_skill_md(content)
        assert len(hooks) == 1
        hook_def = hooks[0][1]
        assert isinstance(hook_def, HttpHookDefinition)
        assert hook_def.headers.get("Authorization") == "Bearer literal_token"

    def test_parse_allowed_tools_as_list(self):
        from myrm_agent_harness.agent.hooks.skill_parser import parse_hooks_from_skill_md

        content = """---
name: test
allowed-tools:
  - Read
  - Write
---

Content
"""
        _, tools = parse_hooks_from_skill_md(content)
        assert tools == ["Read", "Write"]


class TestCommandHookTimeout:
    @pytest.mark.asyncio
    async def test_command_timeout(self):
        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CommandHookDefinition(command="sleep 10", timeout_seconds=1))
        executor = HookExecutor(registry)
        result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success
        assert "timed out" in result.results[0].reason


class TestHttpHookExecution:
    @pytest.mark.asyncio
    async def test_http_hook_ssrf_blocked(self):
        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, HttpHookDefinition(url="https://localhost/hook"))
        executor = HookExecutor(registry)
        result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success
        assert "SSRF" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_http_hook_dns_blocked(self):
        from unittest.mock import AsyncMock, patch

        from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, HttpHookDefinition(url="https://evil.example.com/hook"))
        executor = HookExecutor(registry)

        with patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
            new_callable=AsyncMock,
            side_effect=SSRFSecurityError("private IP"),
        ):
            result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success
        assert "SSRF" in result.results[0].reason

    @pytest.mark.asyncio
    async def test_http_hook_success_mock(self):
        import types
        from unittest.mock import AsyncMock, MagicMock, patch

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, HttpHookDefinition(url="https://api.example.com/hook"))
        executor = HookExecutor(registry)

        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.text = '{"ok": true}'
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = types.ModuleType("httpx")
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.dict("sys.modules", {"httpx": mock_httpx}),
        ):
            result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert result.results[0].success

    @pytest.mark.asyncio
    async def test_http_hook_failure_response(self):
        import types
        from unittest.mock import AsyncMock, MagicMock, patch

        registry = HookRegistry()
        registry.register(
            HookEvent.SESSION_START, HttpHookDefinition(url="https://api.example.com/hook", block_on_failure=True)
        )
        executor = HookExecutor(registry)

        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.text = "Forbidden"
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = types.ModuleType("httpx")
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.dict("sys.modules", {"httpx": mock_httpx}),
        ):
            result = await executor.execute(HookEvent.SESSION_START, {})
        assert result.blocked

    @pytest.mark.asyncio
    async def test_http_hook_network_error(self):
        import types
        from unittest.mock import AsyncMock, MagicMock, patch

        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, HttpHookDefinition(url="https://api.example.com/hook"))
        executor = HookExecutor(registry)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = types.ModuleType("httpx")
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        with (
            patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                side_effect=ConnectionError("refused"),
            ),
            patch.dict("sys.modules", {"httpx": mock_httpx}),
        ):
            result = await executor.execute(HookEvent.SESSION_START, {})
        assert len(result.results) == 1
        assert not result.results[0].success


class TestDispatchUnknownHookType:
    @pytest.mark.asyncio
    async def test_dispatch_unknown_type_returns_failure(self):
        from unittest.mock import MagicMock

        registry = HookRegistry()
        executor = HookExecutor(registry)

        fake_hook = MagicMock()
        fake_hook.matcher = None
        fake_hook.type = "unknown"
        fake_hook.block_on_failure = False

        result = await executor._dispatch(fake_hook, "test_event", {})
        assert not result.success
        assert "Unknown" in result.reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

def test_bootstrap_hook_registry():
    from myrm_agent_harness.agent.hooks.executor import bootstrap_hook_registry, get_hook_executor, set_hook_executor

    # Clear existing
    set_hook_executor(None)

    # First call creates it
    registry1 = bootstrap_hook_registry()
    assert registry1 is not None
    assert get_hook_executor() is not None

    # Second call returns the same
    registry2 = bootstrap_hook_registry()
    assert registry1 is registry2
