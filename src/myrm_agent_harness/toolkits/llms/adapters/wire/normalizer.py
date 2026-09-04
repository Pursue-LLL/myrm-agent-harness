"""Normalize OpenAI Responses API payloads into chat-completions-shaped dicts."""

from __future__ import annotations

from typing import Any


class ResponsesStreamError(Exception):
    """OpenAI Responses API returned a failed or error stream/completion payload."""


def _error_message_from_payload(error: object) -> str | None:
    if isinstance(error, str) and error.strip():
        return error.strip()
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            code = error.get("code")
            if isinstance(code, str) and code.strip():
                return f"{code}: {message.strip()}"
            return message.strip()
    return None


def extract_responses_stream_error(event: dict[str, Any]) -> str | None:
    """Return a human-readable API error from a Responses SSE event, if present."""
    event_type = str(event.get("type") or "").lower()

    if event_type == "error" or event_type.endswith(".error"):
        direct = _error_message_from_payload(event.get("error"))
        if direct:
            return direct

    if "failed" in event_type:
        response = event.get("response")
        if isinstance(response, dict):
            nested = _error_message_from_payload(response.get("error"))
            if nested:
                return nested
        top_level = _error_message_from_payload(event.get("error"))
        if top_level:
            return top_level

    if "response.completed" in event_type or event_type.endswith("response_completed"):
        response = event.get("response")
        if isinstance(response, dict) and response.get("status") == "failed":
            nested = _error_message_from_payload(response.get("error"))
            if nested:
                return nested

    return None


def assert_responses_payload_not_failed(response: dict[str, Any]) -> None:
    """Raise when a non-stream Responses payload reports failed status."""
    if response.get("status") != "failed":
        return
    message = _error_message_from_payload(response.get("error"))
    if message:
        raise ResponsesStreamError(message)
    raise ResponsesStreamError("Responses API request failed")


def _extract_output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
    return "".join(parts)


def _extract_reasoning_summary(response: dict[str, Any]) -> str:
    """Extract plain text summary from reasoning output items, if available."""
    parts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        summary = item.get("summary")
        if isinstance(summary, list):
            for part in summary:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
    return "".join(parts)


def _tool_call_from_function_item(item: dict[str, Any]) -> dict[str, Any] | None:
    call_id = item.get("call_id") or item.get("id")
    name = item.get("name")
    arguments = item.get("arguments") or "{}"
    if not call_id or not name:
        return None
    return {
        "id": str(call_id),
        "type": "function",
        "function": {"name": str(name), "arguments": str(arguments)},
    }


