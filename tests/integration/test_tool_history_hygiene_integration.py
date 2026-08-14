"""Integration tests for tool history hygiene — real message pipeline, no LLM.

Validates the pre-LLM sanitize chain wired in production:
tool_history_hygiene → dangling_tool_call repair → normalize_messages (direct paths).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.config.llm_safety import normalize_messages
from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import (
    repair_dangling_tool_calls,
)
from myrm_agent_harness.agent.middlewares.tooling.tool_history_hygiene import (
    sanitize_tool_history,
)


def _unwrap_middleware(middleware: object) -> object:
    from myrm_agent_harness.agent.middlewares.sync_hook_parity import SyncHookParityAdapter

    if isinstance(middleware, SyncHookParityAdapter):
        return object.__getattribute__(middleware, "_inner")
    return middleware


class TestBuildMiddlewaresWiring:
    """build_middlewares must wire hygiene before dangling (SSOT: _agent_build.py)."""

    def test_tool_history_hygiene_before_dangling(self) -> None:
        from myrm_agent_harness.agent._internals._agent_build import (
            build_middlewares,
            create_registry,
        )

        middlewares = build_middlewares(create_registry(), [])
        class_names = [type(_unwrap_middleware(mw)).__name__ for mw in middlewares]
        hygiene_idx = class_names.index("ToolHistoryHygieneMiddleware")
        dangling_idx = class_names.index("DanglingToolCallMiddleware")
        assert hygiene_idx < dangling_idx


class TestGraceCallPipeline:
    """stream_recovery._grace_call_summary uses sanitize → repair (real functions)."""

    def test_cross_turn_duplicate_ids_then_dangling_repair(self) -> None:
        messages = [
            HumanMessage(content="run tools"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            ToolMessage(content="a", tool_call_id="call_x", name="grep_tool"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_x", "name": "grep_tool", "args": {}}],
            ),
            # Dangling: second AIMessage never got a ToolMessage response
        ]
        repaired = repair_dangling_tool_calls(sanitize_tool_history(list(messages)))

        ai_ids = [
            tc["id"]
            for m in repaired
            if isinstance(m, AIMessage)
            for tc in (m.tool_calls or [])
        ]
        assert ai_ids == ["call_x", "call_x@2"]
        assert len(ai_ids) == len(set(ai_ids))

        tool_messages = [m for m in repaired if isinstance(m, ToolMessage)]
        assert len(tool_messages) >= 2
        assert tool_messages[0].tool_call_id == "call_x"
        assert tool_messages[1].tool_call_id == "call_x@2"


class TestNormalizeMessagesIntegration:
    """normalize_messages delegates sanitize then enforces strict pairing."""

    def test_duplicate_tool_messages_keep_last_then_pair(self) -> None:
        messages = [
            HumanMessage(content="query"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "bash", "args": {"command": "ls"}}],
            ),
            ToolMessage(content="old", tool_call_id="call_1"),
            ToolMessage(content="new", tool_call_id="call_1"),
        ]
        result = normalize_messages(messages)
        tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == "new"

    def test_within_message_duplicate_ids_via_normalize(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "dup", "name": "a", "args": {}},
                    {"id": "dup", "name": "b", "args": {}},
                ],
            ),
            ToolMessage(content="r1", tool_call_id="dup", name="a"),
            ToolMessage(content="r2", tool_call_id="dup@2", name="b"),
        ]
        result = normalize_messages(messages)
        ai = next(m for m in result if isinstance(m, AIMessage))
        ids = [tc["id"] for tc in ai.tool_calls]
        assert ids == ["dup", "dup@2"]
        tool_ids = [m.tool_call_id for m in result if isinstance(m, ToolMessage)]
        assert tool_ids == ["dup", "dup@2"]
