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
- is_quota_exhausted: Detect irreversible quota/credit exhaustion errors for instant failover...

[POS]
LLM error classifier for failover decisions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from .classifier_patterns import (
    _AUTH_RE,
    _BILLING_RE,
    _CLOUDFLARE_CHALLENGE_RE,
    _DUPLICATE_TOOL_USE_ID_RE,
    _IMAGE_TOO_LARGE_RE,
    _LITELLM_INIT_BUG_RE,
    _LONG_CONTEXT_TIER_RE,
    _MEDIA_REJECTED_RE,
    _MODEL_NOT_FOUND_RE,
    _OVERFLOW_CN_KEYWORDS,
    _OVERFLOW_COMPOUND_CHECKS,
    _OVERFLOW_EXACT_RE,
    _OVERLOADED_503_RE,
    _OVERLOADED_RE,
    _PAYLOAD_TOO_LARGE_RE,
    _PROVIDER_FORMAT_400_RE,
    _PROVIDER_POLICY_BLOCKED_RE,
    _RATE_LIMIT_RE,
    _REASONING_MANDATORY_RE,
    _SAFETY_BLOCK_RE,
    _THINKING_SIGNATURE_RE,
    _TIMEOUT_RE,
    _TLS_HARD_RE,
    _TLS_TRANSPORT_RE,
    _USAGE_LIMIT_PATTERNS,
    _USAGE_LIMIT_TRANSIENT_SIGNALS,
)
from .error_types import FailoverReason
from .provider_window import has_rejected_quota_window
from .retry_after import extract_retry_after as extract_retry_after

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
    CHALLENGE_BLOCKED = "challenge_blocked"
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
        ErrorKind.MODEL_NOT_FOUND,
        ErrorKind.CHALLENGE_BLOCKED,
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
    ErrorKind.CHALLENGE_BLOCKED: FailoverReason.CHALLENGE_BLOCKED,
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
    FailoverReason.REASONING_MANDATORY: ErrorKind.FORMAT_ERROR,
    FailoverReason.DUPLICATE_TOOL_USE_ID: ErrorKind.FORMAT_ERROR,
    FailoverReason.IMAGE_TOO_LARGE: ErrorKind.FORMAT_ERROR,
    FailoverReason.MEDIA_REJECTED: ErrorKind.FORMAT_ERROR,
    FailoverReason.FORMAT_ERROR: ErrorKind.FORMAT_ERROR,
    FailoverReason.RESPONSE_FORMAT_ERROR: ErrorKind.RESPONSE_FORMAT_ERROR,
    FailoverReason.CHALLENGE_BLOCKED: ErrorKind.CHALLENGE_BLOCKED,
    FailoverReason.PROVIDER_POLICY_BLOCKED: ErrorKind.MODEL_NOT_FOUND,
    FailoverReason.MODEL_NOT_FOUND: ErrorKind.MODEL_NOT_FOUND,
    FailoverReason.UNKNOWN: ErrorKind.UNKNOWN,
}

# ============================================================================
# Normalizer
# ============================================================================


@dataclass
class NormalizedError:
    status_code: int | None
    message: str
    body: dict[str, object]


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


