"""The summary invocation pairs its message prefix the way the agent middleware chain does.

``_guard_aux_context`` trims by message from the head, which can cut an assistant tool request away
from its results. Strict providers reject orphaned tool results (HTTP 400), so the summary call has to
pass the same pairing gate as the main call, while a well-formed prefix stays untouched so the
prompt-cache prefix remains byte-identical.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
    _build_summary_invocation_messages,
    _guard_aux_context,
)

_CONTEXT_LIMIT = "myrm_agent_harness.agent.context_management.strategies.summary.summarizer.get_model_context_limit"


def _call(call_id: str) -> dict[str, object]:
    return {"id": call_id, "name": "grep_tool", "args": {"pattern": call_id}}


def _history() -> list[BaseMessage]:
    """Parallel tool calls, then a single call whose result is empty, then a text answer."""
    return [
        SystemMessage(content="stable system policy"),
        HumanMessage(content="find a and b"),
        AIMessage(content="", tool_calls=[_call("a"), _call("b")]),
        ToolMessage(content="hit a", tool_call_id="a", name="grep_tool"),
        ToolMessage(content="hit b", tool_call_id="b", name="grep_tool"),
        AIMessage(content="found both"),
        HumanMessage(content="now c"),
        AIMessage(content="", tool_calls=[_call("c")]),
        ToolMessage(content="", tool_call_id="c", name="grep_tool"),
        AIMessage(content="c matched nothing"),
    ]


def _pairing_violations(messages: list[BaseMessage]) -> list[str]:
    """Strict-provider pairing: every tool result answers the open request, every request is answered."""
    problems: list[str] = []
    waiting: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage):
            if message.tool_call_id not in waiting:
                problems.append(f"orphan tool result at {index}")
            waiting.discard(message.tool_call_id)
            continue
        if waiting:
            problems.append(f"unanswered tool calls {sorted(waiting)} before {index}")
        waiting = {call["id"] for call in message.tool_calls} if isinstance(message, AIMessage) else set()
    if waiting:
        problems.append(f"unanswered tool calls {sorted(waiting)} at the end")
    return problems


class TestSummaryPrefixPairing:
    def test_every_head_trimmed_window_is_strictly_paired(self) -> None:
        history = _history()
        broken_windows = 0

        for start in range(len(history)):
            window = history[start:]
            invocation = _build_summary_invocation_messages("summarize", window)

            assert _pairing_violations(invocation) == [], f"window starting at message {start}"
            broken_windows += bool(_pairing_violations(window))

        assert broken_windows, "no head-trimmed window breaks pairing, so the assertions above prove nothing"

    def test_prefix_trimmed_by_the_aux_guard_is_strictly_paired(self) -> None:
        history = [
            HumanMessage(content="start"),
            AIMessage(content="plan " * 4000, tool_calls=[_call("a")]),
            ToolMessage(content="hit a", tool_call_id="a", name="grep_tool"),
            AIMessage(content="found it"),
        ]

        with patch(_CONTEXT_LIMIT, return_value=4096):
            guarded = _guard_aux_context(history, MagicMock())
        invocation = _build_summary_invocation_messages("summarize", guarded)

        assert len(guarded) < len(history)
        assert _pairing_violations(guarded), "the guard must orphan a tool result, or this case proves nothing"
        assert _pairing_violations(invocation) == []
        assert invocation[-1].content == "summarize"

    def test_well_formed_prefix_is_sent_unchanged(self) -> None:
        prefix = _history()

        invocation = _build_summary_invocation_messages("summarize", prefix)

        assert len(invocation) == len(prefix) + 1
        assert all(sent is original for sent, original in zip(invocation, prefix, strict=False))

    def test_unanswered_request_is_answered_like_the_main_call(self) -> None:
        prefix = [HumanMessage(content="go"), AIMessage(content="", tool_calls=[_call("a")])]

        invocation = _build_summary_invocation_messages("summarize", prefix)

        assert _pairing_violations(invocation) == []
        answer = invocation[2]
        assert isinstance(answer, ToolMessage)
        assert answer.tool_call_id == "a"

    @pytest.mark.parametrize("prefix", [None, []])
    def test_without_a_prefix_only_the_prompt_is_sent(self, prefix: list[BaseMessage] | None) -> None:
        invocation = _build_summary_invocation_messages("summarize", prefix)

        assert [message.content for message in invocation] == ["summarize"]
