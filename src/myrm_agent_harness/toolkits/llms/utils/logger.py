"""LiteLLM API request/response logging utility

agent/context_management/PROMPT_CACHE_PRACTICE.md §6.3 whenever this file changes.

[INPUT]
- json::json (POS: Python JSON library)
- copy::copy (POS: Python deep-copy library)
- utils.prompt_cache_economics::coerce_usage_non_negative_int, (POS: Utility library exports. Public interface for the utils module providing commonly used helper functions.)

[OUTPUT]
- is_verbose_response_logging_enabled(): check whether verbose response logging is enabled
- is_verbose_request_logging_enabled(): check whether verbose request logging is enabled
- log_api_request(), log_api_response(): log API request/response
- log_llm_response(): log response and invoke registered response hooks (e.g. cache metrics persistence)

[POS]
LiteLLM API request/response logging utility. Provides detailed LLM API call logging with toggle support.
Auto-truncates long text, redacts sensitive information (API keys), and formats output.
As the logging layer, used by ChatLiteLLM for debugging and monitoring LLM calls.
"""

import contextlib
import copy
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from myrm_agent_harness.utils.token_economics.cache_economics import (
    coerce_usage_non_negative_int,
    compute_prompt_cache_stats,
)

logger = logging.getLogger(__name__)

ResponseHookFn = Callable[[Mapping[str, object]], None]
_response_hooks: list[ResponseHookFn] = []

RequestHookFn = Callable[[str, list[dict[str, object]]], None]
_request_hooks: list[RequestHookFn] = []


def register_response_hook(hook: ResponseHookFn) -> None:
    """Register a hook called on every LLM response (e.g. cache metrics persistence)."""
    if hook not in _response_hooks:
        _response_hooks.append(hook)


def register_request_hook(hook: RequestHookFn) -> None:
    """Register a hook called on every LLM request (e.g. observability recording)."""
    if hook not in _request_hooks:
        _request_hooks.append(hook)


def is_verbose_response_logging_enabled() -> bool:
    """Check if verbose logging is enabled.

    Returns:
        True if verbose logging is enabled, False otherwise
    """
    return True


def is_verbose_request_logging_enabled() -> bool:
    """Check if verbose logging is enabled.

    Returns:
        True if verbose logging is enabled, False otherwise
    """
    return False


def _truncate_content(content: str, max_length: int = 300, head_length: int = 150) -> str:
    """Truncate long text, preserving head and tail.

    Args:
        content: Text to truncate
        max_length: Maximum length
        head_length: Head portion length to preserve

    Returns:
        Truncated text
    """
    if len(content) <= max_length:
        return content

    tail_length = max_length - head_length
    head = content[:head_length]
    tail = content[-tail_length:]
    omitted_length = len(content) - max_length
    return f"{head}\n... ({omitted_length} chars omitted) ...\n{tail}"


def _safe_get_finish_reason(response: Mapping[str, Any]) -> str:
    """Safely get finish_reason, handling empty choices list.

    Args:
        response: LiteLLM response dict

    Returns:
        finish_reason string, or 'N/A' if retrieval fails
    """
    choices = response.get("choices")
    if not choices or not isinstance(choices, list) or len(choices) == 0:
        return "N/A (empty choices)"
    return choices[0].get("finish_reason", "N/A")


def _decode_tool_call_arguments(tool_calls: list[dict]) -> None:
    """Decode tool_calls arguments in-place (for log display only).

    Parses JSON string arguments into dicts for readability.

    Args:
        tool_calls: tool_calls list (mutated in-place)
    """
    for tc in tool_calls:
        if "function" in tc and "arguments" in tc["function"]:
            args = tc["function"]["arguments"]
            if isinstance(args, str):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    tc["function"]["arguments"] = json.loads(args)


