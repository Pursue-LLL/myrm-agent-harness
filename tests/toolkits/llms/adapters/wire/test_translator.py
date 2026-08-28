"""Tests for wire message translator."""

from myrm_agent_harness.toolkits.llms.adapters.wire.translator import (
    chat_messages_to_responses_input,
    extract_responses_instructions,
    resolve_min_output_tokens,
)


def test_assistant_uses_output_text() -> None:
    messages = [{"role": "assistant", "content": "prior answer"}]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["content"][0]["type"] == "output_text"


def test_tool_message_becomes_function_call_output() -> None:
    messages = [{"role": "tool", "tool_call_id": "call_abc", "content": "result"}]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["type"] == "function_call_output"
    assert converted[0]["call_id"] == "call_abc"
    assert converted[0]["output"] == "result"


def test_assistant_tool_calls_become_function_call_items() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{\"q\":\"ai\"}"},
                }
            ],
        }
    ]
    converted = chat_messages_to_responses_input(messages)
    assert converted[1]["type"] == "function_call"
    assert converted[1]["name"] == "web_search"
    assert converted[1]["call_id"] == "call_123"


def test_two_turn_tool_history() -> None:
    messages = [
        {"role": "user", "content": "search news"},
        {
            "role": "assistant",
            "content": "Searching",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "headline"},
        {"role": "user", "content": "summarize"},
    ]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["role"] == "user"
    assert converted[1]["role"] == "assistant"
    assert converted[2]["type"] == "function_call"
    assert converted[3]["type"] == "function_call_output"
    assert converted[4]["role"] == "user"


def test_system_promoted_to_instructions() -> None:
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]
    instructions, remaining = extract_responses_instructions(messages)
    assert instructions == "You are helpful"
    assert remaining == [{"role": "user", "content": "hi"}]


def test_min_output_tokens_floor() -> None:
    assert resolve_min_output_tokens(64) == 512
    assert resolve_min_output_tokens(1024) == 1024


def test_assistant_reasoning_items_replay_before_message() -> None:
    reasoning_blob = {"type": "reasoning", "id": "rs_abc", "encrypted_content": "enc_blob"}
    messages = [
        {"role": "user", "content": "step 1"},
        {
            "role": "assistant",
            "content": "done",
            "responses_reasoning_items": [reasoning_blob],
        },
        {"role": "user", "content": "step 2"},
    ]
    converted = chat_messages_to_responses_input(messages)
    assert converted[1] == reasoning_blob
    assert converted[2]["role"] == "assistant"
    assert converted[3]["role"] == "user"


def test_tool_call_without_id_gets_deterministic_call_id() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "web_search", "arguments": {"q": "ai"}},
                }
            ],
        }
    ]
    converted = chat_messages_to_responses_input(messages)
    fn_call = next(item for item in converted if item.get("type") == "function_call")
    assert fn_call["name"] == "web_search"
    assert fn_call["call_id"].startswith("call_")


def test_tool_output_with_list_content() -> None:
    messages = [
        {
            "role": "tool",
            "tool_call_id": "call_abc",
            "content": [{"type": "text", "text": "result body"}],
        }
    ]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["type"] == "function_call_output"
    assert converted[0]["output"][0]["text"] == "result body"


def test_developer_role_normalized_to_user() -> None:
    messages = [{"role": "developer", "content": "hello"}]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["role"] == "user"


def test_assistant_multipart_input_text_maps_to_output_text() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "input_text", "text": "mapped"}],
        }
    ]
    converted = chat_messages_to_responses_input(messages)
    assert converted[0]["content"][0]["type"] == "output_text"


def test_long_call_id_is_clamped() -> None:
    long_id = "x" * 80
    messages = [{"role": "tool", "tool_call_id": long_id, "content": "ok"}]
    converted = chat_messages_to_responses_input(messages)
    assert len(converted[0]["call_id"]) == 64


def test_system_instructions_from_list_content() -> None:
    messages = [
        {"role": "system", "content": [{"type": "text", "text": "line1"}, "line2"]},
        {"role": "user", "content": "hi"},
    ]
    instructions, remaining = extract_responses_instructions(messages)
    assert instructions == "line1\nline2"
    assert remaining == [{"role": "user", "content": "hi"}]


def test_non_dict_messages_are_skipped() -> None:
    converted = chat_messages_to_responses_input(["bad", {"role": "user", "content": "ok"}])  # type: ignore[list-item]
    assert converted == [{"role": "user", "content": [{"type": "input_text", "text": "ok"}]}]


def test_tool_message_without_call_id_is_skipped() -> None:
    converted = chat_messages_to_responses_input([{"role": "tool", "content": "orphan"}])
    assert converted == []


def test_assistant_non_dict_tool_calls_are_skipped() -> None:
    messages = [{"role": "assistant", "content": "x", "tool_calls": ["bad"]}]
    converted = chat_messages_to_responses_input(messages)
    assert converted == [{"role": "assistant", "content": [{"type": "output_text", "text": "x"}]}]


def test_assistant_empty_tool_name_is_skipped() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_x", "type": "function", "function": {"name": "  ", "arguments": "{}"}}],
        }
    ]
    converted = chat_messages_to_responses_input(messages)
    assert all(item.get("type") != "function_call" for item in converted)


def test_user_content_json_fallback_for_unknown_part() -> None:
    messages = [{"role": "user", "content": [{"type": "image_url", "url": "http://x"}]}]
    converted = chat_messages_to_responses_input(messages)
    assert "image_url" in converted[0]["content"][0]["text"]


def test_system_instructions_from_non_string_content() -> None:
    messages = [{"role": "system", "content": {"policy": "strict"}}, {"role": "user", "content": "hi"}]
    instructions, remaining = extract_responses_instructions(messages)
    assert instructions == '{"policy": "strict"}'
    assert remaining == [{"role": "user", "content": "hi"}]
