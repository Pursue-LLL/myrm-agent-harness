"""Unit tests for DanglingToolCallMiddleware."""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.dangling_tool_call_middleware import (
    _INTERRUPTED_CONTENT,
    _INVALID_ARGS_CONTENT,
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
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "web_search", "args": {"q": "cats"}}]),
            ToolMessage(content="Found cats", tool_call_id="tc_1", name="web_search"),
            AIMessage(content="Here are the results."),
        ]
        assert _build_patched_messages(messages) is None

    def test_single_dangling_tool_call(self):
        """One AIMessage with a dangling tool_call → one synthetic ToolMessage inserted."""
        messages = [
            HumanMessage(content="search for cats"),
            AIMessage(content="", tool_calls=[{"id": "tc_1", "name": "web_search", "args": {"q": "cats"}}]),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        assert len(patched) == 3

        synthetic = patched[2]
        assert isinstance(synthetic, ToolMessage)
        assert synthetic.tool_call_id == "tc_1"
        assert synthetic.name == "web_search"
        assert synthetic.content == _INTERRUPTED_CONTENT
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
                invalid_tool_calls=[{
                    "name": "write_file",
                    "args": "broken json",
                    "id": "call_invalid_1",
                    "error": "JSON parse failed",
                }],
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
        """Error detail from invalid_tool_calls is included in synthetic content."""
        error_msg = "Expected comma in JSON at position 42"
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[{
                    "name": "bash",
                    "args": "{broken",
                    "id": "call_err_1",
                    "error": error_msg,
                }],
            ),
        ]
        patched = _build_patched_messages(messages)
        assert patched is not None
        synthetic = patched[2]
        assert error_msg in synthetic.content

    def test_invalid_tool_calls_error_truncation(self):
        """Huge error details are truncated to _MAX_ERROR_DETAIL_LEN."""
        huge_error = "x" * 2000
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[],
                invalid_tool_calls=[{
                    "name": "write_file",
                    "args": "broken",
                    "id": "call_big_1",
                    "error": huge_error,
                }],
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
                invalid_tool_calls=[{
                    "name": "write_file",
                    "args": "bad",
                    "id": "tc_invalid",
                    "error": "parse error",
                }],
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
        assert synthetic.content == _INTERRUPTED_CONTENT

    def test_additional_kwargs_not_used_when_standard_fields_populated(self):
        """additional_kwargs.tool_calls is NOT used when msg.tool_calls is populated."""
        messages = [
            HumanMessage(content="go"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc_standard", "name": "search", "args": {}}],
                additional_kwargs={
                    "tool_calls": [{"id": "raw_ignored", "type": "function", "function": {"name": "x", "arguments": "{}"}}]
                },
            ),
            ToolMessage(content="ok", tool_call_id="tc_standard", name="search"),
        ]
        patched = _build_patched_messages(messages)
        assert patched is None

    def test_invalid_tool_calls_already_answered(self):
        """invalid_tool_calls with existing ToolMessage → no patching needed."""
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
        assert patched is None


class TestExtractToolCalls:
    """Tests for the _extract_tool_calls helper."""

    def test_standard_tool_calls(self):
        msg = AIMessage(content="", tool_calls=[{"id": "a", "name": "fn", "args": {}}])
        result = _extract_tool_calls(msg)
        assert result == [("a", "fn", False)]

    def test_invalid_tool_calls(self):
        msg = AIMessage(content="", invalid_tool_calls=[{"id": "b", "name": "bad_fn", "args": "x", "error": "e"}])
        result = _extract_tool_calls(msg)
        assert result == [("b", "bad_fn", True)]

    def test_additional_kwargs_fallback(self):
        msg = AIMessage(
            content="",
            additional_kwargs={"tool_calls": [{"id": "c", "function": {"name": "raw_fn", "arguments": "{}"}}]},
        )
        result = _extract_tool_calls(msg)
        assert result == [("c", "raw_fn", False)]

    def test_deduplication(self):
        """Same ID in both tool_calls and invalid_tool_calls → only counted once."""
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
