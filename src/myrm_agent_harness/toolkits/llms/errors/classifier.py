"""LLM error classifier for failover decisions.

Classifies exceptions from LLM providers (OpenAI, Anthropic, Google, Groq,
ZhipuAI, etc.) into ``ErrorKind`` categories and ``FailoverReason`` types.

Features multi-dimensional probe pipeline to handle nested gateway errors
(e.g., OpenRouter metadata.raw), disambiguate 400 Bad Request, and
identify specific local/remote edge cases.

[INPUT]
- (none)

[OUTPUT]
- ErrorKind: Classified LLM error category.
- NormalizedError: Extract deep nested errors (e.g. OpenRouter metadata.raw)...
- normalize_provider_error: function — normalize_provider_error
- classify_error: Classify an LLM exception into an ``ErrorKind`` using mul...
- classify_failover_reason: Classify an LLM exception into a ``FailoverReason`` using...

[POS]
LLM error classifier for failover decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from .error_types import FailoverReason

# ============================================================================
# ErrorKind enum
# ============================================================================

_FAILOVERABLE_KINDS: frozenset[ErrorKind]


class ErrorKind(Enum):
    """Classified LLM error category."""

    CONTEXT_OVERFLOW = "context_overflow"
    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    BILLING = "billing"
    TIMEOUT = "timeout"
    AUTH = "auth"
    SAFETY_BLOCK = "safety_block"
    FORMAT_ERROR = "format_error"
    RESPONSE_FORMAT_ERROR = "response_format_error"
    MODEL_NOT_FOUND = "model_not_found"
    UNKNOWN = "unknown"

    @property
    def is_failoverable(self) -> bool:
        """Whether this error can potentially be resolved by switching models."""
        return self in _FAILOVERABLE_KINDS

    def to_failover_reason(self) -> FailoverReason:
        """Convert to FailoverReason (three-layer system)."""
        return _ERROR_KIND_TO_REASON.get(self, FailoverReason.UNKNOWN)


_FAILOVERABLE_KINDS = frozenset(
    {
        ErrorKind.CONTEXT_OVERFLOW,
        ErrorKind.RATE_LIMIT,
        ErrorKind.OVERLOADED,
        ErrorKind.BILLING,
        ErrorKind.TIMEOUT,
        ErrorKind.SAFETY_BLOCK,
        ErrorKind.RESPONSE_FORMAT_ERROR,
    }
)

# Mapping: ErrorKind → FailoverReason
_ERROR_KIND_TO_REASON: dict[ErrorKind, FailoverReason] = {
    ErrorKind.CONTEXT_OVERFLOW: FailoverReason.CONTEXT_OVERFLOW,
    ErrorKind.RATE_LIMIT: FailoverReason.RATE_LIMIT,
    ErrorKind.OVERLOADED: FailoverReason.OVERLOADED,
    ErrorKind.BILLING: FailoverReason.BILLING,
    ErrorKind.TIMEOUT: FailoverReason.TIMEOUT,
    ErrorKind.AUTH: FailoverReason.AUTH_PERMANENT,
    ErrorKind.SAFETY_BLOCK: FailoverReason.SAFETY_BLOCK,
    ErrorKind.FORMAT_ERROR: FailoverReason.FORMAT_ERROR,
    ErrorKind.RESPONSE_FORMAT_ERROR: FailoverReason.RESPONSE_FORMAT_ERROR,
    ErrorKind.MODEL_NOT_FOUND: FailoverReason.MODEL_NOT_FOUND,
    ErrorKind.UNKNOWN: FailoverReason.UNKNOWN,
}

# Mapping: FailoverReason → ErrorKind
_REASON_TO_ERROR_KIND: dict[FailoverReason, ErrorKind] = {
    FailoverReason.CONTEXT_OVERFLOW: ErrorKind.CONTEXT_OVERFLOW,
    FailoverReason.LONG_CONTEXT_TIER: ErrorKind.CONTEXT_OVERFLOW,
    FailoverReason.RATE_LIMIT: ErrorKind.RATE_LIMIT,
    FailoverReason.OVERLOADED: ErrorKind.OVERLOADED,
    FailoverReason.BILLING: ErrorKind.BILLING,
    FailoverReason.TIMEOUT: ErrorKind.TIMEOUT,
    FailoverReason.AUTH_PERMANENT: ErrorKind.AUTH,
    FailoverReason.SESSION_EXPIRED: ErrorKind.AUTH,
    FailoverReason.SAFETY_BLOCK: ErrorKind.SAFETY_BLOCK,
    FailoverReason.THINKING_SIGNATURE: ErrorKind.FORMAT_ERROR,
    FailoverReason.IMAGE_TOO_LARGE: ErrorKind.FORMAT_ERROR,
    FailoverReason.MEDIA_REJECTED: ErrorKind.FORMAT_ERROR,
    FailoverReason.FORMAT_ERROR: ErrorKind.FORMAT_ERROR,
    FailoverReason.RESPONSE_FORMAT_ERROR: ErrorKind.RESPONSE_FORMAT_ERROR,
    FailoverReason.PROVIDER_POLICY_BLOCKED: ErrorKind.MODEL_NOT_FOUND,
    FailoverReason.MODEL_NOT_FOUND: ErrorKind.MODEL_NOT_FOUND,
    FailoverReason.UNKNOWN: ErrorKind.UNKNOWN,
}

# ============================================================================
# Pattern definitions (module-level pre-compiled for performance)
# ============================================================================

_RATE_LIMIT_RE = re.compile(
    r"\btpm\b|tokens per minute|rate.?limit|too many requests|\b429\b|throttl"
    r"|resource.?exhausted|requests per (?:minute|hour|day)"
    r"|rate increased too quickly|too many concurrent requests"
    r"|servicequotaexceededexception",
    re.IGNORECASE,
)

_OVERLOADED_RE = re.compile(
    r"overloaded(?:_error)?|high.?demand|capacity.?(?:exceeded|full)"
    r"|\b529\b|service.?unavailable|\b502\b|\b503\b|\b504\b",
    re.IGNORECASE,
)

_OVERLOADED_503_RE = re.compile(
    r"(?:service.?unavailable|503).*(?:overload|capacity|high.?demand)"
    r"|(?:overload|capacity|high.?demand).*(?:service.?unavailable|503)",
    re.IGNORECASE,
)

_BILLING_RE = re.compile(
    r"billing|insufficient.?(?:balance|funds|credits|quota)|payment.?required"
    r"|exceeded.?(?:plan|budget|quota)|credit.?balance|\b402\b"
    r"|余额不足|额度不足|请充Value|欠费|无可用资源包|account is deactivated|top up your credits",
    re.IGNORECASE,
)

_AUTH_RE = re.compile(
    r"invalid.?api.?key|incorrect api key|unauthorized|\b401\b|\b403\b"
    r"|authentication|access.?denied|forbidden|permission.?(?:error|denied)"
    r"|api.?key.?(?:revoked|invalid|deactivated|expired)|token.?(?:has )?expired",
    re.IGNORECASE,
)

_TIMEOUT_RE = re.compile(
    r"\btimeout\b|timed.?out|deadline.?exceeded|connection.?(?:error|reset|refused)"
    r"|network.?(?:error|request failed)|fetch.?failed|socket.?hang.?up"
    r"|\b499\b"
    r"|server disconnected|unexpected eof|connection was closed",
    re.IGNORECASE,
)

_OVERFLOW_EXACT_RE = re.compile(
    r"|".join(
        [
            r"request_too_large",
            r"context[_ ]?length[_ ]?exceeded",
            r"maximum context length",
            r"(?:model[_ ]?)?context[_ ]?window[_ ]?exceeded",
            r"exceeds?[_ ](?:the[_ ])?model.?s?[_ ]?(?:maximum[_ ])?context",
            r"prompt is too long",
            r"model token limit",
            r"exceed context limit",
            r"request exceeds the maximum size",
            r"request size exceeds",
            r"exceeds the max_model_len",
            r"max_model_len",
            r"maximum model length",
            r"slot context",
            r"n_ctx_slot",
            r"exceeds the maximum number of input tokens",
            r"token.?limit.?exceeded",
        ]
    ),
    re.IGNORECASE,
)

_OVERFLOW_COMPOUND_CHECKS: list[tuple[re.Pattern[str], ...]] = [
    (
        re.compile(r"max_tokens", re.IGNORECASE),
        re.compile(r"exceed", re.IGNORECASE),
        re.compile(r"context", re.IGNORECASE),
    ),
    (
        re.compile(r"input length", re.IGNORECASE),
        re.compile(r"exceed", re.IGNORECASE),
        re.compile(r"context", re.IGNORECASE),
    ),
    (re.compile(r"413", re.IGNORECASE), re.compile(r"too large", re.IGNORECASE)),
]

_OVERFLOW_CN_KEYWORDS = (
    "上下文过长",
    "上下文超出",
    "上下文长度超",
    "超出最大上下文",
    "请压缩上下文",
)

_LITELLM_INIT_BUG_RE = re.compile(
    r"BadRequestError\.__init__\(\).*missing.*required positional argument",
    re.IGNORECASE,
)

_PROVIDER_FORMAT_400_RE = re.compile(
    r"must be in JSON format|InvalidParameter.*(?:function|arguments)"
    r"|schema validation error|invalid format|invalid json format|valid JSON",
    re.IGNORECASE,
)

_MODEL_NOT_FOUND_RE = re.compile(
    r"is not a valid model|invalid model|model not found|model_not_found"
    r"|does not exist|no such model|unknown model|unsupported model",
    re.IGNORECASE,
)

_USAGE_LIMIT_TRANSIENT_SIGNALS = [
    "try again",
    "retry",
    "resets at",
    "reset in",
    "wait",
    "requests remaining",
    "periodic",
    "window",
]

_USAGE_LIMIT_PATTERNS = ["usage limit", "quota", "limit exceeded", "key limit exceeded"]

_SAFETY_BLOCK_RE = re.compile(
    r"content_policy_violation|violating our usage policy|safety system"
    r"|content filtered|responsible ai policy|safety block",
    re.IGNORECASE,
)

_THINKING_SIGNATURE_RE = re.compile(
    r"signature.*thinking|thinking.*signature",
    re.IGNORECASE,
)

_IMAGE_TOO_LARGE_RE = re.compile(
    r"image exceeds|image.{0,6}too.{0,3}large|image_too_large|image size exceeds"
    r"|exceeds.+per.?image.+limit"
    r"|image.?dimensions?.+exceed|dimensions?.+exceed.+(?:maximum|max|limit|allowed)"
    r"|exceeds.+(?:maximum|max).+(?:allowed )?size.+\d+",
    re.IGNORECASE,
)

_LONG_CONTEXT_TIER_RE = re.compile(
    r"extra usage.+(?:required|needed).+long context",
    re.IGNORECASE,
)

_MEDIA_REJECTED_RE = re.compile(
    r"does not support (?:image|vision|multimodal|media)"
    r"|(?:image|vision|multimodal|media).+(?:not supported|not available|unsupported)"
    r"|cannot process (?:image|media|multimodal)"
    r"|model does not have vision"
    r"|content type.+image.+not supported"
    r"|invalid content type.+image",
    re.IGNORECASE,
)

_PROVIDER_POLICY_BLOCKED_RE = re.compile(
    r"no endpoints available matching your (?:guardrail|data policy)",
    re.IGNORECASE,
)


# ============================================================================
# Normalizer
# ============================================================================


@dataclass
class NormalizedError:
    status_code: int | None
    message: str
    body: dict


def _extract_status_code(error: Exception) -> int | None:
    current = error
    for _ in range(5):
        code = getattr(current, "status_code", None)
        if isinstance(code, int):
            return code
        code = getattr(current, "status", None)
        if isinstance(code, int) and 100 <= code < 600:
            return code
        cause = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if cause is None or cause is current:
            break
        current = cause
    return None


def _extract_error_body(error: Exception) -> dict:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(error, "response", None)
    if response is not None:
        try:
            json_body = response.json()
            if isinstance(json_body, dict):
                return json_body
        except Exception:
            pass
    return {}


def normalize_provider_error(error: Exception) -> NormalizedError:
    """Extract deep nested errors (e.g. OpenRouter metadata.raw) and status codes."""
    status_code = _extract_status_code(error)
    body = _extract_error_body(error)

    # Extract deeply nested message
    _raw_msg = str(error).lower()
    _body_msg = ""
    _metadata_msg = ""
    if isinstance(body, dict):
        _err_obj = body.get("error", {})
        if isinstance(_err_obj, dict):
            _body_msg = str(_err_obj.get("message") or "").lower()
            _metadata = _err_obj.get("metadata", {})
            if isinstance(_metadata, dict):
                _raw_json = _metadata.get("raw") or ""
                if isinstance(_raw_json, str) and _raw_json.strip():
                    try:
                        _inner = json.loads(_raw_json)
                        if isinstance(_inner, dict):
                            _inner_err = _inner.get("error", {})
                            if isinstance(_inner_err, dict):
                                _metadata_msg = str(_inner_err.get("message") or "").lower()
                    except (json.JSONDecodeError, TypeError):
                        pass

    combined_message = f"{_raw_msg} | {_body_msg} | {_metadata_msg}"
    return NormalizedError(status_code=status_code, message=combined_message, body=body)


# ============================================================================
# Public API
# ============================================================================


def classify_error(exc: Exception) -> ErrorKind:
    """Classify an LLM exception into an ``ErrorKind`` using multi-probe pipeline."""
    reason = classify_failover_reason(exc)
    return _REASON_TO_ERROR_KIND.get(reason, ErrorKind.UNKNOWN)


def classify_failover_reason(exc: Exception) -> FailoverReason:
    """Classify an LLM exception into a ``FailoverReason`` using deep inspection.

    Priority (specific → broad):
      thinking_signature → image_too_large → long_context_tier → billing →
      rate_limit → overloaded → auth → provider_format → safety_block →
      provider_policy_blocked → model_not_found → context_overflow → timeout → UNKNOWN
    """
    if isinstance(exc, TypeError) and _LITELLM_INIT_BUG_RE.search(str(exc)):
        return FailoverReason.TIMEOUT

    normalized = normalize_provider_error(exc)
    msg = normalized.message

    if not msg.strip() and not normalized.body:
        return FailoverReason.UNKNOWN

    # 0a. Anthropic thinking block signature invalid (400) — must precede generic 400
    if normalized.status_code == 400 and _THINKING_SIGNATURE_RE.search(msg):
        return FailoverReason.THINKING_SIGNATURE

    # 0b. Per-image size limit exceeded — must precede generic 400 / overflow
    if _IMAGE_TOO_LARGE_RE.search(msg):
        return FailoverReason.IMAGE_TOO_LARGE

    # 0b2. Model rejects multimodal input entirely — must precede generic 400
    if _MEDIA_REJECTED_RE.search(msg):
        return FailoverReason.MEDIA_REJECTED

    # 0c. Anthropic long-context tier gate (429) — must precede generic rate_limit
    if normalized.status_code == 429 and _LONG_CONTEXT_TIER_RE.search(msg):
        return FailoverReason.LONG_CONTEXT_TIER

    # 1. Billing (highest priority to avoid retry loops)
    if _BILLING_RE.search(msg):
        return FailoverReason.BILLING

    # 2. Rate Limit
    if _RATE_LIMIT_RE.search(msg):
        return FailoverReason.RATE_LIMIT

    # Usage Disambiguation (Rate Limit vs Billing)
    has_usage_limit = any(p in msg for p in _USAGE_LIMIT_PATTERNS)
    if has_usage_limit:
        has_transient = any(p in msg for p in _USAGE_LIMIT_TRANSIENT_SIGNALS)
        if has_transient:
            return FailoverReason.RATE_LIMIT
        return FailoverReason.BILLING

    # 3. Overloaded (prioritize over generic timeout)
    if _OVERLOADED_RE.search(msg) or _OVERLOADED_503_RE.search(msg):
        return FailoverReason.OVERLOADED

    # 4. Authentication
    if _AUTH_RE.search(msg):
        return FailoverReason.AUTH_PERMANENT

    # 5. Model / Format / Safety (usually 400s or specific codes)
    if _PROVIDER_FORMAT_400_RE.search(msg):
        # API gateway validation error on LLM output (e.g., "must be in JSON format")
        # This is a model issue (weak model generated invalid JSON), not our bug
        return FailoverReason.RESPONSE_FORMAT_ERROR

    if _SAFETY_BLOCK_RE.search(msg):
        return FailoverReason.SAFETY_BLOCK

    if _PROVIDER_POLICY_BLOCKED_RE.search(msg):
        return FailoverReason.PROVIDER_POLICY_BLOCKED

    if _MODEL_NOT_FOUND_RE.search(msg):
        return FailoverReason.MODEL_NOT_FOUND

    # 6. Context Overflow
    if _is_context_overflow(msg):
        return FailoverReason.CONTEXT_OVERFLOW

    # 7. Transport/Timeouts
    if _TIMEOUT_RE.search(msg):
        return FailoverReason.TIMEOUT

    # 8. Fallback Status Code Probes
    if normalized.status_code == 400:
        # A generic 400 that isn't caught by above patterns is treated as a format error
        # to prevent infinite retry loops.
        return FailoverReason.FORMAT_ERROR

    if normalized.status_code in (401, 403):
        return FailoverReason.AUTH_PERMANENT

    if normalized.status_code == 402:
        return FailoverReason.BILLING

    if normalized.status_code == 413:
        return FailoverReason.CONTEXT_OVERFLOW

    if normalized.status_code == 429:
        return FailoverReason.RATE_LIMIT

    if normalized.status_code in (500, 502, 503, 504, 529):
        return FailoverReason.OVERLOADED

    return FailoverReason.UNKNOWN


def is_context_overflow(exc: Exception) -> bool:
    """Return ``True`` if *exc* signals a context-window overflow."""
    return classify_error(exc) == ErrorKind.CONTEXT_OVERFLOW


def extract_retry_after(exc: Exception) -> float | None:
    """Extract ``Retry-After`` seconds from an LLM exception's HTTP response.

    Walks the exception chain looking for an HTTP response with a
    ``Retry-After`` header.  Returns the value as a positive float, or
    ``None`` if unavailable / unparseable.
    """
    current: Exception | None = exc
    for _ in range(5):
        if current is None:
            break
        response = getattr(current, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                raw = headers.get("retry-after") or headers.get("Retry-After")
                if raw is not None:
                    try:
                        value = float(raw)
                        if value > 0:
                            return value
                    except (ValueError, TypeError):
                        pass
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return None


_AVAILABLE_TOKENS_RE = re.compile(r"available\s*_?tokens\s*:\s*(\d+)", re.IGNORECASE)


def parse_available_output_tokens_from_error(exc: Exception) -> int | None:
    """Extract available output tokens from a ContextWindowExceeded error.

    If the API explicitly reports how many tokens are still available (e.g.
    Anthropic's 'max_tokens: 32768 > 200000 - 190000 = available_tokens: 10000'),
    return that number to allow ephemeral overriding without breaking cache.
    """
    normalized = normalize_provider_error(exc)
    match = _AVAILABLE_TOKENS_RE.search(normalized.message)
    if match:
        try:
            return int(match.group(1))
        except (ValueError, TypeError):
            return None
    return None


# ============================================================================
# Internal helpers
# ============================================================================


def _is_context_overflow(msg: str) -> bool:
    """Check raw message string for context overflow patterns."""
    if _OVERFLOW_EXACT_RE.search(msg):
        return True

    for patterns in _OVERFLOW_COMPOUND_CHECKS:
        if all(p.search(msg) for p in patterns):
            return True

    return any(kw in msg for kw in _OVERFLOW_CN_KEYWORDS)
