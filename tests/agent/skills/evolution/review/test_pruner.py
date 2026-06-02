"""Tests for the trajectory pruner (pruner.py).

Validates conversation history compression into skeleton format.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.skills.evolution.review.pruner import (
    _format_args,
    _truncate,
    prune_trajectory,
)


class TestPruneTrajectory:
    """Test the main prune_trajectory function."""

    def test_empty_history_returns_empty_string(self):
        assert prune_trajectory([]) == ""

    def test_single_human_message(self):
        history = [HumanMessage(content="How to fix this bug?")]
        result = prune_trajectory(history)
        assert "<User>: How to fix this bug?" in result

    def test_ai_message_with_thought(self):
        history = [
            HumanMessage(content="Fix the bug"),
            AIMessage(content="Let me check the logs first"),
        ]
        result = prune_trajectory(history)
        assert "<AI-Thought>: Let me check the logs first" in result

    def test_ai_message_with_tool_call(self):
        history = [
            HumanMessage(content="Search files"),
            AIMessage(
                content="Searching...",
                tool_calls=[{"name": "bash", "args": {"cmd": "grep error log.txt"}, "id": "c1"}],
            ),
        ]
        result = prune_trajectory(history)
        assert "<Tool-Call>: bash(cmd='grep error log.txt')" in result

    def test_tool_message_result(self):
        history = [
            HumanMessage(content="Search"),
            AIMessage(
                content="",
                tool_calls=[{"name": "search", "args": {"q": "test"}, "id": "c1"}],
            ),
            ToolMessage(content="Found 3 results", tool_call_id="c1", name="search"),
        ]
        result = prune_trajectory(history)
        assert "<Tool-Result[search]>: Found 3 results" in result

    def test_truncates_long_tool_results(self):
        long_content = "x" * 500
        history = [
            ToolMessage(content=long_content, tool_call_id="c1", name="bash"),
        ]
        result = prune_trajectory(history, max_tool_result_length=100)
        assert "...(truncated)" in result
        assert len(result) < 500

    def test_truncates_long_thoughts(self):
        long_thought = "thinking " * 200
        history = [
            AIMessage(content=long_thought),
        ]
        result = prune_trajectory(history, max_thought_length=50)
        assert "...(truncated)" in result

    def test_full_conversation_flow(self):
        history = [
            HumanMessage(content="How to debug this?"),
            AIMessage(
                content="I'll check the error logs",
                tool_calls=[{"name": "bash", "args": {"cmd": "tail -n 20 error.log"}, "id": "c1"}],
            ),
            ToolMessage(
                content="[2026-05-25] ERROR: Connection refused",
                tool_call_id="c1",
                name="bash",
            ),
            AIMessage(content="The issue is a connection error. Let me fix it."),
        ]
        result = prune_trajectory(history)
        lines = result.strip().split("\n")
        assert len(lines) == 5
        assert lines[0].startswith("<User>:")
        assert lines[1].startswith("<AI-Thought>:")
        assert lines[2].startswith("<Tool-Call>:")
        assert lines[3].startswith("<Tool-Result[bash]>:")
        assert lines[4].startswith("<AI-Thought>:")

    def test_ai_message_without_content(self):
        history = [
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": "/a/b.py"}, "id": "c1"}],
            ),
        ]
        result = prune_trajectory(history)
        assert "<AI-Thought>" not in result
        assert "<Tool-Call>: read_file(path='/a/b.py')" in result

    def test_multiple_tool_calls_in_one_message(self):
        history = [
            AIMessage(
                content="Running parallel tasks",
                tool_calls=[
                    {"name": "bash", "args": {"cmd": "ls"}, "id": "c1"},
                    {"name": "read", "args": {"path": "a.py"}, "id": "c2"},
                ],
            ),
        ]
        result = prune_trajectory(history)
        assert "<Tool-Call>: bash(cmd='ls')" in result
        assert "<Tool-Call>: read(path='a.py')" in result


class TestTruncate:
    """Test the _truncate helper."""

    def test_no_truncation_needed(self):
        assert _truncate("short", 100) == "short"

    def test_truncation_applies(self):
        result = _truncate("a" * 20, 10)
        assert result == "a" * 10 + "...(truncated)"
        assert len(result) == 10 + len("...(truncated)")

    def test_exact_boundary(self):
        assert _truncate("12345", 5) == "12345"

    def test_one_over_boundary(self):
        result = _truncate("123456", 5)
        assert result == "12345...(truncated)"


class TestFormatArgs:
    """Test the _format_args helper."""

    def test_empty_args(self):
        assert _format_args({}) == ""

    def test_string_arg(self):
        result = _format_args({"cmd": "ls -la"})
        assert result == "cmd='ls -la'"

    def test_dict_arg(self):
        result = _format_args({"config": {"key": "value"}})
        assert result == "config={...}"

    def test_list_arg(self):
        result = _format_args({"items": [1, 2, 3]})
        assert result == "items=[...]"

    def test_int_arg(self):
        result = _format_args({"limit": 10})
        assert result == "limit=10"

    def test_multiple_args(self):
        result = _format_args({"cmd": "grep", "path": "/tmp"})
        assert "cmd='grep'" in result
        assert "path='/tmp'" in result

    def test_long_string_arg_truncated(self):
        long_val = "x" * 100
        result = _format_args({"data": long_val})
        assert "...(truncated)" in result
