"""Tests for reasoning_content stamp logic in ChatLiteLLM.

Verifies that _stamp_missing_reasoning_content correctly back-fills empty
reasoning_content on assistant messages for thinking-mode models (DeepSeek,
Kimi, MiMo), while leaving non-thinking models untouched.
"""

from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM


def _make_model(model: str, **kwargs) -> ChatLiteLLM:
    return ChatLiteLLM.model_construct(client=MagicMock(), model=model, **kwargs)


class TestStampMissingReasoningContent:
    """Verify _stamp_missing_reasoning_content behaviour."""

    def test_deepseek_stamps_empty_reasoning_on_bare_assistant(self) -> None:
        model = _make_model("deepseek/deepseek-v4-flash")
        messages = [
            SystemMessage(content="You are helpful."),
            HumanMessage(content="Hi"),
            AIMessage(content="Hello!"),
            HumanMessage(content="Continue"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_kimi_stamps_empty_reasoning_on_bare_assistant(self) -> None:
        model = _make_model(
            "kimi-k2.5",
            custom_llm_provider="kimi-coding",
        )
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
            HumanMessage(content="Thanks"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_mimo_stamps_empty_reasoning_via_base_url(self) -> None:
        model = _make_model(
            "mimo-v2-flash",
            api_base="https://api.xiaomimimo.com/v1",
        )
        messages = [
            HumanMessage(content="Hi"),
            AIMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_gpt4_does_not_stamp(self) -> None:
        model = _make_model("gpt-4o")
        messages = [
            HumanMessage(content="Hi"),
            AIMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert "reasoning_content" not in assistant_msg

    def test_claude_does_not_stamp(self) -> None:
        model = _make_model("anthropic/claude-3.5-sonnet")
        messages = [
            HumanMessage(content="Hi"),
            AIMessage(content="Hello"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert "reasoning_content" not in assistant_msg

    def test_existing_reasoning_content_preserved(self) -> None:
        """Messages that already have reasoning_content should not be overwritten."""
        model = _make_model("deepseek/deepseek-v4-flash")
        ai_msg = AIMessage(
            content="I'll help you.",
            additional_kwargs={"reasoning_content": "Let me think..."},
        )
        messages = [HumanMessage(content="Hi"), ai_msg]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == "Let me think..."

    def test_mixed_messages_only_assistant_stamped(self) -> None:
        """Only assistant messages get stamped; user/system remain unchanged."""
        model = _make_model("deepseek/deepseek-v4-flash")
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="User query"),
            AIMessage(content="Response 1"),
            HumanMessage(content="Follow up"),
            AIMessage(content="Response 2"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        for msg in message_dicts:
            if msg["role"] == "assistant":
                assert "reasoning_content" in msg
            else:
                assert "reasoning_content" not in msg

    def test_empty_messages_no_crash(self) -> None:
        model = _make_model("deepseek/deepseek-v4-flash")
        message_dicts, _ = model._create_message_dicts([], stop=None)
        assert message_dicts == []

    def test_deepseek_via_provider_field(self) -> None:
        model = _make_model("custom-model", custom_llm_provider="deepseek")
        messages = [HumanMessage(content="Hi"), AIMessage(content="Hello")]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_moonshot_via_base_url(self) -> None:
        model = _make_model(
            "moonshot-model",
            api_base="https://api.moonshot.ai/v1",
        )
        messages = [HumanMessage(content="Hi"), AIMessage(content="Hello")]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_qwen_does_not_stamp(self) -> None:
        model = _make_model("qwen/qwen3-72b")
        messages = [HumanMessage(content="Hi"), AIMessage(content="Hello")]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert "reasoning_content" not in assistant_msg

    def test_tool_call_assistant_message_also_stamped(self) -> None:
        """Assistant messages with tool_calls also need reasoning_content."""
        model = _make_model("deepseek/deepseek-v4-flash")
        ai_with_tool = AIMessage(
            content="",
            additional_kwargs={
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"test"}'},
                    }
                ]
            },
        )
        messages = [HumanMessage(content="Search for X"), ai_with_tool]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""
        assert "tool_calls" in assistant_msg

    def test_tool_call_with_existing_reasoning_preserved(self) -> None:
        """Tool-call messages with existing reasoning keep their content."""
        model = _make_model("deepseek/deepseek-v4-flash")
        ai_with_tool_and_reasoning = AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": "I need to search for this",
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            },
        )
        messages = [HumanMessage(content="Find info"), ai_with_tool_and_reasoning]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == "I need to search for this"

    def test_xiaomi_mimo_prefix_model_stamps(self) -> None:
        """xiaomi_mimo/ prefix in model name triggers stamping."""
        model = _make_model("xiaomi_mimo/mimo-v2.5-pro")
        messages = [HumanMessage(content="Hi"), AIMessage(content="Hello")]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msg = next(m for m in message_dicts if m["role"] == "assistant")
        assert assistant_msg["reasoning_content"] == ""

    def test_multiple_assistant_messages_all_stamped(self) -> None:
        """In long conversations, all assistant messages get stamped."""
        model = _make_model("deepseek/deepseek-v4-flash")
        messages = [
            HumanMessage(content="Q1"),
            AIMessage(content="A1"),
            HumanMessage(content="Q2"),
            AIMessage(content="A2"),
            HumanMessage(content="Q3"),
            AIMessage(content="A3"),
            HumanMessage(content="Q4"),
        ]
        message_dicts, _ = model._create_message_dicts(messages, stop=None)
        assistant_msgs = [m for m in message_dicts if m["role"] == "assistant"]
        assert len(assistant_msgs) == 3
        for msg in assistant_msgs:
            assert msg["reasoning_content"] == ""
