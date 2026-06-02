"""Search failure classification and ErrorContext construction.

[INPUT]
- (none)

[OUTPUT]
- is_retryable_search_error: function — is_retryable_search_error
- build_search_error_context: Build structured context for a single failed search attempt.

[POS]
Search failure classification and ErrorContext construction.
"""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.web_search.exceptions import ErrorContext


def _status_from_exception(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    alt = getattr(exc, "http_status", None)
    if isinstance(alt, int):
        return alt
    return None


def _response_body_snippet(exc: BaseException, max_len: int = 2000) -> str | None:
    for attr in ("response", "body"):
        raw = getattr(exc, attr, None)
        if raw is None:
            continue
        text = raw if isinstance(raw, str) else str(raw)
        if text.strip():
            return text[:max_len]
    msg = str(exc).strip()
    return msg[:max_len] if msg else None


def is_retryable_search_error(exc: BaseException) -> bool:
    """Return True when a failed search attempt may succeed after backoff."""
    text = str(exc).lower()

    # Non-retryable: quota/plan limit or invalid credentials — must check before
    # status codes because LiteLLM wraps provider errors as APIConnectionError(status=500).
    if "exceeds" in text and ("usage limit" in text or "plan" in text):
        return False
    if "invalid api key" in text or "invalid_api_key" in text:
        return False

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True
    status = _status_from_exception(exc)
    if status is not None:
        if status in (408, 425, 429, 500, 502, 503, 504):
            return True
        if status in (400, 401, 403, 404, 405, 422):
            return False

    if "429" in text or "rate limit" in text:
        return True
    if "502" in text or "503" in text or "504" in text or "500" in text:
        return True
    if "timeout" in text or "timed out" in text:
        return True
    # Match real connection errors but not LiteLLM's APIConnectionError wrapper
    if "connection refused" in text or "broken pipe" in text:
        return True
    return bool("connectionerror" in text and "apiconnectionerror" not in text)


def build_search_error_context(
    exc: BaseException,
    *,
    query: str,
    provider: str,
    attempt_index: int,
    error_code: str | None = None,
) -> ErrorContext:
    """Build structured context for a single failed search attempt."""
    status = _status_from_exception(exc)
    body = _response_body_snippet(exc)
    retryable = is_retryable_search_error(exc)
    metadata: dict[str, str] = {
        "provider": provider,
        "attempt_index": str(attempt_index),
    }
    return ErrorContext(
        query=query,
        status_code=status,
        error_code=error_code or type(exc).__name__,
        response_body=body,
        retryable=retryable,
        metadata=metadata,
    )
