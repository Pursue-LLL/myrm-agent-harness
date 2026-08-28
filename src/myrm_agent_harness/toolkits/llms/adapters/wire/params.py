"""Build litellm.responses() kwargs from ChatLiteLLM call params."""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.toolkits.llms.adapters.wire.translator import (
    chat_messages_to_responses_input,
    extract_responses_instructions,
    resolve_min_output_tokens,
)


def build_responses_kwargs(
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Translate chat completion params into Responses API kwargs."""
    instructions, remaining = extract_responses_instructions(message_dicts)
    responses_input = chat_messages_to_responses_input(remaining)

    requested_max = params.get("max_output_tokens") or params.get("max_tokens")
    max_output = resolve_min_output_tokens(
        int(requested_max) if isinstance(requested_max, int) else None
    )

    extra_body = params.get("extra_body") if isinstance(params.get("extra_body"), dict) else {}
    reasoning = extra_body.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning_effort = params.get("reasoning_effort") or extra_body.get("reasoning_effort")
        if reasoning_effort is not None:
            reasoning = {"effort": str(reasoning_effort)}

    kwargs: dict[str, Any] = {
        "model": params.get("model"),
        "input": responses_input,
        "max_output_tokens": max_output,
        "api_key": params.get("api_key"),
        "api_base": params.get("api_base"),
        "stream": bool(params.get("stream")),
    }
    if instructions:
        kwargs["instructions"] = instructions
    if reasoning:
        kwargs["reasoning"] = reasoning
    include = extra_body.get("include")
    if isinstance(include, list) and include:
        kwargs["include"] = include
    if params.get("tools"):
        kwargs["tools"] = params["tools"]
    if params.get("tool_choice") is not None:
        kwargs["tool_choice"] = params["tool_choice"]
    if params.get("temperature") is not None:
        kwargs["temperature"] = params["temperature"]
    if params.get("top_p") is not None:
        kwargs["top_p"] = params["top_p"]
    if params.get("timeout") is not None:
        kwargs["timeout"] = params["timeout"]
    if params.get("force_timeout") is not None:
        kwargs["timeout"] = params["force_timeout"]
    extra_headers = params.get("extra_headers")
    if isinstance(extra_headers, dict):
        kwargs["extra_headers"] = extra_headers
    return kwargs
