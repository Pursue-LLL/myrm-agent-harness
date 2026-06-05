"""Prompt cache break detection and attribution.

Detects significant drops in cache_read_tokens between consecutive LLM calls
and attributes them to specific causes (system prompt change, tool schema
change, model switch, TTL expiry, or server-side eviction).

Two-phase architecture:
  1. Pre-call: ``record_prompt_state()`` captures digests of system prompt,
     tool definitions, and model name. Compares against previous turn to
     record pending changes.
  2. Post-call: ``check_cache_break()`` compares cache_read_tokens against
     the previous turn. If a significant drop is detected (>5% AND >2000
     tokens), attributes it using the pending changes from phase 1.

Compression awareness: ``notify_compaction()`` resets the baseline so that
the natural cache rebuild after compaction is not reported as a break.

Lifecycle via ContextVar (mirrors ``TokenTracker`` pattern):
  - ``init_cache_break_detector()`` at agent startup
  - ``get_cache_break_detector()`` in middleware / metrics
  - ``reset_cache_break_detector()`` at session end

[INPUT]
- (none)

[OUTPUT]
- PromptStateDigest: Immutable hash snapshot of the prompt state at a given turn.
- CacheBreakEvent: Describes a detected cache break with attribution reasons and suggested actions.
- CacheBreakDetector: Detects and attributes prompt cache breaks within a session.
- init_cache_break_detector: Create and bind a detector for the current context.
- get_cache_break_detector: Get the detector for the current context, or None.

[POS]
Prompt cache break detection and attribution.
"""

import hashlib
import logging
import time
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field

from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

MIN_CACHE_BREAK_TOKEN_DROP = 2_000
CACHE_STABLE_RATIO = 0.95
_CACHE_TTL_5MIN_S = 5 * 60
_CACHE_TTL_1HOUR_S = 60 * 60


@dataclass(frozen=True, slots=True)
class PromptStateDigest:
    """Immutable hash snapshot of the prompt state at a given turn."""

    system_prompt_hash: str
    tool_definitions_hash: str
    per_tool_hashes: dict[str, str]
    tool_count: int
    model_name: str


@dataclass(frozen=True, slots=True)
class CacheBreakEvent:
    """Describes a detected cache break with attribution reasons and suggested actions."""

    prev_cache_read: int
    curr_cache_read: int
    token_drop: int
    reasons: tuple[str, ...]
    suggested_actions: tuple[str, ...] = ()
    cache_creation_tokens: int = 0


@dataclass(slots=True)
class _PendingChanges:
    """Changes detected between consecutive prompt states."""

    system_prompt_changed: bool = False
    tool_definitions_changed: bool = False
    model_changed: bool = False
    prev_model: str = ""
    new_model: str = ""
    tool_count_delta: int = 0
    changed_tools: tuple[str, ...] = ()


