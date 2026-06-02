"""Tests for token estimation covering all message token-consuming fields."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.utils.token_estimation import (
    estimate_content_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
)


class TestEstimateContentTokens:
    def test_string_content(self) -> None:
        tokens = estimate_content_tokens("Hello world")
        assert tokens > 0

    def test_empty_string(self) -> None:
        assert estimate_content_tokens("") == 0

    def test_list_content_text_block(self) -> None:
        content: list[dict[str, str]] = [{"type": "text", "text": "Hello world"}]
        tokens = estimate_content_tokens(content)
        assert tokens > 0

    def test_list_content_multiple_blocks(self) -> None:
        content: list[dict[str, str]] = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "world"},
        ]
        tokens = estimate_content_tokens(content)
        assert tokens > 0

    def test_list_content_image_block(self) -> None:
        content: list[dict[str, str]] = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
        ]
        tokens = estimate_content_tokens(content)
        assert tokens > 0, "Image items should use fixed estimate"

    def test_list_content_unknown_block(self) -> None:
        content: list[dict[str, str]] = [
            {"type": "custom", "data": "some custom data"},
        ]
        tokens = estimate_content_tokens(content)
        assert tokens > 0, "Unknown blocks should fall back to json.dumps"


class TestEstimateMessageTokens:
    def test_human_message_includes_framing(self) -> None:
        msg = HumanMessage(content="Hello")
        content_only = estimate_content_tokens("Hello")
        full = estimate_message_tokens(msg)
        assert full > content_only, "Should include framing overhead"

    def test_system_message(self) -> None:
        msg = SystemMessage(content="You are helpful")
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_ai_message_with_tool_calls(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"command": "ls -la /tmp", "description": "list files"},
                    "id": "call_abc123",
                }
            ],
        )
        content_tokens = estimate_content_tokens(msg.content)
        full_tokens = estimate_message_tokens(msg)
        assert full_tokens > content_tokens + 4, (
            f"tool_calls args should add tokens: content={content_tokens}, full={full_tokens}"
        )

    def test_ai_message_with_multiple_tool_calls(self) -> None:
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"command": "echo hello"},
                    "id": "call_1",
                },
                {
                    "name": "file_read_tool",
                    "args": {"path": "/tmp/test.py", "line_range": "1-50"},
                    "id": "call_2",
                },
            ],
        )
        tokens = estimate_message_tokens(msg)
        assert tokens > 20, "Multiple tool calls should contribute significant tokens"

    def test_ai_message_without_tool_calls(self) -> None:
        msg = AIMessage(content="I'll help you with that")
        tokens = estimate_message_tokens(msg)
        content_only = estimate_content_tokens("I'll help you with that")
        assert tokens == content_only + 4, "No tool_calls = content + framing only"

    def test_tool_message_includes_metadata(self) -> None:
        msg = ToolMessage(content="Command output: success", tool_call_id="call_abc123", name="bash_code_execute_tool")
        content_only = estimate_content_tokens("Command output: success")
        full = estimate_message_tokens(msg)
        assert full > content_only + 4, f"tool_call_id and name should add tokens: content={content_only}, full={full}"

    def test_tool_message_without_name(self) -> None:
        msg = ToolMessage(content="output", tool_call_id="call_abc123")
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_ai_message_large_args(self) -> None:
        """Simulates a bash tool call with a long code argument."""
        long_code = "import os\n" * 100
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "bash_code_execute_tool",
                    "args": {"command": long_code, "description": "run script"},
                    "id": "call_big",
                }
            ],
        )
        tokens = estimate_message_tokens(msg)
        assert tokens > 200, f"Large args should produce many tokens, got {tokens}"


class TestEstimateMessagesTokens:
    def test_mixed_conversation(self) -> None:
        messages = [
            SystemMessage(content="You are helpful"),
            HumanMessage(content="Run ls"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash_code_execute_tool",
                        "args": {"command": "ls -la"},
                        "id": "call_1",
                    }
                ],
            ),
            ToolMessage(content="file1.txt\nfile2.txt", tool_call_id="call_1", name="bash_code_execute_tool"),
            AIMessage(content="Here are the files"),
        ]
        total = estimate_messages_tokens(messages)
        assert total > 0

        content_only_total = sum(estimate_content_tokens(m.content) for m in messages)
        assert total > content_only_total, (
            f"Full estimation ({total}) should exceed content-only ({content_only_total}) "
            "due to tool_calls, metadata, and framing"
        )

    def test_empty_list(self) -> None:
        assert estimate_messages_tokens([]) == 0

    def test_tool_heavy_conversation(self) -> None:
        """30 tool calls should show significant difference vs content-only."""
        messages: list[SystemMessage | HumanMessage | AIMessage | ToolMessage] = [
            SystemMessage(content="You are an assistant"),
            HumanMessage(content="Build a project"),
        ]
        for i in range(30):
            messages.append(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "bash_code_execute_tool",
                            "args": {
                                "command": f"echo 'step {i}' && npm install package-{i}",
                                "description": f"Install package {i}",
                            },
                            "id": f"call_{i}",
                        }
                    ],
                )
            )
            messages.append(
                ToolMessage(
                    content=f"Successfully installed package-{i}",
                    tool_call_id=f"call_{i}",
                    name="bash_code_execute_tool",
                )
            )

        total = estimate_messages_tokens(messages)
        content_only = sum(estimate_content_tokens(m.content) for m in messages)
        diff = total - content_only

        assert diff > 1000, (
            f"30 tool calls should add >1000 tokens from args+metadata+framing, "
            f"got diff={diff} (total={total}, content_only={content_only})"
        )
