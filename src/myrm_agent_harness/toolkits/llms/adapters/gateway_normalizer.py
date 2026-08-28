"""OpenAI compatible gateway normalization and 400 parameter downgrade handler.

Provides adaptive parameter sanitization for non-standard or lightweight OpenAI
proxies (OneAPI, Ollama, SiliconFlow, vLLM, etc.) when they reject non-standard
or optional parameters with HTTP 400.

[INPUT]
- Exception/error objects, params dict

[OUTPUT]
- sanitize_gateway_params_on_400(): Adaptive parameter stripping on HTTP 400 format errors
- is_gateway_param_rejection(): Check whether 400 error is due to an unsupported parameter

[POS]
Adapters gateway normalizer.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns matching parameter rejections in 400 Bad Request error messages
_PARAM_REJECTION_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(
            r"stream_options|unknown field.*stream_options|unsupported.*stream_options",
            re.IGNORECASE,
        ),
        ("stream_options",),
    ),
    (
        re.compile(
            r"parallel_tool_calls|unknown field.*parallel_tool_calls|unsupported.*parallel_tool_calls",
            re.IGNORECASE,
        ),
        ("parallel_tool_calls",),
    ),
    (
        re.compile(
            r"reasoning_effort|unknown field.*reasoning_effort|unsupported.*reasoning_effort",
            re.IGNORECASE,
        ),
        ("reasoning_effort",),
    ),
    (
        re.compile(r"presence_penalty|frequency_penalty", re.IGNORECASE),
        ("presence_penalty", "frequency_penalty"),
    ),
    (
        re.compile(
            r"max_completion_tokens|unknown field.*max_completion_tokens|unsupported.*max_completion_tokens",
            re.IGNORECASE,
        ),
        ("max_completion_tokens",),
    ),
    (
        re.compile(
            r"temperature.*(?:not supported|unsupported|does not support)|unsupported.*temperature",
            re.IGNORECASE,
        ),
        ("temperature",),
    ),
    (
        re.compile(
            r"response_format|unknown field.*response_format|unsupported.*response_format",
            re.IGNORECASE,
        ),
        ("response_format",),
    ),
    (
        re.compile(
            r"unknown field.*['\"]?user['\"]?|unsupported.*['\"]?user['\"]?",
            re.IGNORECASE,
        ),
        ("user",),
    ),
)


def is_gateway_param_rejection(exc: Exception) -> bool:
    """Return True if the exception indicates a gateway 400 error caused by an unsupported parameter."""
    err_str = str(exc).lower()
    for pattern, _ in _PARAM_REJECTION_PATTERNS:
        if pattern.search(err_str):
            return True
    return False


def sanitize_gateway_params_on_400(params: dict[str, Any], exc: Exception) -> list[str]:
    """Inspect the 400 error and strip the rejected parameters from params.

    For parameters with fallback compatibility (e.g. max_completion_tokens -> max_tokens),
    automatically maps the value to the compatible parameter key.

    Returns the list of parameter names that were stripped.
    """
    err_str = str(exc).lower()
    stripped: list[str] = []

    # Preserve value before stripping for fallback mappings
    saved_max_completion_tokens = params.get("max_completion_tokens")

    for pattern, param_keys in _PARAM_REJECTION_PATTERNS:
        if pattern.search(err_str):
            for key in param_keys:
                if key in params:
                    params.pop(key, None)
                    stripped.append(key)

    # Automatic fallback mapping: max_completion_tokens -> max_tokens
    if "max_completion_tokens" in stripped and saved_max_completion_tokens is not None:
        if "max_tokens" not in params:
            params["max_tokens"] = saved_max_completion_tokens
            if "allowed_openai_params" in params and isinstance(
                params["allowed_openai_params"], list
            ):
                if "max_tokens" not in params["allowed_openai_params"]:
                    params["allowed_openai_params"].append("max_tokens")

    # Also remove from allowed_openai_params whitelist if present
    if (
        stripped
        and "allowed_openai_params" in params
        and isinstance(params["allowed_openai_params"], list)
    ):
        params["allowed_openai_params"] = [
            p for p in params["allowed_openai_params"] if p not in stripped
        ]

    if stripped:
        logger.warning(
            " Gateway 400 detected, automatically stripped rejected param(s): %s",
            stripped,
        )

    return stripped
