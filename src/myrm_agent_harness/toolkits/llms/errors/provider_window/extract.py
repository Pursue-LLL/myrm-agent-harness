"""Read the provider's own statement of when a rate-limited call may be retried.

[INPUT]
- Exception chain of a failed LLM call (``__cause__``/``__context__``), their HTTP response
  headers and JSON bodies as raised by litellm / OpenAI / Anthropic SDKs

[OUTPUT]
- extract_provider_window: first usable ProviderWindowHint, or None
- has_rejected_quota_window: True when the provider flags a spent quota window

[POS]
Single extractor behind every wait/hold decision. Precedence: Anthropic unified
rate-limit headers (rejected quota windows; the overage spend pool is not a window) >
Codex/OpenAI body fields > ``Retry-After`` header > "retry after N seconds" message text.
Anthropic's headers live two to three levels down the cause chain, so the whole chain is
merged before reading.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

from .types import ProviderWindowHint, WindowSource

_MAX_CHAIN_DEPTH = 6
_MAX_PLAUSIBLE_WAIT_S = 366 * 24 * 3600.0

# Quota windows are duration-named buckets (``5h``, ``7d``). ``overage`` is the pay-as-you-go pool: an
# account without credits reports it as "rejected" even while every window is open, so it is no window.
_ANTHROPIC_WINDOW_STATUS_RE = re.compile(r"^anthropic-ratelimit-unified-(\d+[hd])-status$")
_MESSAGE_RETRY_AFTER_RE = re.compile(r"retry.*?after.*?(\d+).*?second", re.IGNORECASE)


def extract_provider_window(exc: BaseException, *, now: float | None = None) -> ProviderWindowHint | None:
    """Return the provider-stated retry boundary carried by *exc*, if any."""
    now_ts = time.time() if now is None else now
    chain = _walk_chain(exc)
    headers = _merged_headers(chain)

    rejected = _rejected_windows(headers)
    if rejected:
        # A spent quota window is the only truth; Retry-After would be an admission pause.
        resets = [_epoch(headers.get(f"anthropic-ratelimit-unified-{name}-reset")) for name in rejected]
        if any(reset is None for reset in resets):
            return None
        return _hint(max(r for r in resets if r is not None), now_ts, WindowSource.ANTHROPIC_UNIFIED, True)

    body_reset = _codex_body_reset(chain, now_ts)
    if body_reset is not None:
        return _hint(body_reset, now_ts, WindowSource.CODEX_BODY, True)

    retry_after = _retry_after_seconds(headers.get("retry-after"), now_ts)
    if retry_after is not None:
        return _hint(now_ts + retry_after, now_ts, WindowSource.RETRY_AFTER, False)

    match = _MESSAGE_RETRY_AFTER_RE.search(str(exc))
    if match:
        return _hint(now_ts + int(match.group(1)), now_ts, WindowSource.MESSAGE, False)
    return None


def has_rejected_quota_window(exc: BaseException) -> bool:
    """Whether the provider reports at least one rejected (spent) quota window."""
    return bool(_rejected_windows(_merged_headers(_walk_chain(exc))))


def _hint(reset_at: float, now: float, source: WindowSource, quota_window: bool) -> ProviderWindowHint | None:
    wait_s = reset_at - now
    if not 0 < wait_s <= _MAX_PLAUSIBLE_WAIT_S:
        return None
    return ProviderWindowHint(reset_at=reset_at, wait_s=wait_s, source=source, quota_window=quota_window)


def _walk_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN_DEPTH:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _merged_headers(chain: list[BaseException]) -> dict[str, str]:
    """Lower-cased headers of every chain level; the outermost value wins."""
    merged: dict[str, str] = {}
    for err in chain:
        response = getattr(err, "response", None)
        sources = (
            getattr(err, "headers", None),
            getattr(err, "response_headers", None),
            getattr(response, "headers", None),
        )
        for source in sources:
            if isinstance(source, Mapping):
                for key, value in source.items():
                    merged.setdefault(str(key).lower(), str(value))
    return merged


def _rejected_windows(headers: Mapping[str, str]) -> list[str]:
    names: list[str] = []
    for key, value in headers.items():
        match = _ANTHROPIC_WINDOW_STATUS_RE.match(key)
        if match and value.strip().lower() == "rejected":
            names.append(match.group(1))
    return names


def _epoch(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _codex_body_reset(chain: list[BaseException], now: float) -> float | None:
    for err in chain:
        for fields in _body_candidates(err):
            resets_at = _number(fields.get("resets_at"))
            if resets_at is not None and resets_at > now:
                return resets_at
            resets_in = _number(fields.get("resets_in_seconds"))
            if resets_in is not None:
                return now + resets_in
    return None


def _body_candidates(err: BaseException) -> list[Mapping[str, object]]:
    body = getattr(err, "body", None)
    if not isinstance(body, Mapping):
        response = getattr(err, "response", None)
        try:
            body = response.json() if response is not None else None
        except Exception:
            body = None
    if not isinstance(body, Mapping):
        return []
    nested = body.get("error")
    return [body, nested] if isinstance(nested, Mapping) else [body]


def _retry_after_seconds(raw: str | None, now: float) -> float | None:
    if raw is None:
        return None
    seconds = _epoch(raw)
    if seconds is not None:
        return seconds
    try:
        return parsedate_to_datetime(raw).timestamp() - now
    except (TypeError, ValueError):
        return None