def extract_responses_reasoning_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve reasoning output items (with encrypted_content) for multi-turn replay."""
    preserved: list[dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        entry: dict[str, Any] = {"type": "reasoning"}
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id.strip():
            entry["id"] = item_id
        encrypted = item.get("encrypted_content")
        if isinstance(encrypted, str) and encrypted.strip():
            entry["encrypted_content"] = encrypted
        summary = item.get("summary")
        if isinstance(summary, list) and summary:
            entry["summary"] = summary
        if len(entry) > 1:
            preserved.append(entry)
    return preserved


def _extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function_call":
            continue
        mapped = _tool_call_from_function_item(item)
        if mapped is not None:
            tool_calls.append(mapped)
    return tool_calls


def _map_usage(usage: dict[str, Any] | None) -> dict[str, int] | None:
    if not usage:
        return None
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total,
    }


def responses_dict_to_chat_completion(response: dict[str, Any]) -> dict[str, Any]:
    """Convert a completed Responses API payload to chat-completions shape for ChatLiteLLM."""
    text = _extract_output_text(response)
    tool_calls = _extract_tool_calls(response)
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    reasoning_summary = _extract_reasoning_summary(response)
    if reasoning_summary:
        message["reasoning_content"] = reasoning_summary
    reasoning_items = extract_responses_reasoning_items(response)
    if reasoning_items:
        message["responses_reasoning_items"] = reasoning_items
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = text or ""
    finish_reason = "tool_calls" if tool_calls else "stop"
    if response.get("status") == "incomplete":
        finish_reason = "length"
    return {
        "id": response.get("id"),
        "object": "chat.completion",
        "model": response.get("model"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": _map_usage(response.get("usage") if isinstance(response.get("usage"), dict) else None),
    }


def _function_call_delta_chunk(
    *,
    call_id: str,
    name: str | None = None,
    arguments_delta: str | None = None,
    index: int = 0,
) -> dict[str, Any]:
    fn_payload: dict[str, Any] = {}
    if name is not None:
        fn_payload["name"] = name
    if arguments_delta is not None:
        fn_payload["arguments"] = arguments_delta
    tool_call: dict[str, Any] = {"index": index, "id": call_id, "type": "function", "function": fn_payload}
    return {"choices": [{"index": 0, "delta": {"tool_calls": [tool_call]}, "finish_reason": None}]}


def responses_event_to_completion_chunk(event: dict[str, Any]) -> dict[str, Any] | None:
    """Map a Responses stream event to a chat completion stream chunk dict."""
    event_type = str(event.get("type") or "")
    normalized_type = event_type.lower()
    delta = event.get("delta")

    if (
        "output_text.delta" in normalized_type
        or normalized_type.endswith("output_text_delta")
    ) and isinstance(delta, str) and delta:
        return {
            "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
        }

    if (
        "reasoning.delta" in normalized_type
        or "reasoning_summary.delta" in normalized_type
        or "reasoning_text.delta" in normalized_type
    ):
        text_delta = delta if isinstance(delta, str) else ""
        if not text_delta and isinstance(delta, dict):
            text_delta = str(delta.get("text") or "")
        if text_delta:
            return {
                "choices": [{"index": 0, "delta": {"reasoning_content": text_delta}, "finish_reason": None}],
            }

    item = event.get("item")
    if isinstance(item, dict) and item.get("type") == "function_call":
        mapped = _tool_call_from_function_item(item)
        if mapped is not None:
            fn = mapped["function"]
            return _function_call_delta_chunk(
                call_id=str(mapped["id"]),
                name=str(fn["name"]),
                arguments_delta=str(fn.get("arguments") or ""),
            )

    if (
        "function_call_arguments.delta" in normalized_type
        or normalized_type.endswith("function_call_arguments_delta")
    ):
        call_id = event.get("call_id") or event.get("item_id")
        if isinstance(call_id, str) and isinstance(delta, str) and delta:
            return _function_call_delta_chunk(call_id=call_id, arguments_delta=delta)

    if "response.completed" in normalized_type or normalized_type.endswith("response_completed"):
        response = event.get("response")
        if isinstance(response, dict):
            tool_calls = _extract_tool_calls(response)
            finish_reason = "tool_calls" if tool_calls else "stop"
            if response.get("status") == "incomplete":
                finish_reason = "length"
            usage = _map_usage(response.get("usage") if isinstance(response.get("usage"), dict) else None)
            chunk: dict[str, Any] = {
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }
            delta: dict[str, Any] = {}
            if tool_calls:
                delta["tool_calls"] = [
                    {
                        "index": idx,
                        "id": tc["id"],
                        "type": "function",
                        # Arguments are streamed via function_call_arguments.delta;
                        # re-emitting them on completed duplicates aggregator state.
                        "function": {"name": str(tc["function"]["name"])},
                    }
                    for idx, tc in enumerate(tool_calls)
                ]
            reasoning_summary = _extract_reasoning_summary(response)
            if reasoning_summary:
                delta["reasoning_content"] = reasoning_summary
            reasoning_items = extract_responses_reasoning_items(response)
            if reasoning_items:
                delta["responses_reasoning_items"] = reasoning_items
            if delta:
                chunk["choices"][0]["delta"] = delta
            if usage:
                chunk["usage"] = usage
            return chunk
    return None