def _extract_error_body(error: Exception) -> dict[str, object]:
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

    # Extract deeply nested message, structured error codes, and types
    _raw_msg = str(error).lower()
    _body_msg = ""
    _codes: list[str] = []
    _types: list[str] = []
    _metadata_msg = ""

    # Direct exception attributes from client SDKs (OpenAI, Anthropic, LiteLLM)
    direct_code = getattr(error, "code", None)
    if direct_code is not None and not callable(direct_code):
        _codes.append(str(direct_code).lower())
    direct_type = getattr(error, "type", None)
    if direct_type is not None and not callable(direct_type):
        _types.append(str(direct_type).lower())

    if isinstance(body, dict):
        if body.get("code"):
            _codes.append(str(body["code"]).lower())
        if body.get("type"):
            _types.append(str(body["type"]).lower())

        _err_obj = body.get("error", {})
        if isinstance(_err_obj, dict):
            _body_msg = str(_err_obj.get("message") or "").lower()
            if _err_obj.get("code"):
                _codes.append(str(_err_obj["code"]).lower())
            if _err_obj.get("type"):
                _types.append(str(_err_obj["type"]).lower())

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
                                if _inner_err.get("code"):
                                    _codes.append(str(_inner_err["code"]).lower())
                                if _inner_err.get("type"):
                                    _types.append(str(_inner_err["type"]).lower())
                    except (json.JSONDecodeError, TypeError):
                        pass

    # Extract raw HTML or text snippet if response body is non-JSON (e.g. Cloudflare challenges)
    _resp_text = ""
    response = getattr(error, "response", None)
    if response is not None:
        text_attr = getattr(response, "text", None)
        if isinstance(text_attr, str):
            _resp_text = text_attr[:2000].lower()
        elif hasattr(response, "content"):
            content_attr = getattr(response, "content", None)
            if isinstance(content_attr, (bytes, bytearray)):
                _resp_text = content_attr[:2000].decode("utf-8", errors="ignore").lower()

    _codes_str = " ".join(_codes)
    _types_str = " ".join(_types)
    combined_message = f"{_raw_msg} | {_body_msg} | {_codes_str} | {_types_str} | {_metadata_msg} | {_resp_text}"
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
      thinking_signature → duplicate_tool_use_id → image_too_large → media_rejected →
      long_context_tier → billing → rate_limit → provider_policy_blocked → auth →
      provider_format → safety_block → model_not_found → overloaded → context_overflow →
      timeout → UNKNOWN
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

    # 0a1. Mandatory reasoning constraint / reasoning_effort rejected (400) — must precede generic 400
    if normalized.status_code == 400 and _REASONING_MANDATORY_RE.search(msg):
        return FailoverReason.REASONING_MANDATORY

    # 0a2. Duplicate tool_use / tool_call_id — must precede generic 400
    if normalized.status_code == 400 and _DUPLICATE_TOOL_USE_ID_RE.search(msg):
        return FailoverReason.DUPLICATE_TOOL_USE_ID

    # 0b. Per-image size or Gateway payload limit exceeded — must precede generic 400 / overflow
    if _IMAGE_TOO_LARGE_RE.search(msg) or _PAYLOAD_TOO_LARGE_RE.search(msg):
        return FailoverReason.IMAGE_TOO_LARGE

    # 0b2. Model rejects multimodal input entirely — must precede generic 400
    if _MEDIA_REJECTED_RE.search(msg):
        return FailoverReason.MEDIA_REJECTED

    # 0c. Anthropic long-context tier gate (429) — must precede generic rate_limit
    if normalized.status_code == 429 and _LONG_CONTEXT_TIER_RE.search(msg):
        return FailoverReason.LONG_CONTEXT_TIER

    # 1. Billing & Quota Exhaustion (highest priority to avoid retry loops)
    if _BILLING_RE.search(msg) or _QUOTA_EXHAUSTED_RE.search(msg) or has_rejected_quota_window(exc):
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

    # 3. Provider Policy / Guardrail Block (must precede generic 401/403 auth)
    if _PROVIDER_POLICY_BLOCKED_RE.search(msg):
        return FailoverReason.PROVIDER_POLICY_BLOCKED

    # 3.5. Cloudflare / WAF Anti-bot Challenge (must precede generic 401/403 auth fallback)
    is_html_doc = "<html" in msg or "<!doctype html" in msg
    if _CLOUDFLARE_CHALLENGE_RE.search(msg) or (is_html_doc and (normalized.status_code == 403 or "403" in msg)):
        return FailoverReason.CHALLENGE_BLOCKED

    # 4. Authentication (permanent credential / key errors)
    if _AUTH_RE.search(msg):
        return FailoverReason.AUTH_PERMANENT

    # 5. Model / Format / Safety (usually 400s or specific codes)
    if _PROVIDER_FORMAT_400_RE.search(msg):
        # API gateway validation error on LLM output (e.g., "must be in JSON format")
        # This is a model issue (weak model generated invalid JSON), not our bug
        return FailoverReason.RESPONSE_FORMAT_ERROR

    if _SAFETY_BLOCK_RE.search(msg):
        return FailoverReason.SAFETY_BLOCK

    # Model-not-found before overloaded: ServiceUnavailableError wrappers often match
    # service.?unavailable while the inner message is a missing-model distributor error.
    if _MODEL_NOT_FOUND_RE.search(msg):
        return FailoverReason.MODEL_NOT_FOUND

    # 5. Overloaded (prioritize over generic timeout)
    if _OVERLOADED_RE.search(msg) or _OVERLOADED_503_RE.search(msg):
        return FailoverReason.OVERLOADED

    # 6. Context Overflow
    if _is_context_overflow(msg):
        return FailoverReason.CONTEXT_OVERFLOW

    # 7. Transport/Timeouts (+ transient TLS: transport errors carrying an
    # SSL/TLS/handshake trace but no hard certificate verdict — same class
    # as connection reset, e.g. Bun's "unknown certificate verification
    # error" emitted on mid-handshake reset)
    if _TIMEOUT_RE.search(msg) or (_TLS_TRANSPORT_RE.search(msg) and not _TLS_HARD_RE.search(msg)):
        return FailoverReason.TIMEOUT

    # 7b. Hard TLS failure: the certificate/chain itself is rejected.
    # Fail-fast as AUTH_PERMANENT (peer-identity credential can never verify
    # by retrying); the diagnostic engine still surfaces the tls_certificate
    # remediation hint for these.
    if _TLS_HARD_RE.search(msg):
        return FailoverReason.AUTH_PERMANENT

    # 8. Fallback Status Code Probes
    if normalized.status_code == 400:
        # A generic 400 that isn't caught by above patterns is treated as a format error
        # to prevent infinite retry loops.
        return FailoverReason.FORMAT_ERROR

    if normalized.status_code == 403:
        if is_html_doc:
            return FailoverReason.CHALLENGE_BLOCKED
        return FailoverReason.AUTH_PERMANENT

    if normalized.status_code == 401:
        return FailoverReason.AUTH_PERMANENT

    if normalized.status_code == 402:
        return FailoverReason.BILLING

    if normalized.status_code == 413:
        if _PAYLOAD_TOO_LARGE_RE.search(msg) or _IMAGE_TOO_LARGE_RE.search(msg):
            return FailoverReason.IMAGE_TOO_LARGE
        return FailoverReason.CONTEXT_OVERFLOW

    if normalized.status_code == 429:
        return FailoverReason.RATE_LIMIT

    if normalized.status_code in (500, 502, 503, 504, 529):
        return FailoverReason.OVERLOADED

    return FailoverReason.UNKNOWN


