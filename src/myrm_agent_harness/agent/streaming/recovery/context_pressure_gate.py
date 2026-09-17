"""Pre-send cumulative context pressure gate (deterministic, no LLM calls).

Runs before each model request: estimates the full cumulative request size
(messages + bound-tool overhead, aligned with the provider prompt tokens when
available) and deterministically sheds load when it crosses the preflight
budget. Never calls the LLM itself, so the gate cannot explode on its own.

Also hosts the presumed-overflow helper: a generic HTTP 400 that carries no
overflow signal is treated as a presumed overflow exactly once when occupancy
is high, instead of looping forever or dying immediately.

[INPUT]
- utils.token_estimation::estimate_context_tokens (POS: Token estimation infrastructure)
- agent._internals.agent_recovery::emergency_compact/truncate_oldest_rounds
  (POS: Agent recovery strategies — context overflow, LLM failover, structured error context)
- toolkits.llms.errors.classifier::classify_failover_reason (POS: LLM error classifier for failover decisions)
- toolkits.llms.errors.error_types::FailoverReason (POS: Three-layer error classification system)
- toolkits.llms.utils.model_utils::get_model_context_limit (POS: Stateless utilities for inspecting LLM model properties)

[OUTPUT]
- ContextPressureConfig: resolved preflight budget for one session
- resolve_effective_config: mapping override, else model window, else default
- estimate_request_tokens: cumulative request size for gate decisions
- preflight_budget: effective send budget from config
- run_preflight_compact: deterministic Tier2 -> Tier3 load shedding
- is_presumed_overflow: high-occupancy generic-400 detector
- CONTEXT_OVERFLOW_TERMINAL_CODE: unified terminal code for UI triage

[POS]
Deterministic send-gate owned by the streaming recovery layer. The heavy
summarization path stays in StreamRecoveryMixin._handle_overflow; this module
only decides *when* to shed load and performs the zero-LLM-cost tiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from myrm_agent_harness.toolkits.llms.errors.classifier import (
    classify_failover_reason,
    normalize_provider_error,
)
from myrm_agent_harness.toolkits.llms.errors.error_types import FailoverReason
from myrm_agent_harness.toolkits.llms.utils.model_utils import get_model_context_limit
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage

logger = get_agent_logger(__name__)

CONTEXT_OVERFLOW_TERMINAL_CODE = "context_overflow_after_compaction"

DEFAULT_MAX_CONTEXT_TOKENS = 200_000
DEFAULT_PREFLIGHT_RATIO = 0.8
DEFAULT_RESERVE_TOKENS = 20_000
DEFAULT_PRESUMED_RATIO = 0.85
DEFAULT_MAX_PREFLIGHT_STREAK = 3


@dataclass(frozen=True, slots=True)
class ContextPressureConfig:
    """Resolved preflight budget for one session.

    Values come from the ``context_pressure_config`` mapping in the merged
    run context when present, otherwise from the defaults below. Server layers
    may inject per-agent overrides through that single mapping key.
    """

    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    preflight_ratio: float = DEFAULT_PREFLIGHT_RATIO
    reserve_tokens: int = DEFAULT_RESERVE_TOKENS
    presumed_ratio: float = DEFAULT_PRESUMED_RATIO
    max_preflight_streak: int = DEFAULT_MAX_PREFLIGHT_STREAK

    @staticmethod
    def resolve(raw: dict[str, Any] | None) -> ContextPressureConfig:
        """Resolve config from the merged run context mapping."""
        if not isinstance(raw, dict):
            return ContextPressureConfig()
        mapping = raw.get("context_pressure_config")
        if not isinstance(mapping, dict):
            return ContextPressureConfig()
        try:
            max_ctx = int(mapping.get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS))
            ratio = float(mapping.get("preflight_ratio", DEFAULT_PREFLIGHT_RATIO))
            reserve = int(mapping.get("reserve_tokens", DEFAULT_RESERVE_TOKENS))
            presumed = float(mapping.get("presumed_ratio", DEFAULT_PRESUMED_RATIO))
            streak = int(mapping.get("max_preflight_streak", DEFAULT_MAX_PREFLIGHT_STREAK))
        except (TypeError, ValueError):
            return ContextPressureConfig()
        if max_ctx <= 0:
            return ContextPressureConfig()
        ratio = min(max(ratio, 0.1), 0.95)
        presumed = min(max(presumed, ratio), 0.99)
        return ContextPressureConfig(
            max_context_tokens=max_ctx,
            preflight_ratio=ratio,
            reserve_tokens=max(0, reserve),
            presumed_ratio=presumed,
            max_preflight_streak=max(1, streak),
        )


@dataclass(slots=True)
class PreflightStreak:
    """Tracks consecutive preflight-triggered turns for rapid-refill cutoff."""

    streak: int = 0
    guarded_turns: int = 0


def resolve_effective_config(
    raw: dict[str, Any] | None,
    llm: BaseChatModel | None,
) -> ContextPressureConfig:
    """Resolve the effective budget: explicit mapping wins, else model window.

    Falls back to the conservative default only when neither the run context
    mapping nor the model itself reports a window, so wide-window models are
    never compacted prematurely and narrow ones stay protected.
    """
    if isinstance(raw, dict) and isinstance(raw.get("context_pressure_config"), dict):
        return ContextPressureConfig.resolve(raw)
    if llm is not None:
        try:
            window = get_model_context_limit(llm)
        except Exception:
            window = None
        if isinstance(window, int) and window > 0:
            base = ContextPressureConfig.resolve(None)
            return ContextPressureConfig(
                max_context_tokens=window,
                preflight_ratio=base.preflight_ratio,
                reserve_tokens=base.reserve_tokens,
                presumed_ratio=base.presumed_ratio,
                max_preflight_streak=base.max_preflight_streak,
            )
    return ContextPressureConfig.resolve(raw)


def estimate_request_tokens(
    messages: list[BaseMessage],
    *,
    bound_tool_overhead_tokens: int = 0,
    last_provider_prompt_tokens: int | None = None,
) -> int:
    """Estimate the full cumulative request size for gate decisions."""
    return estimate_context_tokens(
        messages,
        bound_tool_overhead_tokens=bound_tool_overhead_tokens,
        last_provider_prompt_tokens=last_provider_prompt_tokens,
    )


def preflight_budget(config: ContextPressureConfig) -> int:
    """Effective send budget: the stricter of ratio gate and reserve gate."""
    by_ratio = int(config.max_context_tokens * config.preflight_ratio)
    by_reserve = config.max_context_tokens - config.reserve_tokens
    return max(1_000, min(by_ratio, by_reserve))


def presumed_budget(config: ContextPressureConfig) -> int:
    """Occupancy floor above which a generic 400 is presumed overflow."""
    return int(config.max_context_tokens * config.presumed_ratio)


async def run_preflight_compact(messages: list[BaseMessage]) -> tuple[int, str]:
    """Deterministically shed load in place without any LLM call.

    Tier2 (emergency tool-result prune) first, Tier3 (oldest-round truncation)
    as fallback. Both helpers are tool-pair safe. Returns freed tokens and
    the strategy name for recovery events.
    """
    from myrm_agent_harness.agent._internals.agent_recovery import (
        emergency_compact as _emergency_compact,
    )
    from myrm_agent_harness.agent._internals.agent_recovery import (
        truncate_oldest_rounds as _truncate_oldest_rounds,
    )

    try:
        saved = await _emergency_compact(messages)
    except Exception as exc:
        logger.warning(" Preflight Tier2 emergency compact failed: %s", exc)
        saved = 0
    if saved > 0:
        return saved, "context_preflight_compact"
    try:
        saved = _truncate_oldest_rounds(messages)
    except Exception as exc:
        logger.warning(" Preflight Tier3 truncation failed: %s", exc)
        saved = 0
    return saved, "context_preflight_truncation"


def is_presumed_overflow(
    exc: Exception,
    request_tokens: int,
    config: ContextPressureConfig,
) -> bool:
    """Detect high-occupancy generic 400s worth one presumed-overflow retry.

    Only matches when the classifier lands on FORMAT_ERROR with an HTTP 400
    status (i.e. the provider gave no usable overflow signal) *and* the
    cumulative request already sits above the presumed budget. Anything else
    keeps the fast-fail behavior to avoid retry loops.
    """
    if classify_failover_reason(exc) != FailoverReason.FORMAT_ERROR:
        return False
    if normalize_provider_error(exc).status_code != 400:
        return False
    return request_tokens >= presumed_budget(config)


class PreflightGateMixin:
    """Pre-send gate + presumed-overflow recovery for StreamExecutor.

    Mixed in via multiple inheritance; accesses host attributes
    (``_ctx``, ``streaming_final_answer``, ``_preflight_streak``,
    ``_presumed_overflow_used``) and the host ``_emit_recovery_event``.
    Keeps the executor file from growing past its budget.
    """

    _ctx: Any
    streaming_final_answer: bool
    _preflight_streak: PreflightStreak
    _presumed_overflow_used: bool

    if TYPE_CHECKING:
        # Bound at runtime via StreamRecoveryMixin in the MRO. Declared only
        # for type checking; never define a runtime stub here or it would
        # shadow the real emitter.
        async def _emit_recovery_event(self, step_key: str, **extra: object) -> None: ...

    async def _run_preflight_pressure_gate(self) -> None:
        """Cumulative pre-send gate: shed load before the provider sees it.

        Deterministic only (emergency prune, then oldest-round truncation),
        so the gate itself can never explode. Fail-open: when shedding frees
        nothing repeatedly, marks ``compression_exhausted`` and still sends
        once instead of looping.
        """
        from langgraph.types import Command

        ctx: Any = self._ctx
        if isinstance(ctx.agent_input, Command):
            return
        messages_dict: Any = ctx.agent_input
        messages: list[Any] = messages_dict.get("messages", [])
        if not messages:
            self._preflight_streak.streak = 0
            return
        merged = ctx.merged_context if isinstance(ctx.merged_context, dict) else None
        config = resolve_effective_config(merged, getattr(ctx, "llm", None))
        request_tokens = estimate_request_tokens(messages)
        if request_tokens < preflight_budget(config):
            self._preflight_streak.streak = 0
            return
        if self._preflight_streak.streak >= config.max_preflight_streak:
            ctx.stats.compression_exhausted = True
            logger.warning(
                " Preflight rapid-refill breaker tripped after %d guarded turns",
                self._preflight_streak.streak,
            )
            await self._emit_recovery_event(
                "context_preflight_exhausted",
                restart=False,
                terminal_code=CONTEXT_OVERFLOW_TERMINAL_CODE,
                request_tokens=request_tokens,
            )
            return
        saved, strategy = await run_preflight_compact(messages)
        self._preflight_streak.streak += 1
        self._preflight_streak.guarded_turns += 1
        if saved <= 0 and self._preflight_streak.streak >= config.max_preflight_streak:
            ctx.stats.compression_exhausted = True
        logger.warning(
            " Preflight pressure gate stage %d: freed %d tokens (request=%d)",
            self._preflight_streak.streak,
            saved,
            request_tokens,
        )
        await self._emit_recovery_event(
            strategy,
            restart=True,
            freed_tokens=saved,
            request_tokens=request_tokens,
        )

    async def _handle_presumed_overflow(self, exc: Exception) -> bool:
        """Single presumed-overflow retry for high-occupancy generic 400s.

        The provider gave no usable overflow signal (classifier: FORMAT_ERROR
        + HTTP 400) but the cumulative request already sits above the presumed
        budget. Sheds load deterministically exactly once; anything else keeps
        the fast-fail behavior to avoid retry loops.
        """
        from langgraph.types import Command

        if self._presumed_overflow_used:
            return False
        ctx: Any = self._ctx
        if isinstance(ctx.agent_input, Command):
            return False
        messages_dict: Any = ctx.agent_input
        messages: list[Any] = messages_dict.get("messages", [])
        if not messages:
            return False
        merged = ctx.merged_context if isinstance(ctx.merged_context, dict) else None
        config = resolve_effective_config(merged, getattr(ctx, "llm", None))
        request_tokens = estimate_request_tokens(messages)
        if not is_presumed_overflow(exc, request_tokens, config):
            return False
        self._presumed_overflow_used = True
        saved, strategy = await run_preflight_compact(messages)
        if saved <= 0:
            ctx.stats.compression_exhausted = True
            logger.warning(
                " Presumed overflow shed nothing (request=%d) — failing fast",
                request_tokens,
            )
            await self._emit_recovery_event(
                "context_presumed_overflow_exhausted",
                restart=False,
                terminal_code=CONTEXT_OVERFLOW_TERMINAL_CODE,
                request_tokens=request_tokens,
            )
            return False
        logger.warning(
            " Presumed overflow recovered: freed %d tokens (request=%d), retrying",
            saved,
            request_tokens,
        )
        await self._emit_recovery_event(
            "context_presumed_overflow",
            restart=True,
            freed_tokens=saved,
            request_tokens=request_tokens,
            strategy=strategy,
        )
        self.streaming_final_answer = False
        return True


__all__ = [
    "CONTEXT_OVERFLOW_TERMINAL_CODE",
    "ContextPressureConfig",
    "PreflightGateMixin",
    "PreflightStreak",
    "estimate_request_tokens",
    "is_presumed_overflow",
    "preflight_budget",
    "presumed_budget",
    "resolve_effective_config",
    "run_preflight_compact",
]
