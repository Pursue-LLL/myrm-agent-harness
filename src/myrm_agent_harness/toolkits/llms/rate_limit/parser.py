"""Rate Limit Header Parser.

[INPUT]
- .types::RateLimitBucket, RateLimitState (POS: Data structures)

[OUTPUT]
- parse_rate_limit_headers: Parses HTTP headers into RateLimitState.

[POS]
Parser for extracting rate limit info from LLM provider HTTP headers.
"""

import re
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from typing import Any

from .types import RateLimitBucket, RateLimitState

_OPENAI_RESET_RE = re.compile(
    r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+)ms)?"
)


def _parse_reset_time(val: Any) -> float | None:
    """Parse reset time into relative seconds.

    Handles:
    - OpenAI format: "6m0s", "1.5s", "2ms"
    - Anthropic format: "2024-01-01T00:00:00Z" (ISO 8601)
    - Unix timestamps: "1704067200"
    - Plain seconds: "60"
    """
    if not val:
        return None

    val_str = str(val).strip()

    # Try ISO 8601 (Anthropic)
    if "T" in val_str and "Z" in val_str:
        try:
            from datetime import datetime

            # Basic ISO 8601 parsing
            dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            reset_at = dt.timestamp()
            return max(0.0, reset_at - time.time())
        except Exception:
            pass

    # Try OpenAI format (e.g., "6m0s")
    if "s" in val_str or "m" in val_str or "h" in val_str:
        m = _OPENAI_RESET_RE.match(val_str)
        if m and any(m.groups()):
            h = float(m.group(1) or 0)
            mins = float(m.group(2) or 0)
            s = float(m.group(3) or 0)
            ms = float(m.group(4) or 0)
            return (h * 3600) + (mins * 60) + s + (ms / 1000.0)

    # Try plain float (seconds or unix timestamp)
    try:
        fval = float(val_str)
        # Unix timestamps are >946684800 (2000-01-01)
        if fval > 9.46e8:
            return max(0.0, fval - time.time())
        return fval
    except ValueError:
        pass

    return None


def _parse_int(val: Any) -> int | None:
    try:
        if val is None:
            return None
        return int(float(val))
    except (ValueError, TypeError, OverflowError):
        return None


def parse_rate_limit_headers(
    headers: Mapping[str, str],
    provider: str,
    model: str,
) -> RateLimitState | None:
    """Parse rate limit headers from HTTP response.

    Supports OpenAI, Anthropic, and OpenRouter standard headers.
    Returns None if no rate limit headers are found.
    """
    if not headers:
        return None

    # Case-insensitive header lookup
    headers_lower = {k.lower(): v for k, v in headers.items()}

    # Extract timestamp to prevent race conditions
    updated_at = time.time()
    if "date" in headers_lower:
        try:
            dt = parsedate_to_datetime(headers_lower["date"])
            updated_at = dt.timestamp()
        except Exception:
            pass

    # Normalize provider prefixes
    p = provider.lower()
    prefix = "x-ratelimit-"
    if p == "anthropic":
        prefix = "anthropic-ratelimit-"

    # Check if any rate limit headers exist
    has_rl = any(
        k.startswith(prefix) or k.startswith("x-ratelimit-") for k in headers_lower
    )
    if not has_rl:
        return None

    # Helper to extract bucket
    def _extract_bucket(
        limit_key: str, remaining_key: str, reset_key: str
    ) -> RateLimitBucket | None:
        limit = _parse_int(headers_lower.get(limit_key))
        remaining = _parse_int(headers_lower.get(remaining_key))
        reset = _parse_reset_time(headers_lower.get(reset_key))

        # Fallback to standard x-ratelimit if provider-specific is missing
        if limit is None and prefix != "x-ratelimit-":
            limit = _parse_int(
                headers_lower.get(limit_key.replace(prefix, "x-ratelimit-"))
            )
            remaining = _parse_int(
                headers_lower.get(remaining_key.replace(prefix, "x-ratelimit-"))
            )
            reset = _parse_reset_time(
                headers_lower.get(reset_key.replace(prefix, "x-ratelimit-"))
            )

        if limit is not None and remaining is not None and reset is not None:
            return RateLimitBucket(
                limit=limit,
                remaining=remaining,
                reset_seconds=reset,
                updated_at=updated_at,
            )
        return None

    # Anthropic uses "requests-limit" (resource-first); OpenAI uses "limit-requests"
    if p == "anthropic":
        rpm = _extract_bucket(
            f"{prefix}requests-limit",
            f"{prefix}requests-remaining",
            f"{prefix}requests-reset",
        )
        tpm = _extract_bucket(
            f"{prefix}tokens-limit",
            f"{prefix}tokens-remaining",
            f"{prefix}tokens-reset",
        )
        # Anthropic also exposes input-tokens / output-tokens separately
        if tpm is None:
            tpm = _extract_bucket(
                f"{prefix}input-tokens-limit",
                f"{prefix}input-tokens-remaining",
                f"{prefix}input-tokens-reset",
            )
        rph = None
        tph = None
    else:
        rpm = _extract_bucket(
            f"{prefix}limit-requests",
            f"{prefix}remaining-requests",
            f"{prefix}reset-requests",
        )
        rph = _extract_bucket(
            f"{prefix}limit-requests-1h",
            f"{prefix}remaining-requests-1h",
            f"{prefix}reset-requests-1h",
        )
        tpm = _extract_bucket(
            f"{prefix}limit-tokens",
            f"{prefix}remaining-tokens",
            f"{prefix}reset-tokens",
        )
        tph = _extract_bucket(
            f"{prefix}limit-tokens-1h",
            f"{prefix}remaining-tokens-1h",
            f"{prefix}reset-tokens-1h",
        )

    if not any((rpm, rph, tpm, tph)):
        return None

    return RateLimitState(
        provider=provider,
        model=model,
        rpm=rpm,
        rph=rph,
        tpm=tpm,
        tph=tph,
        updated_at=updated_at,
    )