def prepare_messages_for_display(message_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare message list for log display.

    Args:
        message_dicts: Original message dict list

    Returns:
        Processed message dict list (deep copy, original unaffected)
    """
    messages_for_display = []
    for msg in message_dicts:
        msg_copy = copy.deepcopy(msg)  # Deep copy to avoid mutating original messages

        # Only truncate content field (head/tail 150 chars each when > 300 chars)
        if "content" in msg_copy and isinstance(msg_copy["content"], str):
            msg_copy["content"] = _truncate_content(msg_copy["content"])

        # Decode tool_calls arguments (if JSON strings) for readability
        if msg_copy.get("tool_calls"):
            _decode_tool_call_arguments(msg_copy["tool_calls"])

        messages_for_display.append(msg_copy)

    return messages_for_display


def _truncate_tool_descriptions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Truncate tool descriptions (deep copy, original unaffected).

    Args:
        tools: Tool list

    Returns:
        Processed tool list
    """
    tools_for_display = []
    for tool in tools:
        tool_copy = copy.deepcopy(tool)

        # Truncate function.description field (head/tail 100 chars each)
        if "function" in tool_copy and "description" in tool_copy["function"]:
            desc = tool_copy["function"]["description"]
            if isinstance(desc, str) and len(desc) > 200:
                head = desc[:100]
                tail = desc[-100:]
                omitted_length = len(desc) - 200
                tool_copy["function"]["description"] = f"{head}\n... ({omitted_length} chars omitted) ...\n{tail}"

        tools_for_display.append(tool_copy)

    return tools_for_display


def log_llm_request(
    model: str,
    message_dicts: list[dict[str, Any]],
    params: dict[str, Any],
) -> None:
    """Log LLM API request.

    Args:
        model: Model name
        message_dicts: Message dict list
        params: Request parameters
    """
    for hook in _request_hooks:
        try:
            hook(model, message_dicts)
        except Exception:
            logger.debug("Request hook failed", exc_info=True)

    if not is_verbose_request_logging_enabled():
        return

    messages_for_display = prepare_messages_for_display(message_dicts)
    messages_preview = json.dumps(messages_for_display, ensure_ascii=False, indent=2)

    # Format params output (excluding messages, truncating tool descriptions)
    params_for_display = {k: v for k, v in params.items() if k not in ["messages"]}

    # Truncate tool descriptions
    if params_for_display.get("tools"):
        params_for_display["tools"] = _truncate_tool_descriptions(params_for_display["tools"])

    params_formatted = json.dumps(params_for_display, ensure_ascii=False, indent=2)

    logger.warning(
        f" LLM API Request:\n"
        f" Model: {model}\n"
        f" Messages Count: {len(message_dicts)}\n"
        f" Params:\n{params_formatted}\n"
        f" Messages: {messages_preview}"
    )


def _decode_thinking_blocks(messages_data: list[dict[str, Any]]) -> None:
    """Decode nested JSON in thinking_blocks (in-place).

    thinking_blocks contain the model's reasoning process (e.g. DeepSeek Reasoner),
    where the thinking field is a nested JSON string that needs decoding for readability.

    Args:
        messages_data: Message list
    """
    for msg in messages_data:
        thinking_blocks = msg.get("thinking_blocks")
        if not thinking_blocks:
            continue

        for block in thinking_blocks:
            if "thinking" not in block:
                continue

            thinking_str = block["thinking"]
            if not isinstance(thinking_str, str):
                continue

            try:
                # Parse nested JSON
                thinking_obj = json.loads(thinking_str)
                block["thinking"] = thinking_obj  # Replace with parsed object
            except (json.JSONDecodeError, TypeError):
                pass  # Keep as-is


def _clean_response_messages(messages_data: list[dict[str, Any]]) -> None:
    """Clean hash value fields from response messages (in-place).

    Only removes technical fields containing long hash values, making logs cleaner; other fields preserved.

    Args:
        messages_data: Message list
    """
    for msg in messages_data:
        # Remove top-level provider_specific_fields (typically contains thought_signature hashes)
        msg.pop("provider_specific_fields", None)

        # Clean hash value fields in tool_calls
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                # Remove fields containing hash values
                tc.pop("provider_specific_fields", None)  # Contains thought_signature hash
                tc.pop("id", None)  # Tool call ID (long hash)

        # Clean hash value fields in thinking_blocks
        thinking_blocks = msg.get("thinking_blocks")
        if thinking_blocks:
            for block in thinking_blocks:
                block.pop("signature", None)  # Signature field (long hash)


def log_llm_response(
    response: Mapping[str, Any],
) -> None:
    """Log LLM API response.

    Args:
        response: LLM response dict
    """
    for hook in _response_hooks:
        try:
            hook(response)
        except Exception:
            logger.debug("Response hook failed", exc_info=True)

    if not is_verbose_response_logging_enabled():
        return

    model = response.get("model", "N/A")
    token_usage = response.get("usage", {})
    messages_data = [choice.get("message", {}) for choice in response.get("choices", [])]

    # Decode tool_calls arguments (if JSON strings) for readability
    for msg in messages_data:
        if msg.get("tool_calls"):
            _decode_tool_call_arguments(msg["tool_calls"])

    # Decode nested JSON in thinking_blocks
    _decode_thinking_blocks(messages_data)

    # Clean redundant fields
    _clean_response_messages(messages_data)

    # Extract token counts: coerce rules match optional NDJSON sink; cache ratio computed by compute_prompt_cache_stats
    prompt_tokens = coerce_usage_non_negative_int(token_usage.get("prompt_tokens", 0))
    completion_tokens = coerce_usage_non_negative_int(token_usage.get("completion_tokens", 0))
    total_tokens = coerce_usage_non_negative_int(token_usage.get("total_tokens", 0))

    # Extract cached_tokens from prompt_tokens_details
    # LiteLLM standardizes: OpenAI/Anthropic/Gemini all map to prompt_tokens_details.cached_tokens
    prompt_details = token_usage.get("prompt_tokens_details", {}) or {}
    cached_tokens = (
        coerce_usage_non_negative_int(prompt_details.get("cached_tokens")) if isinstance(prompt_details, dict) else 0
    )

    # Extract reasoning_tokens from completion_tokens_details
    completion_details = token_usage.get("completion_tokens_details", {}) or {}
    reasoning_tokens = completion_details.get("reasoning_tokens", 0) if isinstance(completion_details, dict) else 0

    cache_stats = compute_prompt_cache_stats(prompt_tokens, cached_tokens)
    cache_hit_rate = cache_stats["cache_hit_rate"]
    cost_savings_pct = cache_stats["cost_savings_pct"]

    # Build log message
    log_parts = [
        " LLM API Response:",
        f" Model: {model}",
        " Token Usage:",
        f" - Prompt Tokens: {prompt_tokens}",
        f" - Completion Tokens: {completion_tokens}",
        f" - Total Tokens: {total_tokens}",
        f" - Cached Tokens: {cached_tokens}",
    ]

    # If cache hit, show cache effect
    if cached_tokens > 0:
        log_parts.append(f" Cache Hit Rate: {cache_hit_rate:.1%} | Cost Savings: {cost_savings_pct:.1%}")

    if reasoning_tokens:
        log_parts.append(f" - Reasoning Tokens: {reasoning_tokens}")

    log_parts.extend(
        [
            f" Finish Reason: {_safe_get_finish_reason(response)}",
            f" Messages:\n{json.dumps(messages_data, ensure_ascii=False, indent=4)}",
        ]
    )

    logger.info("\n".join(log_parts))
