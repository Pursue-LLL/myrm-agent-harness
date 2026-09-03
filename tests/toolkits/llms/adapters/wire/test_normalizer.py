"""Tests for Responses stream normalizer."""

import pytest

from myrm_agent_harness.toolkits.llms.adapters.wire.normalizer import (
    ResponsesStreamError,
    _error_message_from_payload,
    assert_responses_payload_not_failed,
    extract_responses_reasoning_items,
    extract_responses_stream_error,
    responses_dict_to_chat_completion,
    responses_event_to_completion_chunk,
)


def test_completed_response_maps_tool_calls() -> None:
    payload = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_abc",
                "name": "web_search",
                "arguments": "{\"q\":\"ai\"}",
            }
        ]
    }
    completion = responses_dict_to_chat_completion(payload)
    message = completion["choices"][0]["message"]
    assert completion["choices"][0]["finish_reason"] == "tool_calls"
    assert message["tool_calls"][0]["function"]["name"] == "web_search"


def test_reasoning_items_preserved_on_completion() -> None:
    payload = {
        "output": [
            {
                "type": "reasoning",
                "id": "rs_abc",
                "encrypted_content": "enc_blob",
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "answer"}],
            },
        ]
    }
    items = extract_responses_reasoning_items(payload)
    assert items == [{"type": "reasoning", "id": "rs_abc", "encrypted_content": "enc_blob"}]
    completion = responses_dict_to_chat_completion(payload)
    message = completion["choices"][0]["message"]
    assert message["responses_reasoning_items"] == items


def test_response_completed_includes_reasoning_items_in_delta() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_abc",
                        "encrypted_content": "enc_blob",
                    }
                ],
            },
        }
    )
    assert chunk is not None
    delta = chunk["choices"][0]["delta"]
    assert delta["responses_reasoning_items"][0]["encrypted_content"] == "enc_blob"


def test_function_call_arguments_delta_chunk() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.function_call_arguments.delta",
            "call_id": "call_abc",
            "delta": "{\"q\":",
        }
    )
    assert chunk is not None
    tool_calls = chunk["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["id"] == "call_abc"
    assert tool_calls[0]["function"]["arguments"] == "{\"q\":"


def test_response_completed_with_tool_calls() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_abc",
                        "name": "web_search",
                        "arguments": "{}",
                    }
                ],
            },
        }
    )
    assert chunk is not None
    assert chunk["choices"][0]["finish_reason"] == "tool_calls"
    tool_calls = chunk["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "web_search"


def test_delta_then_completed_does_not_duplicate_arguments() -> None:
    from myrm_agent_harness.toolkits.llms.adapters.streaming import aggregate_tool_call_chunk

    delta_chunk = responses_event_to_completion_chunk(
        {
            "type": "response.function_call_arguments.delta",
            "call_id": "call_abc",
            "delta": '{"q":"ai"}',
        }
    )
    completed_chunk = responses_event_to_completion_chunk(
        {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_abc",
                        "name": "web_search",
                        "arguments": '{"q":"ai"}',
                    }
                ],
            },
        }
    )
    assert delta_chunk is not None
    assert completed_chunk is not None

    aggregated: list[dict[str, object]] = []
    for chunk in (delta_chunk, completed_chunk):
        raw_tool_calls = chunk["choices"][0].get("delta", {}).get("tool_calls")
        if not raw_tool_calls:
            continue
        from myrm_agent_harness.toolkits.llms.adapters.streaming import build_tool_call_chunks

        for tc_chunk in build_tool_call_chunks(raw_tool_calls, None):
            aggregate_tool_call_chunk(tc_chunk, aggregated)

    assert len(aggregated) == 1
    assert aggregated[0]["function"]["arguments"] == '{"q":"ai"}'


def test_extract_error_from_response_failed_event() -> None:
    message = extract_responses_stream_error(
        {
            "type": "response.failed",
            "response": {
                "status": "failed",
                "error": {"code": "training_not_allowed", "message": "Training not allowed for muse-spark contributor"},
            },
        }
    )
    assert message == "training_not_allowed: Training not allowed for muse-spark contributor"


def test_extract_error_from_error_event() -> None:
    message = extract_responses_stream_error(
        {"type": "error", "error": {"message": "Internal server error"}},
    )
    assert message == "Internal server error"


def test_extract_error_from_completed_failed_response() -> None:
    message = extract_responses_stream_error(
        {
            "type": "response.completed",
            "response": {
                "status": "failed",
                "error": {"message": "data policy error: allowTraining required"},
            },
        }
    )
    assert message == "data policy error: allowTraining required"


def test_assert_responses_payload_not_failed_raises() -> None:
    with pytest.raises(ResponsesStreamError, match="billing_required"):
        assert_responses_payload_not_failed(
            {"status": "failed", "error": {"code": "billing_required", "message": "Insufficient credits"}},
        )


def test_error_payload_with_code_prefix() -> None:
    message = extract_responses_stream_error(
        {"type": "error", "error": {"code": "rate_limit", "message": "Too many requests"}},
    )
    assert message == "rate_limit: Too many requests"


def test_output_text_field_used_when_present() -> None:
    completion = responses_dict_to_chat_completion({"output_text": "direct text"})
    assert completion["choices"][0]["message"]["content"] == "direct text"


def test_reasoning_summary_contributes_to_output_text() -> None:
    completion = responses_dict_to_chat_completion(
        {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "thought"}],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
            ]
        }
    )
    assert "thought" in completion["choices"][0]["message"]["content"]
    assert "answer" in completion["choices"][0]["message"]["content"]


def test_reasoning_item_with_summary_only_is_preserved() -> None:
    items = extract_responses_reasoning_items(
        {
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_sum",
                    "summary": [{"type": "summary_text", "text": "trace"}],
                }
            ]
        }
    )
    assert items == [{"type": "reasoning", "id": "rs_sum", "summary": [{"type": "summary_text", "text": "trace"}]}]


def test_usage_mapping_from_responses_payload() -> None:
    completion = responses_dict_to_chat_completion(
        {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
    )
    assert completion["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_assert_failed_without_error_message_uses_generic() -> None:
    with pytest.raises(ResponsesStreamError, match="Responses API request failed"):
        assert_responses_payload_not_failed({"status": "failed"})


def test_function_call_item_event_maps_to_tool_delta() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.output_item.added",
            "item": {
                "type": "function_call",
                "call_id": "call_item",
                "name": "web_search",
                "arguments": "{}",
            },
        }
    )
    assert chunk is not None
    tool_calls = chunk["choices"][0]["delta"]["tool_calls"]
    assert tool_calls[0]["function"]["name"] == "web_search"


def test_response_completed_incomplete_sets_length_finish_reason() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.completed",
            "response": {
                "status": "incomplete",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "partial"}]}],
            },
        }
    )
    assert chunk is not None
    assert chunk["choices"][0]["finish_reason"] == "length"


def test_error_message_from_plain_string() -> None:
    assert _error_message_from_payload(" plain error ") == "plain error"


def test_non_function_output_items_are_ignored_for_tool_calls() -> None:
    chunk = responses_event_to_completion_chunk(
        {
            "type": "response.completed",
            "response": {
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            },
        }
    )
    assert chunk is not None
    assert chunk["choices"][0]["finish_reason"] == "stop"
    assert chunk["usage"]["total_tokens"] == 3
