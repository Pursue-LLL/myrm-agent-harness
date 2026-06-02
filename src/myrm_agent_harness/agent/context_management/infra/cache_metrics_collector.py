"""Explicit-cache prompt metrics collection (opt-in NDJSON persistence).

Enable by setting environment variable ``MYRM_CACHE_METRICS_DIR`` to a writable
directory. Each completed LLM response appends one JSON line (NDJSON) per day file.

[INPUT]
- contextvars::ContextVar
- dataclasses::dataclass
- utils.token_economics.cache_economics::coerce_usage_non_negative_int, compute_prompt_cache_stats

[OUTPUT]
- PendingExplicitCacheSnapshot: frozen snapshot from ExplicitCacheProcessor
- clear_pending_explicit_cache_snapshot(): reset pending (middleware / cleanup)
- set_pending_explicit_cache_snapshot(): store snapshot for next LLM response
- take_pending_explicit_cache_snapshot(): consume snapshot (pairing)
- try_persist_cache_call_metrics(): run cache break detection (always-on) + append NDJSON (opt-in)
- get_pending_cache_break_event(): consume pending cache break event for SSE dispatch

[POS]
Request-scoped pairing via ContextVar (same asyncio task as token tracker).

## Deployment Guidance

**Single-instance semantics**: Default ``threading.Lock`` and NDJSON appends
assume single framework instance per directory. For multi-instance deployments
(e.g., horizontal scaling), control plane MUST inject distinct
``MYRM_CACHE_METRICS_DIR`` per instance (e.g., ``/logs/metrics/instance-1``)
or route to a centralized metrics aggregator to prevent interleaved writes.

**Expected vs Actual**: NDJSON records contain both pre-LLM estimates
(``explicit_cache.expected_*``) and post-LLM actuals
(``actual_cache_hit_rate``). Expected values assume no KV-cache drift or tool
insertions; divergence indicates architectural drift (see
``PROMPT_CACHE_PRACTICE.md`` for interpretation).
"""

import json
import logging
import threading
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.utils.token_economics.cache_economics import (
    coerce_usage_non_negative_int,
    compute_prompt_cache_stats,
)

from .schemas import CacheUsageFeedback

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class PendingExplicitCacheSnapshot:
    """Pre-LLM explicit-cache snapshot (paired with the next ``log_llm_response``).

    Contains only essential cache performance metrics. Model name available via
    ``response_model``. Business tracking (chat_id/user_id) belongs in centralized
    logging. Configuration constants belong in documentation. Derived metrics
    (expected_hit_rate) calculated on-demand to avoid redundancy.
    """

    turn_count: int
    breakpoint_count: int
    message_count: int
    total_estimated_tokens: int
    expected_cacheable_tokens: int
    compression_count: int


_pending_snapshot: ContextVar[PendingExplicitCacheSnapshot | None] = ContextVar(
    "explicit_cache_metrics_pending", default=None
)


def clear_pending_explicit_cache_snapshot() -> None:
    """Clear any pending snapshot (start of model call or defensive cleanup)."""
    _pending_snapshot.set(None)


def set_pending_explicit_cache_snapshot(snapshot: PendingExplicitCacheSnapshot) -> None:
    """Attach snapshot for the upcoming LLM call in this context."""
    _pending_snapshot.set(snapshot)


def take_pending_explicit_cache_snapshot() -> PendingExplicitCacheSnapshot | None:
    """Atomically take and clear the pending snapshot."""
    current = _pending_snapshot.get()
    _pending_snapshot.set(None)
    return current


_pending_cache_break: ContextVar[dict[str, object] | None] = ContextVar(
    "pending_cache_break_event", default=None
)

_cache_usage_feedback: ContextVar[CacheUsageFeedback | None] = ContextVar(
    "cache_usage_feedback", default=None
)


def get_pending_cache_break_event() -> dict[str, object] | None:
    """Atomically take and clear the pending cache break event for SSE dispatch."""
    event = _pending_cache_break.get()
    if event is not None:
        _pending_cache_break.set(None)
    return event


def get_cache_usage_feedback() -> CacheUsageFeedback | None:
    """Return accumulated provider cache usage feedback for the current request."""
    return _cache_usage_feedback.get()


def clear_cache_usage_feedback() -> None:
    """Clear accumulated provider cache usage feedback for the current request."""
    _cache_usage_feedback.set(None)


