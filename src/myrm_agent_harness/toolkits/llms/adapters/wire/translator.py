"""LangChain/OpenAI chat messages ↔ OpenAI Responses API input translator."""

from __future__ import annotations

import hashlib
import json
from typing import Any

ResponsesRole = str

MUSE_SPARK_MIN_OUTPUT_TOKENS = 512
_MAX_RESPONSES_CALL_ID_LENGTH = 64


def resolve_min_output_tokens(requested: int | None) -> int:
    """Floor output budget for reasoning models that consume tokens before text."""
    base = requested if requested is not None and requested > 0 else 1024
    return max(MUSE_SPARK_MIN_OUTPUT_TOKENS, base)


def _normalize_role(raw_role: object) -> ResponsesRole:
    role = str(raw_role or "user")
    if role in {"assistant", "system"}:
        return role
    return "user"


def _content_part_type(role: ResponsesRole) -> str:
    return "output_text" if role == "assistant" else "input_text"


def _map_content_part(part: object, role: ResponsesRole) -> dict[str, str]:
    part_type = _content_part_type(role)
    if isinstance(part, str):
        return {"type": part_type, "text": part}
    if isinstance(part, dict):
        ptype = part.get("type")
        text = part.get("text")
        if ptype == "text" and isinstance(text, str):
            return {"type": part_type, "text": text}
        if ptype == "input_text" and isinstance(text, str):
            mapped = "output_text" if role == "assistant" else "input_text"
            return {"type": mapped, "text": text}
        if ptype == "output_text" and isinstance(text, str):
            return {"type": "output_text", "text": text}
    return {"type": part_type, "text": json.dumps(part, ensure_ascii=False)}


def _content_to_parts(content: object, role: ResponsesRole) -> tuple[list[dict[str, str]], str]:
    if isinstance(content, str):
        return [{"type": _content_part_type(role), "text": content}], content
    if isinstance(content, list):
        parts = [_map_content_part(part, role) for part in content]
        text_type = _content_part_type(role)
        text = "".join(p.get("text", "") for p in parts if p.get("type") == text_type)
        return parts, text
    serialized = json.dumps(content, ensure_ascii=False)
    return [{"type": _content_part_type(role), "text": serialized}], serialized


def _deterministic_call_id(fn_name: str, arguments: str, index: int) -> str:
    digest = hashlib.sha256(f"{fn_name}:{arguments}:{index}".encode()).hexdigest()[:48]
    return f"call_{digest}"


def _clamp_responses_call_id(call_id: str) -> str:
    trimmed = call_id.strip()
    if len(trimmed) <= _MAX_RESPONSES_CALL_ID_LENGTH:
        return trimmed
    return trimmed[:_MAX_RESPONSES_CALL_ID_LENGTH]


def _normalize_tool_arguments(raw_arguments: object) -> str:
    if isinstance(raw_arguments, dict):
        return json.dumps(raw_arguments, ensure_ascii=False)
    if isinstance(raw_arguments, str):
        return raw_arguments.strip() or "{}"
    return str(raw_arguments or "{}")


def _append_responses_reasoning_items(result: list[dict[str, Any]], msg: dict[str, Any]) -> None:
    items = msg.get("responses_reasoning_items")
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict) and item.get("type") == "reasoning":
            result.append(dict(item))


def _append_assistant_message(
    result: list[dict[str, Any]],
    msg: dict[str, Any],
    *,
    content: object,
) -> None:
    _append_responses_reasoning_items(result, msg)
    role = "assistant"
    parts, text = _content_to_parts(content, role)
    if parts:
        result.append({"role": role, "content": parts})
    elif text.strip():
        result.append({"role": role, "content": text})

    tool_calls = msg.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for index, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        fn_name = fn.get("name")
        if not isinstance(fn_name, str) or not fn_name.strip():
            continue
        call_id = tc.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            arguments = _normalize_tool_arguments(fn.get("arguments", "{}"))
            call_id = _deterministic_call_id(fn_name, arguments, len(result) + index)
        arguments = _normalize_tool_arguments(fn.get("arguments", "{}"))
        result.append(
            {
                "type": "function_call",
                "call_id": _clamp_responses_call_id(call_id),
                "name": fn_name.strip(),
                "arguments": arguments,
            }
        )


def _append_tool_output(result: list[dict[str, Any]], msg: dict[str, Any]) -> None:
    raw_tool_call_id = msg.get("tool_call_id")
    if not isinstance(raw_tool_call_id, str) or not raw_tool_call_id.strip():
        return
    tool_content = msg.get("content")
    if isinstance(tool_content, list):
        converted = _content_to_parts(tool_content, "user")[0]
        output_value: object = converted if converted else ""
    else:
        output_value = str(tool_content or "")
    result.append(
        {
            "type": "function_call_output",
            "call_id": _clamp_responses_call_id(raw_tool_call_id),
            "output": output_value,
        }
    )


def chat_messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-style chat message dicts to Responses API input items."""
    result: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        if role == "system":
            continue
        if role == "tool":
            _append_tool_output(result, msg)
            continue
        if role == "assistant":
            _append_assistant_message(result, msg, content=msg.get("content", ""))
            continue

        normalized_role = _normalize_role(role)
        parts, text = _content_to_parts(msg.get("content", ""), normalized_role)
        if parts:
            result.append({"role": normalized_role, "content": parts})
        else:
            result.append({"role": normalized_role, "content": text})
    return result


def extract_responses_instructions(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """Promote leading system message to Responses ``instructions`` when present."""
    if not messages:
        return None, []
    first = messages[0]
    if str(first.get("role")) != "system":
        return None, messages
    content = first.get("content")
    if isinstance(content, str):
        instructions = content
    elif isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        instructions = "\n".join(texts)
    else:
        instructions = json.dumps(content, ensure_ascii=False)
    return instructions, messages[1:]
