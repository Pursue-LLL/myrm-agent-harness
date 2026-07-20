"""Tests for tool-specific loop detector suggestion generators."""

from __future__ import annotations

from myrm_agent_harness.agent.security.guards.loop_guard_types import CallRecord
from myrm_agent_harness.agent.security.guards.loop_suggestions.bash import suggest_bash
from myrm_agent_harness.agent.security.guards.loop_suggestions.browser import suggest_browser_snapshot
from myrm_agent_harness.agent.security.guards.loop_suggestions.file import suggest_file_read
from myrm_agent_harness.agent.security.guards.loop_suggestions.memory import suggest_memory_recall
from myrm_agent_harness.agent.security.guards.loop_suggestions.meta import (
    suggest_skill_search,
    suggest_skill_select,
    suggest_spawn_subagent,
)
from myrm_agent_harness.agent.security.guards.loop_suggestions.web import suggest_web_search


def _make_call(tool: str, args: dict[str, object] | None = None, result: str | None = None) -> CallRecord:
    rec = CallRecord(tool_name=tool, args_hash="h", args=args or {})
    if result is not None:
        rec.result_content = result
    return rec


class TestSuggestMemoryRecall:
    def test_empty_result_suggests_profile_key(self) -> None:
        calls = [_make_call("memory_search_tool", {"query": "test"}, "[]")]
        result = suggest_memory_recall(calls)
        assert "profile_key" in result

    def test_untried_categories(self) -> None:
        calls = [_make_call("memory_search_tool", {"categories": ["knowledge"]}, "some data")]
        result = suggest_memory_recall(calls)
        assert "untried categories" in result

    def test_low_limit(self) -> None:
        calls = [
            _make_call(
                "memory_search_tool", {"limit": 5, "categories": list(["knowledge", "event", "preference", "rule"])}, "data"
            )
        ]
        result = suggest_memory_recall(calls)
        assert "limit" in result or "profile_key" in result

    def test_no_suggestions_fallback(self) -> None:
        calls = [
            _make_call(
                "memory_search_tool", {"categories": list(["knowledge", "event", "preference", "rule"]), "limit": 20}, "data"
            )
        ]
        result = suggest_memory_recall(calls)
        assert len(result) > 0


class TestSuggestBash:
    def test_file_not_found(self) -> None:
        calls = [_make_call("bash_code_execute_tool", {"command": "cat /x"}, "Error: No such file or directory")]
        result = suggest_bash(calls)
        assert "ls" in result or "path" in result.lower()

    def test_permission_denied(self) -> None:
        calls = [_make_call("bash_code_execute_tool", {"command": "cat /root"}, "Permission denied")]
        result = suggest_bash(calls)
        assert "permission" in result.lower()

    def test_invalid_format(self) -> None:
        calls = [_make_call("bash_code_execute_tool", {"command": "bad"}, "Error: syntax error near unexpected token")]
        result = suggest_bash(calls)
        assert "syntax" in result.lower() or "verify" in result.lower()

    def test_many_commands(self) -> None:
        calls = [_make_call("bash_code_execute_tool", {"command": f"cmd{i}"}, "ok") for i in range(3)]
        result = suggest_bash(calls)
        assert len(result) > 0

    def test_few_commands_fallback(self) -> None:
        calls = [_make_call("bash_code_execute_tool", {"command": "ls"}, "ok")]
        result = suggest_bash(calls)
        assert len(result) > 0


class TestSuggestFileRead:
    def test_file_not_found(self) -> None:
        calls = [_make_call("file_read_tool", {"path": "/x"}, "Error: file not found")]
        result = suggest_file_read(calls)
        assert "glob" in result.lower() or "find" in result.lower() or "path" in result.lower()

    def test_permission_denied(self) -> None:
        calls = [_make_call("file_read_tool", {"path": "/root"}, "Permission denied")]
        result = suggest_file_read(calls)
        assert "permission" in result.lower()

    def test_many_paths(self) -> None:
        calls = [_make_call("file_read_tool", {"path": f"/p{i}"}, "ok") for i in range(3)]
        result = suggest_file_read(calls)
        assert len(result) > 0


class TestSuggestWebSearch:
    def test_empty_results(self) -> None:
        calls = [_make_call("web_search_tool", {"query": "test"}, "[]")]
        result = suggest_web_search(calls)
        assert len(result) > 0

    def test_network_error(self) -> None:
        calls = [_make_call("web_search_tool", {"query": "test"}, "Connection refused")]
        result = suggest_web_search(calls)
        assert len(result) > 0

    def test_many_queries(self) -> None:
        calls = [_make_call("web_search_tool", {"query": f"q{i}"}, "ok") for i in range(3)]
        result = suggest_web_search(calls)
        assert len(result) > 0


class TestSuggestBrowserSnapshot:
    def test_empty_page(self) -> None:
        calls = [_make_call("browser_snapshot_tool", {}, "[]")]
        result = suggest_browser_snapshot(calls)
        assert len(result) > 0

    def test_timeout(self) -> None:
        calls = [_make_call("browser_snapshot_tool", {}, "Request timed out")]
        result = suggest_browser_snapshot(calls)
        assert len(result) > 0

    def test_many_calls(self) -> None:
        calls = [_make_call("browser_snapshot_tool", {"selector": f"s{i}"}, "ok") for i in range(3)]
        result = suggest_browser_snapshot(calls)
        assert len(result) > 0


class TestSuggestSpawnSubagent:
    def test_timeout(self) -> None:
        calls = [_make_call("delegate_task_tool", {"prompt": "test"}, "Request timed out")]
        result = suggest_spawn_subagent(calls)
        assert len(result) > 0

    def test_many_calls(self) -> None:
        calls = [_make_call("delegate_task_tool", {"prompt": f"p{i}"}, "ok") for i in range(3)]
        result = suggest_spawn_subagent(calls)
        assert len(result) > 0


class TestSuggestSkillSelect:
    def test_error(self) -> None:
        calls = [_make_call("skill_select_tool", {"skill_id": "s1"}, "Error: not found")]
        result = suggest_skill_select(calls)
        assert len(result) > 0

    def test_many_calls(self) -> None:
        calls = [_make_call("skill_select_tool", {"skill_id": f"s{i}"}, "ok") for i in range(3)]
        result = suggest_skill_select(calls)
        assert len(result) > 0


class TestSuggestSkillSearch:
    def test_empty_results(self) -> None:
        calls = [_make_call("discover_capability_tool", {"query": "test"}, "[]")]
        result = suggest_skill_search(calls)
        assert len(result) > 0

    def test_many_calls(self) -> None:
        calls = [_make_call("discover_capability_tool", {"query": f"q{i}"}, "ok") for i in range(3)]
        result = suggest_skill_search(calls)
        assert len(result) > 0