def _record_cache_usage_feedback(prompt_tokens: int, cached_tokens: int) -> None:
    """Accumulate cache usage so pruning decisions can use real provider feedback."""
    if prompt_tokens <= 0 and cached_tokens <= 0:
        return

    current = _cache_usage_feedback.get()
    calls = 1
    input_tokens = max(prompt_tokens, 0)
    total_cached_tokens = max(cached_tokens, 0)
    if current is not None:
        calls += current.calls
        input_tokens += current.input_tokens
        total_cached_tokens += current.cached_tokens

    cache_stats = compute_prompt_cache_stats(input_tokens, total_cached_tokens)
    feedback = CacheUsageFeedback(
        calls=calls,
        input_tokens=input_tokens,
        cached_tokens=total_cached_tokens,
        cache_hit_rate=cache_stats["cache_hit_rate"],
    )
    _cache_usage_feedback.set(feedback)


_metrics_dir_override: str | None = None


def set_cache_metrics_dir(path: str | None) -> None:
    """Configure cache metrics output directory. None disables metrics persistence."""
    global _metrics_dir_override
    _metrics_dir_override = path


def _cache_metrics_dir() -> str | None:
    return _metrics_dir_override


def _usage_ints(response: Mapping[str, object]) -> tuple[int, int, int]:
    """Extract (prompt_tokens, completion_tokens, cached_tokens) from LLM response."""
    token_usage = response.get("usage", {})
    if not isinstance(token_usage, dict):
        return 0, 0, 0

    prompt_tokens = coerce_usage_non_negative_int(token_usage.get("prompt_tokens", 0))
    completion_tokens = coerce_usage_non_negative_int(token_usage.get("completion_tokens", 0))

    prompt_details = token_usage.get("prompt_tokens_details", {})
    cached = 0
    if isinstance(prompt_details, dict):
        cached = coerce_usage_non_negative_int(prompt_details.get("cached_tokens"))

    return prompt_tokens, completion_tokens, cached


def _append_ndjson_line(base_dir: str, payload: dict[str, object]) -> None:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    path = Path(base_dir) / f"cache_metrics_{day}.ndjson"
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    try:
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        logger.exception("Failed to append cache metrics")


def _check_cache_break(cached_tokens: int, response: Mapping[str, object]) -> dict[str, object] | None:
    """Run cache break detection (always-on, independent of NDJSON persistence)."""
    from .cache_break_detector import get_cache_break_detector

    detector = get_cache_break_detector()
    if detector is None:
        return None

    token_usage = response.get("usage", {})
    cache_creation = 0
    if isinstance(token_usage, dict):
        raw = token_usage.get("cache_creation_input_tokens")
        if raw is not None:
            cache_creation = coerce_usage_non_negative_int(raw)

    event = detector.check_cache_break(cached_tokens, cache_creation)
    if event is None:
        return None

    return {
        "prev_cache_read": event.prev_cache_read,
        "curr_cache_read": event.curr_cache_read,
        "token_drop": event.token_drop,
        "reasons": list(event.reasons),
        "suggested_actions": list(event.suggested_actions),
        "cache_creation_tokens": event.cache_creation_tokens,
    }


def try_persist_cache_call_metrics(response: Mapping[str, object]) -> None:
    """Persist cache metrics (opt-in NDJSON) and run cache break detection (always-on)."""
    pending = take_pending_explicit_cache_snapshot()
    prompt_tokens, completion_tokens, cached_tokens = _usage_ints(response)
    _record_cache_usage_feedback(prompt_tokens, cached_tokens)

    break_info = _check_cache_break(cached_tokens, response)

    # Store break event in ContextVar for SSE dispatch (always-on, independent of NDJSON)
    if break_info is not None:
        _pending_cache_break.set(break_info)

    base = _cache_metrics_dir()
    if base is None:
        return

    cache_stats = compute_prompt_cache_stats(prompt_tokens, cached_tokens)
    cache_hit_rate = cache_stats["cache_hit_rate"]
    cost_savings_pct = cache_stats["cost_savings_pct"]

    model_raw = response.get("model", "N/A")
    response_model = model_raw if isinstance(model_raw, str) else str(model_raw)

    record: dict[str, object] = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "response_model": response_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "actual_cache_hit_rate": cache_hit_rate,
        "cost_savings_pct_vs_uncached_input": cost_savings_pct,
        "explicit_cache_snapshot": pending is not None,
    }

    if pending is not None:
        record["explicit_cache"] = asdict(pending)

    if break_info is not None:
        record["cache_break"] = break_info

    _append_ndjson_line(base, record)


_hook_installed = False


def install_llm_response_hook() -> None:
    """Register ``try_persist_cache_call_metrics`` as an LLM response hook (idempotent)."""
    global _hook_installed
    if _hook_installed:
        return
    _hook_installed = True

    from myrm_agent_harness.toolkits.llms.utils.logger import register_response_hook

    register_response_hook(try_persist_cache_call_metrics)
