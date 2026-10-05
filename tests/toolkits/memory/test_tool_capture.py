"""Tests for tool-scoped memory capture hook.

Validates:
- Edict extraction (EN + ZH patterns)
- Tool name association via keyword mapping
- Failure tracking and threshold-based rule creation
- ToolMemoryCaptureHook event handlers
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory.tool_capture import (
    ToolMemoryCaptureHook,
    _FailureTracker,
    associate_tool,
    extract_clean_error_summary,
    extract_tool_edicts,
)
from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

# ── extract_tool_edicts ─────────────────────────────────────────────


class TestExtractToolEdicts:
    def test_english_never_use(self):
        edicts = extract_tool_edicts("never use sudo for this project.")
        assert len(edicts) >= 1
        assert any("sudo" in e.rule_text.lower() for e in edicts)
        assert edicts[0].language == "en"

    def test_english_dont_run(self):
        edicts = extract_tool_edicts("don't run rm -rf ever again.")
        assert len(edicts) >= 1
        assert any("rm" in e.rule_text.lower() for e in edicts)

    def test_english_always_use(self):
        edicts = extract_tool_edicts("always use ruff instead of flake8.")
        assert len(edicts) >= 1
        assert any("ruff" in e.rule_text.lower() for e in edicts)

    def test_chinese_prohibit(self):
        edicts = extract_tool_edicts("禁止使用sudo命令。")
        assert len(edicts) >= 1
        assert any("sudo" in e.rule_text for e in edicts)
        assert edicts[0].language == "zh"

    def test_chinese_must_use(self):
        edicts = extract_tool_edicts("必须使用ruff进行代码检查。")
        assert len(edicts) >= 1
        assert any("ruff" in e.rule_text for e in edicts)

    def test_no_match(self):
        edicts = extract_tool_edicts("Hello, how are you today?")
        assert edicts == []

    def test_deduplication(self):
        edicts = extract_tool_edicts("never use sudo. Don't use sudo.")
        rule_texts = [e.rule_text.lower() for e in edicts]
        assert len(set(rule_texts)) == len(rule_texts)

    def test_short_text_filtered(self):
        edicts = extract_tool_edicts("never use x.")
        assert all(len(e.rule_text) >= 3 for e in edicts)


# ── associate_tool ─────────────────────────────────────────────────


class TestAssociateTool:
    def test_keyword_match_sudo(self):
        assert associate_tool("sudo rm -rf /", None) == "bash_code_execute_tool"

    def test_keyword_match_search(self):
        assert associate_tool("search for python docs", None) == "web_search_tool"

    def test_keyword_match_chinese(self):
        assert associate_tool("不要使用终端删除", None) == "bash_code_execute_tool"

    def test_unrelated_text_strictly_isolated_from_recent_tool(self):
        # Bug fix: unrelated negatives should NOT be falsely bound to recent_tool
        assert associate_tool("不要说谎，直接告诉我", "my_tool") is None
        assert associate_tool("something unrelated", "my_tool") is None
        assert associate_tool("别太啰嗦", "web_search_tool") is None

    def test_explicit_pronoun_fallback_to_recent_tool(self):
        # Legitimate pronoun pointing back to recent tool
        assert associate_tool("不要再用这个工具了", "bash_code_execute_tool") == "bash_code_execute_tool"
        assert associate_tool("该工具禁止在此目录下运行", "file_write_tool") == "file_write_tool"
        assert associate_tool("don't run this command again", "bash_code_execute_tool") == "bash_code_execute_tool"
        assert associate_tool("never execute that tool", "my_tool") == "my_tool"

    def test_dynamic_tools_and_mcp_matching(self):
        avail = ["github__create_issue", "postgres__run_query", "slack__send_message"]
        assert associate_tool("不要使用 github 创建 issue", available_tools=avail) == "github__create_issue"
        assert associate_tool("never run postgres query directly", available_tools=avail) == "postgres__run_query"
        assert associate_tool("something else", available_tools=avail) is None

    def test_no_match_no_recent(self):
        assert associate_tool("something unrelated", None) is None


class TestExtractCleanErrorSummary:
    def test_python_traceback_extracts_tail_exception(self):
        tb = """Traceback (most recent call last):
  File "app.py", line 42, in <module>
    do_something()
  File "app.py", line 12, in do_something
    raise PermissionError("Permission denied: /etc/shadow")"""
        summary = extract_clean_error_summary(tb)
        assert "PermissionError" in summary or "Permission denied" in summary

    def test_ansi_escape_cleaning(self):
        raw = "\x1b[31m[ERROR]\x1b[0m ConnectionTimeout: endpoint unreachable"
        summary = extract_clean_error_summary(raw)
        assert "\x1b" not in summary
        assert "ConnectionTimeout: endpoint unreachable" in summary

    def test_empty_error_handling(self):
        assert extract_clean_error_summary("") == "unknown error"
        assert extract_clean_error_summary("   \n\t  ") == "unknown error"


# ── _FailureTracker ─────────────────────────────────────────────────


class TestFailureTracker:
    def test_count_increments(self):
        tracker = _FailureTracker()
        assert tracker.record_failure("tool_a") == 1
        assert tracker.record_failure("tool_a") == 2
        assert tracker.record_failure("tool_b") == 1

    def test_should_create_rule_at_threshold(self):
        tracker = _FailureTracker()
        tracker.record_failure("tool_a")
        assert not tracker.should_create_rule("tool_a")
        tracker.record_failure("tool_a")
        assert tracker.should_create_rule("tool_a")

    def test_mark_recorded_prevents_duplicate(self):
        tracker = _FailureTracker()
        tracker.record_failure("tool_a")
        tracker.record_failure("tool_a")
        assert tracker.should_create_rule("tool_a")
        tracker.mark_recorded("tool_a")
        assert not tracker.should_create_rule("tool_a")


# ── ToolMemoryCaptureHook ───────────────────────────────────────────


class TestToolMemoryCaptureHook:
    @pytest.mark.asyncio
    async def test_on_user_turn_extracts_edict(self):
        hook = ToolMemoryCaptureHook()
        # Mock last tool
        await hook.on_post_tool_use("post_tool_use", {"tool_name": "bash_code_execute_tool"})

        result = await hook.on_user_turn("user_turn", {"user_input": "never use sudo"})
        assert result.success is True

        pending = hook.pending_rules
        assert len(pending) >= 1
        rule = pending[0]
        assert rule.tool_name == "bash_code_execute_tool"
        assert rule.tool_rule_priority == ToolRulePriority.CRITICAL
        assert "sudo" in rule.content.lower()

    @pytest.mark.asyncio
    async def test_on_user_turn_no_edict(self):
        hook = ToolMemoryCaptureHook()
        result = await hook.on_user_turn("user_turn", {"user_input": "hello world"})
        assert result.success is True
        assert len(hook.pending_rules) == 0

    @pytest.mark.asyncio
    async def test_on_post_tool_failure_threshold(self):
        hook = ToolMemoryCaptureHook()
        await hook.on_post_tool_failure(
            "POST_TOOL_USE_FAILURE",
            {"tool_name": "web_fetch_tool", "error": "timeout"},
        )
        assert len(hook.pending_rules) == 0

        await hook.on_post_tool_failure(
            "POST_TOOL_USE_FAILURE",
            {"tool_name": "web_fetch_tool", "error": "timeout again"},
        )
        assert len(hook.pending_rules) == 1
        rule = hook.pending_rules[0]
        assert rule.tool_rule_priority == ToolRulePriority.NORMAL
        assert rule.tool_name == "web_fetch_tool"
        # Transient failure rules carry a short TTL + origin marker so the context
        # loader can keep them out of the stable prompt layer.
        assert rule.expected_valid_days == 1
        assert rule.metadata.get("origin") == "tool_failure"

    @pytest.mark.asyncio
    async def test_on_post_tool_failure_no_duplicate_rule(self):
        hook = ToolMemoryCaptureHook()
        for _ in range(5):
            await hook.on_post_tool_failure(
                "POST_TOOL_USE_FAILURE",
                {"tool_name": "web_fetch_tool", "error": "err"},
            )
        failure_rules = [r for r in hook.pending_rules if "failed" in r.content]
        assert len(failure_rules) == 1

    @pytest.mark.asyncio
    async def test_on_post_tool_failure_empty_tool_name(self):
        hook = ToolMemoryCaptureHook()
        result = await hook.on_post_tool_failure(
            "POST_TOOL_USE_FAILURE",
            {"tool_name": "", "error": "err"},
        )
        assert result.success
        assert len(hook.pending_rules) == 0

    def test_drain_pending(self):
        hook = ToolMemoryCaptureHook()
        hook._pending_rules.append(
            __import__(
                "myrm_agent_harness.toolkits.memory.types",
                fromlist=["ProceduralMemory"],
            ).ProceduralMemory(
                content="test",
                trigger="t",
                action="a",
            )
        )
        drained = hook.drain_pending()
        assert len(drained) == 1
        assert len(hook.pending_rules) == 0

    def test_reset_session(self):
        hook = ToolMemoryCaptureHook()
        hook._failure_tracker.record_failure("tool_a")
        hook._failure_tracker.record_failure("tool_a")
        hook.reset_session()
        assert hook._failure_tracker.counts == {}
        assert len(hook.pending_rules) == 0
