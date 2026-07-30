"""Tests for retention_helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.retention_helpers import (
    build_tool_call_group_by_id,
    effective_keep_recent_calls,
    extract_failed_tool_call_ids,
    extract_focus_files,
    extract_focus_modules,
    extract_user_goal_hint,
    find_keep_recent_prune_cutoff,
    should_retain_tool_message,
    tool_message_matches_focus_signals,
)
from myrm_agent_harness.agent.context_management.strategies.tool_call_groups import build_tool_call_groups


def test_extract_failed_tool_call_ids_invalid_shape() -> None:
    assert extract_failed_tool_call_ids({}) == frozenset()
    assert extract_failed_tool_call_ids({"compression_intent": "bad"}) == frozenset()
    assert extract_failed_tool_call_ids({"compression_intent": {"failed_tool_call_ids": "bad"}}) == frozenset()
    metadata = {
        "compression_intent": {
            "failed_tool_call_ids": ["call_1", "", 123],
        }
    }
    assert extract_failed_tool_call_ids(metadata) == frozenset({"call_1"})


def test_should_retain_tool_message_for_failed_id() -> None:
    msg = ToolMessage(content="ok", tool_call_id="call_failed", name="bash")
    assert should_retain_tool_message(msg, frozenset({"call_failed"})) is True


def test_should_retain_tool_message_for_error_heuristic() -> None:
    msg = ToolMessage(
        content="Traceback (most recent call last):\nValueError: boom",
        tool_call_id="call_x",
        name="bash",
    )
    assert should_retain_tool_message(msg, frozenset()) is True


def test_should_retain_tool_message_for_focus_file_signal() -> None:
    msg = ToolMessage(
        content="Read src/app/main.py successfully",
        tool_call_id="call_read",
        name="file_read_tool",
    )
    assert should_retain_tool_message(
        msg,
        frozenset(),
        focus_files=frozenset({"src/app/main.py"}),
    ) is True


def test_should_retain_tool_message_for_focus_path_in_tool_args_only() -> None:
    messages = [
        HumanMessage(content="review login module"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_read",
                    "name": "file_read_tool",
                    "args": {"path": "src/auth/login.py"},
                }
            ],
        ),
        ToolMessage(
            content="import os\n" + ("def todo_item() -> None:\n    pass\n" * 400),
            tool_call_id="call_read",
            name="file_read_tool",
        ),
    ]
    groups = build_tool_call_groups(messages)
    assert len(groups) == 1
    tool_msg = messages[2]
    assert isinstance(tool_msg, ToolMessage)

    assert should_retain_tool_message(
        tool_msg,
        frozenset(),
        focus_files=frozenset({"src/auth/login.py"}),
        group=groups[0],
    ) is True
    assert should_retain_tool_message(
        tool_msg,
        frozenset(),
        focus_files=frozenset({"src/auth/login.py"}),
    ) is False


def test_should_retain_tool_message_for_goal_hint_in_tool_args_only() -> None:
    messages = [
        HumanMessage(content="fix login timeout"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_bash",
                    "name": "bash_code_execute_tool",
                    "args": {"command": "pytest tests/test_login_timeout.py -q"},
                }
            ],
        ),
        ToolMessage(
            content="FAILED " + ("assert False\n" * 500),
            tool_call_id="call_bash",
            name="bash_code_execute_tool",
        ),
    ]
    groups = build_tool_call_groups(messages)
    assert len(groups) == 1
    tool_msg = messages[2]
    assert isinstance(tool_msg, ToolMessage)

    assert should_retain_tool_message(
        tool_msg,
        frozenset(),
        user_goal_hint="fix login timeout issue",
        group=groups[0],
    ) is True


def test_build_tool_call_group_by_id() -> None:
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "grep_tool", "args": {}}]),
        ToolMessage(content="result1", name="grep_tool", tool_call_id="tc1"),
    ]
    index = build_tool_call_group_by_id(messages)
    assert "tc1" in index
    assert index["tc1"].tool_index == 2


def test_extract_user_goal_hint() -> None:
    assert extract_user_goal_hint({}) == ""
    assert extract_user_goal_hint({"compression_intent": {"user_goal_hint": " fix timeout "}}) == "fix timeout"


def test_tool_message_matches_focus_signals() -> None:
    msg = ToolMessage(content="output from myrm-agent-server/app/main.py", tool_call_id="c1", name="grep")
    assert tool_message_matches_focus_signals(
        msg,
        focus_files=frozenset({"./myrm-agent-server/app/main.py"}),
        focus_modules=frozenset(),
    ) is True


def test_extract_focus_files_and_modules() -> None:
    metadata = {
        "compression_intent": {
            "focus_files": ["src/a.py", ""],
            "focus_modules": ["agent.context", 1],
        }
    }
    assert extract_focus_files(metadata) == frozenset({"src/a.py"})
    assert extract_focus_modules(metadata) == frozenset({"agent.context"})


def test_find_keep_recent_prune_cutoff_protects_recent_groups() -> None:
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "grep_tool", "args": {}}]),
        ToolMessage(content="result1", name="grep_tool", tool_call_id="tc1"),
        AIMessage(content="", tool_calls=[{"id": "tc2", "name": "web_search", "args": {}}]),
        ToolMessage(content="result2", name="web_search", tool_call_id="tc2"),
    ]
    assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 2


def test_find_keep_recent_prune_cutoff_with_many_groups() -> None:
    messages: list = [HumanMessage(content="hi")]
    for i in range(6):
        tc_id = f"tc{i}"
        messages.append(
            AIMessage(content="", tool_calls=[{"id": tc_id, "name": "tool", "args": {}}])
        )
        messages.append(ToolMessage(content=f"result{i}", name="tool", tool_call_id=tc_id))

    # keep 5 of 6 groups -> first protected group is tc1 at message index 4
    assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=5) == 4


def test_find_keep_recent_prune_cutoff_zero_disables_prune() -> None:
    messages = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"id": "tc1", "name": "grep_tool", "args": {}}]),
        ToolMessage(content="result1", name="grep_tool", tool_call_id="tc1"),
    ]
    assert find_keep_recent_prune_cutoff(messages, keep_recent_calls=0) == 3


def test_effective_keep_recent_calls_eco_mode() -> None:
    assert effective_keep_recent_calls(keep_recent_calls=5, eco_mode=True) == 3
    assert effective_keep_recent_calls(keep_recent_calls=2, eco_mode=True) == 2
    assert effective_keep_recent_calls(keep_recent_calls=5, eco_mode=False) == 5