def is_context_overflow(exc: Exception) -> bool:
    """Return ``True`` if *exc* signals a context-window overflow."""
    if classify_error(exc) == ErrorKind.CONTEXT_OVERFLOW:
        return True
    msg = normalize_provider_error(exc).message
    return _is_context_overflow(msg)


def is_payload_overflow(exc: Exception) -> bool:
    """Return ``True`` if *exc* indicates HTTP 413 or Payload/Request/Entity Too Large."""
    normalized = normalize_provider_error(exc)
    if normalized.status_code == 413:
        return True
    msg = normalized.message.lower()
    if _PAYLOAD_TOO_LARGE_RE.search(msg) or _IMAGE_TOO_LARGE_RE.search(msg):
        return True
    if "413" in msg and ("payload" in msg or "entity" in msg or "too large" in msg):
        return True
    reason = classify_failover_reason(exc)
    return reason == FailoverReason.IMAGE_TOO_LARGE


_QUOTA_EXHAUSTED_RE = re.compile(
    r"insufficient_quota"
    r"|quota_exceeded"
    r"|exceeded your current quota"
    r"|exceeded your quota"
    r"|check your plan and billing details"
    r"|free tier limit exceeded"
    r"|daily limit exceeded"
    r"|per-day limit"
    r"|requests per day.*exhausted"
    r"|usage.?limit.?reached"
    r"|enforced.?spend.?limit.?reached"
    r"|额度用尽|额度耗尽|账户欠费|超出每日限额",
    re.IGNORECASE,
)


def is_quota_exhausted(exc: Exception) -> bool:
    """Return ``True`` if *exc* signals non-transient quota exhaustion or zero balance.

    Unlike momentary rate limits (e.g. RPM/TPM bursts that recover within seconds),
    quota exhaustion (daily quota, prepaid credit depleted, plan limits) cannot be
    resolved by short-interval transient retries.
    """
    normalized = normalize_provider_error(exc)
    msg = normalized.message
    if _QUOTA_EXHAUSTED_RE.search(msg):
        return True
    reason = classify_failover_reason(exc)
    return reason == FailoverReason.BILLING


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
