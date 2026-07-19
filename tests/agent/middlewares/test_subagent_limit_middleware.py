"""Tests for SubagentLimitMiddleware.

Validates that the middleware correctly truncates excessive delegate_task
tool calls from LLM responses while preserving non-delegate calls.
"""

from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.middlewares.subagent_limit_middleware import (
    MAX_CONCURRENT_SUBAGENTS,
    _truncate_delegate_calls,
)


def _make_tool_call(name: str, call_id: str, args: dict | None = None) -> dict:
    return {"name": name, "id": call_id, "args": args or {}}


class TestTruncateDelegateCalls:
    def test_no_tool_calls_returns_none(self):
        msg = AIMessage(content="hello")
        result = _truncate_delegate_calls(msg, 3)
        assert result is None

    def test_no_delegate_calls_returns_none(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                _make_tool_call("file_read_tool", "c1"),
                _make_tool_call("grep_tool", "c2"),
            ],
        )
        result = _truncate_delegate_calls(msg, 3)
        assert result is None

    def test_within_limit_returns_none(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                _make_tool_call("delegate_task_tool", "d1", {"task": "a"}),
                _make_tool_call("delegate_task_tool", "d2", {"task": "b"}),
            ],
        )
        result = _truncate_delegate_calls(msg, 3)
        assert result is None

    def test_exactly_at_limit_returns_none(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                _make_tool_call("delegate_task_tool", f"d{i}", {"task": f"t{i}"}) for i in range(MAX_CONCURRENT_SUBAGENTS)
            ],
        )
        result = _truncate_delegate_calls(msg, MAX_CONCURRENT_SUBAGENTS)
        assert result is None

    def test_exceeds_limit_truncates(self):
        tool_calls = [_make_tool_call("delegate_task_tool", f"d{i}", {"task": f"task_{i}"}) for i in range(5)]
        msg = AIMessage(content="spawning", tool_calls=tool_calls)
        result = _truncate_delegate_calls(msg, 3)

        assert result is not None
        delegate_calls = [tc for tc in result.tool_calls if tc["name"] == "delegate_task_tool"]
        assert len(delegate_calls) == 3

    def test_preserves_non_delegate_calls(self):
        tool_calls = [
            _make_tool_call("file_read_tool", "f1"),
            _make_tool_call("delegate_task_tool", "d1", {"task": "a"}),
            _make_tool_call("delegate_task_tool", "d2", {"task": "b"}),
            _make_tool_call("delegate_task_tool", "d3", {"task": "c"}),
            _make_tool_call("delegate_task_tool", "d4", {"task": "d"}),
            _make_tool_call("grep_tool", "g1"),
        ]
        msg = AIMessage(content="", tool_calls=tool_calls)
        result = _truncate_delegate_calls(msg, 2)

        assert result is not None
        names = [tc["name"] for tc in result.tool_calls]
        assert names.count("file_read_tool") == 1
        assert names.count("grep_tool") == 1
        assert names.count("delegate_task_tool") == 2

    def test_single_delegate_with_limit_one(self):
        tool_calls = [
            _make_tool_call("delegate_task_tool", "d1", {"task": "a"}),
            _make_tool_call("delegate_task_tool", "d2", {"task": "b"}),
        ]
        msg = AIMessage(content="", tool_calls=tool_calls)
        result = _truncate_delegate_calls(msg, 1)

        assert result is not None
        delegate_calls = [tc for tc in result.tool_calls if tc["name"] == "delegate_task_tool"]
        assert len(delegate_calls) == 1
        assert delegate_calls[0]["id"] == "d1"

    def test_preserves_content(self):
        tool_calls = [_make_tool_call("delegate_task_tool", f"d{i}", {"task": f"t{i}"}) for i in range(5)]
        msg = AIMessage(content="I will delegate these tasks", tool_calls=tool_calls)
        result = _truncate_delegate_calls(msg, 2)

        assert result is not None
        assert result.content == "I will delegate these tasks"

    def test_batch_mode_delegate_counts_as_single_call(self):
        """mode=batch is one delegate_task_tool call and respects the per-response limit."""
        tool_calls = [
            _make_tool_call("delegate_task_tool", "d1", {"mode": "single", "task": "a"}),
            _make_tool_call(
                "delegate_task_tool",
                "b1",
                {"mode": "batch", "tasks": [{"agent_type": "search", "objective": "x"}]},
            ),
            _make_tool_call("delegate_task_tool", "d2", {"task": "b"}),
            _make_tool_call("delegate_task_tool", "d3", {"task": "c"}),
        ]
        msg = AIMessage(content="", tool_calls=tool_calls)
        result = _truncate_delegate_calls(msg, 2)

        assert result is not None
        delegate_calls = [tc for tc in result.tool_calls if tc["name"] == "delegate_task_tool"]
        assert len(delegate_calls) == 2
