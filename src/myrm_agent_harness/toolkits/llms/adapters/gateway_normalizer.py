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
    (
        re.compile(
            r"top_p.*(?:not supported|unsupported|does not support)|unsupported.*top_p|temperature.*top_p|top_p.*temperature",
            re.IGNORECASE,
        ),
        ("top_p",),
    ),
)

# Structured-output rejections that never name our parameter. Strict gateways and
# grammar backends reject the schema shape itself: a bare {"type": "object"} node
# without properties, or a grammar the backend cannot compile. These wordings carry
# no parameter token, so the name-based table above cannot match them.
_STRUCTURED_OUTPUT_SCHEMA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"an object with no properties is not allowed", re.IGNORECASE),
    re.compile(r"guided_grammar|xgrammar|compile_grammar_error", re.IGNORECASE),
)

# Schema name of the internally injected constrained tool-call transport. Only this
# transport is ever auto-stripped on schema-shape rejections; a user-supplied
# response_format is left untouched so explicit structured output keeps working.
_TOOL_CALLS_TRANSPORT_SCHEMA_NAME = "tool_calls_transport"

# Endpoints whose internal tool-call transport was rejected once, keyed by
# (model, base_url). Bounded process-local memory so a mis-detected endpoint pays
# exactly one failed request; endpoint or model changes alter the key.
_TRANSPORT_STRIP_MEMO: dict[tuple[str, str], None] = {}
_TRANSPORT_STRIP_MEMO_CAP = 256


def _normalize_memo_key(model: str, base_url: str) -> tuple[str, str]:
    """Normalize endpoint identity for the transport-strip memory."""
    return (model or "").strip().lower(), (base_url or "").strip().lower()


def is_transport_stripped(model: str = "", base_url: str = "") -> bool:
    """Return True when this endpoint already rejected the internal tool-call transport."""
    return _normalize_memo_key(model, base_url) in _TRANSPORT_STRIP_MEMO


def remember_stripped_transport(model: str = "", base_url: str = "") -> None:
    """Record that an endpoint rejected the internal tool-call transport."""
    key = _normalize_memo_key(model, base_url)
    if key == ("", "") or key in _TRANSPORT_STRIP_MEMO:
        return
    if len(_TRANSPORT_STRIP_MEMO) >= _TRANSPORT_STRIP_MEMO_CAP:
        _TRANSPORT_STRIP_MEMO.pop(next(iter(_TRANSPORT_STRIP_MEMO)))
    _TRANSPORT_STRIP_MEMO[key] = None


def _response_format_is_internal_transport(value: object) -> bool:
    """Return True when a response_format value is our injected tool-call transport."""
    if not isinstance(value, dict):
        return False
    json_schema = value.get("json_schema")
    return isinstance(json_schema, dict) and json_schema.get("name") == _TOOL_CALLS_TRANSPORT_SCHEMA_NAME


def _strip_internal_tool_calls_transport(params: dict[str, Any]) -> bool:
    """Remove our injected tool-call transport (top-level and extra_body)."""
    removed = False
    if _response_format_is_internal_transport(params.get("response_format")):
        params.pop("response_format", None)
        removed = True
    extra_body = params.get("extra_body")
    if isinstance(extra_body, dict) and _response_format_is_internal_transport(extra_body.get("response_format")):
        extra_body.pop("response_format", None)
        removed = True
    return removed


def is_gateway_param_rejection(exc: Exception) -> bool:
    """Return True if the exception indicates a gateway 400 error caused by an unsupported parameter."""
    err_str = str(exc).lower()
    for pattern, _ in _PARAM_REJECTION_PATTERNS:
        if pattern.search(err_str):
            return True
    return any(pattern.search(err_str) for pattern in _STRUCTURED_OUTPUT_SCHEMA_PATTERNS)


def sanitize_gateway_params_on_400(
    params: dict[str, Any],
    exc: Exception,
    *,
    model: str = "",
    base_url: str = "",
) -> list[str]:
    """Inspect the 400 error and strip the rejected parameters from params.

    For parameters with fallback compatibility (e.g. max_completion_tokens -> max_tokens),
    automatically maps the value to the compatible parameter key. Schema-shape rejections
    strip only our internally injected tool-call transport; user-supplied response_format
    is preserved. Whenever our internal transport is stripped, the endpoint is remembered
    so future requests skip the injection and never pay the failed call.

    Returns the list of parameter names that were stripped.
    """
    err_str = str(exc).lower()
    stripped: list[str] = []

    # Preserve value before stripping for fallback mappings
    saved_max_completion_tokens = params.get("max_completion_tokens")

    # Snapshot before stripping: a name-based rejection of our internal transport
    # qualifies for endpoint memory too, so mis-detected endpoints pay one retry.
    had_internal_transport = _response_format_is_internal_transport(params.get("response_format")) or (
        isinstance(params.get("extra_body"), dict)
        and _response_format_is_internal_transport(params["extra_body"].get("response_format"))
    )

    for pattern, param_keys in _PARAM_REJECTION_PATTERNS:
        if pattern.search(err_str):
            for key in param_keys:
                if key in params and key not in stripped:
                    params.pop(key, None)
                    stripped.append(key)

    for pattern in _STRUCTURED_OUTPUT_SCHEMA_PATTERNS:
        if pattern.search(err_str):
            if _strip_internal_tool_calls_transport(params) and "response_format" not in stripped:
                stripped.append("response_format")
            break

    if "response_format" in stripped and had_internal_transport:
        remember_stripped_transport(model, base_url)

    # Automatic fallback mapping: max_completion_tokens -> max_tokens
    if "max_completion_tokens" in stripped and saved_max_completion_tokens is not None and "max_tokens" not in params:
        params["max_tokens"] = saved_max_completion_tokens
        allowed_params = params.get("allowed_openai_params")
        if isinstance(allowed_params, list) and "max_tokens" not in allowed_params:
            allowed_params.append("max_tokens")

    # Also remove from allowed_openai_params whitelist if present
    if stripped and "allowed_openai_params" in params and isinstance(params["allowed_openai_params"], list):
        params["allowed_openai_params"] = [p for p in params["allowed_openai_params"] if p not in stripped]

    if stripped:
        logger.warning(
            " Gateway 400 detected, automatically stripped rejected param(s): %s",
            stripped,
        )

    return stripped
