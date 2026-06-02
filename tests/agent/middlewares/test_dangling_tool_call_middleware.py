"""Unit tests for DanglingToolCallMiddleware."""

from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.dangling_tool_call_middleware import (
    _INTERRUPTED_CONTENT,
    _build_patched_messages,
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
