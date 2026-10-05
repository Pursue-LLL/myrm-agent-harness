"""Unit tests for DanglingToolCallMiddleware."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.tooling.dangling_tool_call_middleware import (
    _INTERRUPTED_MUTATION_CONTENT,
    _INTERRUPTED_SAFE_CONTENT,
    _MAX_ERROR_DETAIL_LEN,
    _build_patched_messages,
    _extract_tool_calls,
    dangling_tool_call_middleware,
)


class TestBuildPatchedMessages:
    """Tests for the pure _build_patched_messages function."""

    def test_no_dangling_returns_none(self):
        """No dangling tool_calls → returns None (no patching needed)."""
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="hi"),
        ]
        assert _build_patched_messages(messages) is None

    def test_complete_tool_call_pair_returns_none(self):
        """AIMessage with tool_calls + matching ToolMessages → no patching."""
        messages = [
            HumanMessage(content="search for cats"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc_1", "name": "web_search", "args": {"q": "cats"}}],
            ),
            ToolMessage(content="Found cats", tool_call_id="tc_1", name="web_search"),
            AIMessage(content="Here are the results."),
        ]
        assert _build_patched_messages(messages) is None

    def test_single_dangling_tool_call(self):
        """One AIMessage with a dangling tool_call → one synthetic ToolMessage inserted."""
        messages = [
            HumanMessage(content="search for cats"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc_1", "name": "web_search_tool", "args": {"q": "cats"}}],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 3

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "tc_1"
        assert synthetic.name == "web_search_tool"
        assert synthetic.content == _INTERRUPTED_SAFE_CONTENT
        assert synthetic.status == "success"

    def test_single_dangling_mutation_tool_call(self):
        """Mutation tool (bash/write) gets error status and mutation content."""
        messages = [
            HumanMessage(content="run command"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tc_mut_1",
                        "name": "bash_code_execute_tool",
                        "args": {"command": "rm -rf /tmp/test"},
                    }
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 3

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "tc_mut_1"
        assert synthetic.name == "bash_code_execute_tool"
        assert synthetic.content == _INTERRUPTED_MUTATION_CONTENT
        assert synthetic.status == "error"

    def test_multiple_dangling_in_same_ai_message(self):
        """AIMessage with multiple dangling tool_calls → all get synthetic ToolMessages."""
        messages = [
            HumanMessage(content="do two things"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc_1", "name": "web_search", "args": {"q": "a"}},
                    {"id": "tc_2", "name": "file_read", "args": {"path": "/tmp"}},
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 4

        assert isinstance(patched[2], ToolMessage)
        assert patched[2].tool_call_id == "tc_1"
        assert patched[2].name == "web_search"

        assert isinstance(patched[3], ToolMessage)
        assert patched[3].tool_call_id == "tc_2"
        assert patched[3].name == "file_read"

    def test_partial_completion(self):
        """Some tool_calls have ToolMessages, some don't → only missing ones patched."""
        messages = [
            HumanMessage(content="do two things"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc_1", "name": "web_search", "args": {"q": "a"}},
                    {"id": "tc_2", "name": "file_read", "args": {"path": "/tmp"}},
                ],
            ),
            ToolMessage(content="search result", tool_call_id="tc_1", name="web_search"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 4

        assert patched[0] == messages[0]
        assert patched[1] == messages[1]

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "tc_2"
        assert synthetic.name == "file_read"

        assert patched[3] == messages[2]

    def test_multiple_dangling_ai_messages(self):
        """Multiple interrupted turns in history → all dangling calls patched."""
        messages = [
            HumanMessage(content="first"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "tool_a", "args": {}}]),
            HumanMessage(content="second"),
            AIMessage(content="", tool_calls=[{"id": "tc_2", "name": "tool_b", "args": {}}]),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 6

        assert isinstance(patched[2], ToolMessage)
        assert patched[2].tool_call_id == "tc_1"

        assert isinstance(patched[5], ToolMessage)
        assert patched[5].tool_call_id == "tc_2"

    def test_ai_message_without_tool_calls_ignored(self):
        """AIMessage with no tool_calls is not affected."""
        messages = [
            HumanMessage(content="hello"),
            AIMessage(content="world"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "search", "args": {}}]),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 4

        assert patched[0] == messages[0]
        assert patched[1] == messages[1]
        assert patched[2] == messages[2]
        assert isinstance(patched[3], ToolMessage)
        assert patched[3].tool_call_id == "tc_1"

    def test_empty_messages(self):
        """Empty message list → no patching."""
        assert _build_patched_messages([]) is None

    def test_orphan_tool_message_is_dropped(self):
        """ToolMessage without any matching AI tool_call should be dropped."""
        messages = [
            HumanMessage(content="hello"),
            ToolMessage(content="orphan", tool_call_id="ghost_1", name="ghost"),
            AIMessage(content="world"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 2
        assert all(not isinstance(msg, ToolMessage) for msg in patched)

    def test_malformed_tool_call_is_sanitized(self):
        """Malformed tool_call name/args are sanitized before synthetic patching."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"id": "tc_1", "name": "placeholder", "args": {}}],
        )
        # Build with valid schema first, then inject malformed payload to validate sanitizer behavior.
        ai_msg.tool_calls = [{"id": "tc_1", "name": "", "args": "not_json"}]
        messages = [
            HumanMessage(content="run"),
            ai_msg,
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 3
        ai_msg = patched[1]
        assert isinstance(ai_msg, AIMessage)
        assert ai_msg.tool_calls[0]["name"] == "unknown"
        assert ai_msg.tool_calls[0]["args"] == {}
        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "tc_1"

    def test_idempotent_on_already_patched(self):
        """Running on already-patched messages produces no new patches."""
        messages = [
            HumanMessage(content="search"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "search", "args": {}}]),
        ]
        first_patch = _build_patched_messages(messages)
        assert first_patch is not None

        second_patch = _build_patched_messages(first_patch)
        assert second_patch is None

    def test_synthetic_message_position_after_ai(self):
        """Synthetic ToolMessage is inserted right after the dangling AIMessage,
        not at the end of the list."""
        messages = [
            HumanMessage(content="first"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "tool_a", "args": {}}]),
            HumanMessage(content="second"),
            AIMessage(content="response"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 5

        assert patched[0] == messages[0]
        assert patched[1] == messages[1]
        assert isinstance(patched[2], ToolMessage)
        assert patched[2].tool_call_id == "tc_1"
        assert patched[3] == messages[2]
        assert patched[4] == messages[3]


class TestInvalidToolCalls:
    """Tests for invalid_tool_calls and additional_kwargs.tool_calls handling."""

    def test_invalid_tool_calls_detected_as_dangling(self):
        """AIMessage with invalid_tool_calls (malformed JSON) → synthetic ToolMessage."""
        messages = [
            HumanMessage(content="write a file"),
            AIMessage(
                content="Let me write that.",
                tool_calls=[],
                invalid_tool_calls=[
                    {
                        "name": "write_file",
                        "args": "broken json",
                        "id": "call_invalid_1",
                        "error": "JSON parse failed",
                    }
                ],
            ),
            HumanMessage(content="try again"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 4

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "call_invalid_1"
        assert synthetic.name == "write_file"
        assert synthetic.status == "error"
        assert "invalid" in synthetic.content.lower()

    def test_invalid_tool_calls_with_error_detail(self):
        """Structured parse diagnosis is included in the synthetic content."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[
                    {
                        "name": "bash",
                        "args": "{broken",
                        "id": "call_err_1",
                        "error": "Expected comma in JSON at position 42",
                    }
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        synthetic = patched[2]
        assert "failed to parse" in synthetic.content
        assert synthetic.status == "error"

    def test_invalid_tool_calls_error_truncation(self):
        """Huge error details are truncated to _MAX_ERROR_DETAIL_LEN."""
        huge_error = "x" * 2000
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[
                    {
                        "name": "write_file",
                        "args": "broken",
                        "id": "call_big_1",
                        "error": huge_error,
                    }
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        synthetic = patched[2]
        assert len(synthetic.content) < _MAX_ERROR_DETAIL_LEN + 100

    def test_mixed_valid_and_invalid_tool_calls(self):
        """Both tool_calls and invalid_tool_calls present → both handled."""
        messages = [
            HumanMessage(content="do stuff"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc_valid", "name": "search", "args": {"q": "test"}}],
                invalid_tool_calls=[
                    {
                        "name": "write_file",
                        "args": "bad",
                        "id": "tc_invalid",
                        "error": "parse error",
                    }
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None

        tool_msgs = [m for m in patched if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 2
        ids = {m.tool_call_id for m in tool_msgs}
        assert ids == {"tc_valid", "tc_invalid"}

    def test_additional_kwargs_tool_calls_fallback(self):
        """Raw provider tool_calls in additional_kwargs detected when standard fields empty."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="Processing...",
                tool_calls=[],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "raw_call_1",
                            "type": "function",
                            "function": {"name": "terminal", "arguments": "{}"},
                        }
                    ]
                },
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "raw_call_1"
        assert synthetic.name == "terminal"
        assert synthetic.content == _INTERRUPTED_MUTATION_CONTENT

    def test_additional_kwargs_not_used_when_standard_fields_populated(self):
        """additional_kwargs.tool_calls is NOT used when msg.tool_calls is populated."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc_standard", "name": "search", "args": {}}],
                additional_kwargs={
                    "tool_calls": [
                        {
                            "id": "raw_ignored",
                            "type": "function",
                            "function": {"name": "x", "arguments": "{}"},
                        }
                    ]
                },
            ),
            ToolMessage(content="ok", tool_call_id="tc_standard", name="search"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is None

    def test_invalid_tool_calls_already_answered(self):
        """Answered invalid calls are still quarantined (upgrade), but never double-patched."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[{"name": "fn", "args": "bad", "id": "tc_answered", "error": "err"}],
            ),
            ToolMessage(content="handled", tool_call_id="tc_answered", name="fn"),
        ]
        patched = _build_patched_messages(messages)
        # Quarantine must still upgrade the declaration (poison isolation runs
        # even when a ToolMessage already exists), so a patch is produced.
        assert patched is not None
        upgraded = patched[1]
        assert getattr(upgraded, "invalid_tool_calls", None) == []
        assert [tc["id"] for tc in upgraded.tool_calls] == ["tc_answered"]
        # No synthetic ToolMessage appended — the real answer already pairs it.
        assert len(patched) == 3
        assert patched[2].content == "handled"


class TestExtractToolCalls:
    """Tests for the _extract_tool_calls helper."""

    def test_standard_tool_calls(self):
        msg = AIMessage(content="", tool_calls=[{"id": "a", "name": "fn", "args": {}}])
        result = _extract_tool_calls(msg)
        assert result == [("a", "fn")]

    def test_additional_kwargs_fallback(self):
        msg = AIMessage(
            content="",
            additional_kwargs={"tool_calls": [{"id": "c", "function": {"name": "raw_fn", "arguments": "{}"}}]},
        )
        result = _extract_tool_calls(msg)
        assert result == [("c", "raw_fn")]

    def test_deduplication(self):
        """Same ID in both tool_calls and invalid_tool_calls → the valid
        declaration wins; quarantine clears the invalid bucket upstream, and
        extraction never re-reads it (no duplicate double declaration)."""
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "dup", "name": "fn", "args": {}}],
            invalid_tool_calls=[{"id": "dup", "name": "fn", "args": "x", "error": "e"}],
        )
        result = _extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0][0] == "dup"


class TestDanglingToolCallMiddlewareAsync:
    """Tests for the async middleware entry point."""

    async def test_patches_dangling_and_calls_handler(self):
        """Middleware patches dangling calls and forwards to handler."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "search", "args": {}}]),
        ]
        sentinel = MagicMock()
        handler = AsyncMock(return_value=sentinel)

        request = MagicMock()
        request.messages = messages
        patched_request = MagicMock()
        request.override.return_value = patched_request

        result = await dangling_tool_call_middleware.awrap_model_call(request, handler)

        request.override.assert_called_once()
        patched_msgs = request.override.call_args.kwargs["messages"]
        assert len(patched_msgs) == 3
        assert isinstance(patched_msgs[2], ToolMessage)
        handler.assert_awaited_once_with(patched_request)
        assert result is sentinel

    async def test_no_patch_passes_original_request(self):
        """When no dangling calls, handler receives the original request."""
        messages = [HumanMessage(content="hello"), AIMessage(content="hi")]
        sentinel = MagicMock()
        handler = AsyncMock(return_value=sentinel)

        request = MagicMock()
        request.messages = messages

        result = await dangling_tool_call_middleware.awrap_model_call(request, handler)

        request.override.assert_not_called()
        handler.assert_awaited_once_with(request)
        assert result is sentinel


class TestWithheldToolCallsPromotion:
    """Streaming aggregation cannot carry invalid_tool_calls across chunk merges,
    so args-recovery-withheld calls arrive as additional_kwargs["tool_call_recovery"]
    with safe=False. The middleware must re-declare them so the model gets a
    structured invalid-args ToolMessage instead of silently losing the turn."""

    @staticmethod
    def _withheld_message() -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[],
            additional_kwargs={
                "tool_call_recovery": [
                    {
                        "tool_call_id": "call_w",
                        "tool_name": "write_file",
                        "strategy": "truncated_stream_unverified",
                        "degraded": True,
                        "safe": False,
                        "raw_arguments": '{"path": "repor',
                        "error": "Tool call arguments for 'write_file' could not be safely parsed",
                    }
                ]
            },
        )

    def test_withheld_call_promoted_to_invalid_args_toolmessage(self):
        messages = [HumanMessage(content="go"), self._withheld_message()]
        patched = _build_patched_messages(messages)
        assert patched is not None
        ai_msg = patched[1]
        assert [tc["id"] for tc in ai_msg.tool_calls] == ["call_w"]
        assert ai_msg.tool_calls[0]["args"] == {}

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "call_w"
        assert synthetic.status == "error"
        assert "could not be safely parsed" in synthetic.content

    def test_withheld_call_promotion_idempotent(self):
        first = _build_patched_messages([HumanMessage(content="go"), self._withheld_message()])
        assert first is not None
        # Re-running on the patched output declares nothing new.
        assert _build_patched_messages(list(first)) is None

    def test_safe_recovery_entries_are_ignored(self):
        msg = AIMessage(
            content="",
            tool_calls=[],
            additional_kwargs={
                "tool_call_recovery": [
                    {"tool_call_id": "call_s", "tool_name": "search", "strategy": "standard_json", "safe": True}
                ]
            },
        )
        assert _build_patched_messages([HumanMessage(content="go"), msg]) is None


class TestReplayIsolation:
    """End-to-end replay-poisoning isolation: malformed tool_call args never
    reach the provider in raw form (langchain serializes invalid_tool_calls
    verbatim), and output is stable across replays."""

    BAD_ARGS = '{"path": "report\ndocs/final.md", "optio'

    @staticmethod
    def _invalid_history() -> list:
        return [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[
                    {
                        "name": "write_file",
                        "args": TestReplayIsolation.BAD_ARGS,
                        "id": "call_bad",
                        "error": "truncated JSON",
                    }
                ],
            ),
        ]

    def test_unrepairable_malformed_args_never_replayed(self):
        """Quarantine rewrites the declaration; raw malformed text is gone."""
        patched = _build_patched_messages(self._invalid_history())
        assert patched is not None
        ai_msg = patched[1]
        assert ai_msg.invalid_tool_calls == []
        upgraded = ai_msg.tool_calls[0]
        assert upgraded["id"] == "call_bad"
        assert upgraded["args"] == {}
        # The malformed raw text must not survive anywhere in the patched history.
        assert self.BAD_ARGS not in str([m.model_dump() for m in patched])

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "call_bad"
        assert synthetic.status == "error"
        assert "failed to parse" in synthetic.content

    def test_repairable_malformed_args_upgraded_with_interrupted_semantics(self):
        """A repairable truncation becomes a well-formed declaration paired
        with interrupted semantics (replay-safety aware), not invalid-args."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[
                    {"name": "write_file", "args": '{"path": "repor', "id": "call_fix", "error": "truncated"}
                ],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        ai_msg = patched[1]
        assert ai_msg.invalid_tool_calls == []
        assert ai_msg.tool_calls[0]["args"] == {"path": "repor"}

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "call_fix"
        assert synthetic.content in (_INTERRUPTED_SAFE_CONTENT, _INTERRUPTED_MUTATION_CONTENT)

    def test_output_stable_across_replays(self):
        """Deterministic isolation: repeated runs produce identical output."""
        first = _build_patched_messages(self._invalid_history())
        second = _build_patched_messages(self._invalid_history())
        assert first is not None and second is not None
        assert str([m.model_dump() for m in first]) == str([m.model_dump() for m in second])

        # Re-running on the patched output itself changes nothing (idempotent).
        assert _build_patched_messages(list(first)) is None

    def test_openai_serialization_contains_no_malformed_text(self):
        """Probe regression: langchain_openai serializes invalid_tool_calls into
        the API request verbatim — after repair, every outbound arguments field
        must be valid JSON with no malformed leftovers."""
        pytest.importorskip("langchain_openai")
        from langchain_openai.chat_models.base import _convert_message_to_dict

        patched = _build_patched_messages(self._invalid_history())
        assert patched is not None
        outbound = _convert_message_to_dict(patched[1])
        calls = outbound.get("tool_calls") or []
        assert calls, "upgraded declaration must be present in outbound payload"
        for call in calls:
            args_text = call["function"]["arguments"]
            assert json.loads(args_text) is not None  # every field must parse
        assert self.BAD_ARGS not in json.dumps(outbound)

    def test_duplicate_id_invalid_entry_never_replayed(self):
        """Probe regression (contract hole): an invalid entry sharing an id
        with a valid call used to survive quarantine — the pipeline reported
        no change and langchain replayed the malformed text as a duplicate-id
        double declaration. Now the invalid bucket is always cleared: the
        valid declaration wins, the malformed text never reaches the
        provider, and the dangling call still gets its synthetic response."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[{"name": "good_tool", "args": {"x": 1}, "id": "c1"}],
                invalid_tool_calls=[{"name": "bad_tool", "args": '{"path": "repor', "id": "c1", "error": "truncated"}],
            ),
        ]
        patched = _build_patched_messages(messages)
        # Clearing the invalid bucket mutates the message → a patch is produced
        # (previously the pipeline returned None and replayed the poison verbatim).
        assert patched is not None
        ai_msg = patched[1]
        assert ai_msg.invalid_tool_calls == []
        assert [tc["id"] for tc in ai_msg.tool_calls] == ["c1"]

        # The dangling declaration gets exactly one synthetic response.
        assert isinstance(patched[2], ToolMessage)
        assert patched[2].tool_call_id == "c1"

        # Malformed raw text must not survive anywhere in the patched history.
        assert '{"path": "repor' not in str([m.model_dump() for m in patched])

    def test_duplicate_id_outbound_single_declaration(self):
        """Probe regression: the outbound payload must carry exactly one
        well-formed declaration per id — no duplicate-id double declaration,
        no malformed arguments (verified against real langchain_openai)."""
        pytest.importorskip("langchain_openai")
        from langchain_openai.chat_models.base import _convert_message_to_dict

        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[{"name": "good_tool", "args": {"x": 1}, "id": "c1"}],
                invalid_tool_calls=[{"name": "bad_tool", "args": '{"path": "repor', "id": "c1", "error": "truncated"}],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        outbound = _convert_message_to_dict(patched[1])
        calls = outbound.get("tool_calls") or []
        ids = [c.get("id") for c in calls]
        assert len(ids) == len(set(ids)), "duplicate-id double declaration sent to API"
        assert ids == ["c1"]
        assert json.loads(calls[0]["function"]["arguments"]) == {"x": 1}