@dataclass(slots=True)
class _SessionCacheState:
    """Mutable per-session tracking state."""

    prev_cache_read: int | None = None
    prev_digest: PromptStateDigest | None = None
    prev_timestamp: float = field(default_factory=time.monotonic)
    compaction_pending: bool = False
    pending_changes: _PendingChanges | None = None


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _compute_system_prompt_hash(messages: Sequence[BaseMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        if msg.type == "system":
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            parts.append(content)
    return _sha256_hex("||".join(parts)) if parts else _sha256_hex("")


def _compute_tool_hashes(
    tool_names_and_schemas: Sequence[tuple[str, str]],
) -> tuple[str, dict[str, str]]:
    """Compute aggregate hash and per-tool hashes.

    Args:
        tool_names_and_schemas: Sequence of (tool_name, schema_json_str) pairs.

    Returns:
        (aggregate_hash, {tool_name: hash})
    """
    per_tool: dict[str, str] = {}
    aggregate_parts: list[str] = []
    for name, schema in sorted(tool_names_and_schemas):
        h = _sha256_hex(f"{name}:{schema}")
        per_tool[name] = h
        aggregate_parts.append(h)
    aggregate = _sha256_hex("|".join(aggregate_parts)) if aggregate_parts else _sha256_hex("")
    return aggregate, per_tool


def _diff_tool_hashes(prev: dict[str, str], curr: dict[str, str]) -> tuple[str, ...]:
    """Identify which tools had schema changes."""
    changed: list[str] = []
    all_names = set(prev) | set(curr)
    for name in sorted(all_names):
        prev_h = prev.get(name)
        curr_h = curr.get(name)
        if prev_h != curr_h:
            changed.append(name)
    return tuple(changed)


class CacheBreakDetector:
    """Detects and attributes prompt cache breaks within a session."""

    __slots__ = "_state"

    def __init__(self) -> None:
        self._state = _SessionCacheState()

    def record_prompt_state(
        self,
        messages: Sequence[BaseMessage],
        model: str,
        tool_names_and_schemas: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        """Phase 1 (pre-call): record current state and detect what changed.

        Args:
            messages: Full message list (system + conversation).
            model: Model name string.
            tool_names_and_schemas: Optional (name, schema_json) pairs.
                When provided, enables per-tool attribution. When omitted,
                tool changes are attributed as "tools or server-side".
        """
        system_hash = _compute_system_prompt_hash(messages)

        if tool_names_and_schemas is not None:
            agg_hash, per_tool = _compute_tool_hashes(tool_names_and_schemas)
            tool_count = len(tool_names_and_schemas)
        else:
            agg_hash = ""
            per_tool = {}
            tool_count = -1

        digest = PromptStateDigest(
            system_prompt_hash=system_hash,
            tool_definitions_hash=agg_hash,
            per_tool_hashes=per_tool,
            tool_count=tool_count,
            model_name=model,
        )

        prev = self._state.prev_digest
        if prev is not None:
            changes = _PendingChanges()
            if prev.system_prompt_hash != digest.system_prompt_hash:
                changes.system_prompt_changed = True
            if prev.tool_definitions_hash != digest.tool_definitions_hash:
                changes.tool_definitions_changed = True
                changes.tool_count_delta = digest.tool_count - prev.tool_count
                changes.changed_tools = _diff_tool_hashes(prev.per_tool_hashes, digest.per_tool_hashes)
            if prev.model_name != digest.model_name:
                changes.model_changed = True
                changes.prev_model = prev.model_name
                changes.new_model = digest.model_name

            has_any = changes.system_prompt_changed or changes.tool_definitions_changed or changes.model_changed
            self._state.pending_changes = changes if has_any else None
        else:
            self._state.pending_changes = None

        self._state.prev_digest = digest

    def check_cache_break(self, cache_read_tokens: int, cache_creation_tokens: int = 0) -> CacheBreakEvent | None:
        """Phase 2 (post-call): detect break and attribute causes.

        Returns CacheBreakEvent if a significant cache drop was detected,
        None otherwise.
        """
        prev_read = self._state.prev_cache_read
        now = time.monotonic()
        elapsed_s = now - self._state.prev_timestamp

        self._state.prev_cache_read = cache_read_tokens
        self._state.prev_timestamp = now

        if self._state.compaction_pending:
            self._state.compaction_pending = False
            self._state.pending_changes = None
            logger.debug(
                "[CacheBreak] compaction baseline reset, cache_read=%d",
                cache_read_tokens,
            )
            return None

        if prev_read is None:
            self._state.pending_changes = None
            return None

        token_drop = prev_read - cache_read_tokens
        if cache_read_tokens >= prev_read * CACHE_STABLE_RATIO or token_drop < MIN_CACHE_BREAK_TOKEN_DROP:
            self._state.pending_changes = None
            return None

        reasons, actions = self._build_reasons_and_actions(elapsed_s)
        self._state.pending_changes = None

        event = CacheBreakEvent(
            prev_cache_read=prev_read,
            curr_cache_read=cache_read_tokens,
            token_drop=token_drop,
            reasons=reasons,
            suggested_actions=actions,
            cache_creation_tokens=cache_creation_tokens,
        )

        logger.warning(
            "[PROMPT CACHE BREAK] %s | cache_read: %d → %d (-%d), creation: %d",
            ", ".join(reasons),
            prev_read,
            cache_read_tokens,
            token_drop,
            cache_creation_tokens,
        )

        return event

    def seconds_since_last_call(self) -> float | None:
        """Seconds elapsed since the last recorded LLM call, or None if no call recorded."""
        if self._state.prev_cache_read is None and self._state.prev_digest is None:
            return None
        return time.monotonic() - self._state.prev_timestamp

    def notify_compaction(self) -> None:
        """Reset baseline after compaction to prevent false positives."""
        self._state.compaction_pending = True
        self._state.prev_cache_read = None
        logger.debug("[CacheBreak] compaction notified, baseline will reset")

    def _build_reasons_and_actions(self, elapsed_s: float) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Build both attribution reasons and corresponding suggested actions."""
        reasons: list[str] = []
        actions: list[str] = []
        changes = self._state.pending_changes

        if changes:
            if changes.model_changed:
                reasons.append(f"model changed ({changes.prev_model} → {changes.new_model})")
                actions.append("Keep one model per session. Use sub-agents for tasks requiring different models.")
            if changes.system_prompt_changed:
                reasons.append("system prompt changed")
                actions.append(
                    "Check for dynamic content in system prompt "
                    "(timestamps, request IDs). "
                    "Move dynamic values to user messages instead."
                )
            if changes.tool_definitions_changed:
                delta = changes.tool_count_delta
                if delta != 0:
                    sign = "+" if delta > 0 else ""
                    reasons.append(f"tools changed ({sign}{delta} tools)")
                elif changes.changed_tools:
                    names = ", ".join(changes.changed_tools[:5])
                    suffix = f" +{len(changes.changed_tools) - 5} more" if len(changes.changed_tools) > 5 else ""
                    reasons.append(f"tool schema changed ({names}{suffix})")
                else:
                    reasons.append("tool definitions changed")
                actions.append(
                    "Avoid adding/removing tools mid-session. Use deferred tool loading or skill invocation instead."
                )

        if not reasons:
            if elapsed_s > _CACHE_TTL_1HOUR_S:
                reasons.append("likely 1h TTL expiry (prompt unchanged)")
                actions.append("Consider shorter sessions or providers with longer cache TTL.")
            elif elapsed_s > _CACHE_TTL_5MIN_S:
                reasons.append("likely 5min TTL expiry (prompt unchanged)")
                actions.append("Enable idle compaction to keep cache warm, or reduce time between requests.")
            else:
                reasons.append("likely server-side (prompt unchanged, <5min gap)")
                actions.append("Provider-side cache eviction, no action needed.")

        return tuple(reasons), tuple(actions)


# ---------------------------------------------------------------------------
# ContextVar lifecycle (mirrors token_tracker pattern)
# ---------------------------------------------------------------------------

_detector_var: ContextVar[CacheBreakDetector | None] = ContextVar("cache_break_detector", default=None)


def init_cache_break_detector() -> CacheBreakDetector:
    """Create and bind a detector for the current context."""
    detector = CacheBreakDetector()
    _detector_var.set(detector)
    return detector


def get_cache_break_detector() -> CacheBreakDetector | None:
    """Get the detector for the current context, or None."""
    return _detector_var.get()


def reset_cache_break_detector() -> None:
    """Clear the detector from the current context."""
    _detector_var.set(None)
