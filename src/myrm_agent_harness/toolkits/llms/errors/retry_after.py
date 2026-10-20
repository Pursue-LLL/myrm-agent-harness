"""``Retry-After`` extraction from provider HTTP exceptions.

Providers state their retry boundary in a header; this reads it without deciding what
to do with it. Kept beside ``provider_window`` because that module is the primary
consumer of provider-stated windows.

[INPUT]
- Exception (POS: provider 异常，可能需要沿 __cause__ / __context__ 链查找)

[OUTPUT]
- extract_retry_after(): 从 HTTP 响应头读取正数秒数，取不到返回 None

[POS]
Header-level retry-boundary reader. Walks up to five links of the exception chain, since
SDKs wrap the original HTTP response several layers deep.
"""

from __future__ import annotations

_MAX_CHAIN_DEPTH = 5


def extract_retry_after(exc: Exception) -> float | None:
    """Extract ``Retry-After`` seconds from an LLM exception's HTTP response.

    Walks the exception chain looking for an HTTP response with a
    ``Retry-After`` header.  Returns the value as a positive float, or
    ``None`` if unavailable / unparseable.
    """
    current: Exception | None = exc
    for _ in range(_MAX_CHAIN_DEPTH):
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
                    except (ValueError, TypeError):
                        value = 0.0
                    if value > 0:
                        return value
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return None
