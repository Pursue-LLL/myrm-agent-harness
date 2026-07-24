"""Routing strategy implementations for Combo target ordering.

Each strategy reorders a list of ``ComboTarget`` entries to determine
which target the resolver should try first.

[INPUT]
- combo.combo_types (POS: ComboTarget, RoutingStrategy)

[OUTPUT]
- apply_strategy: reorder targets according to a RoutingStrategy

[POS]
Pure functions — no I/O, no state, no side-effects.  All mutable session
context (LKGP sticky target, round-robin index, request counters) is
passed in via ``StrategyContext`` and returned as a new instance.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field

from .combo_types import ComboTarget, RoutingStrategy


@dataclass
class StrategyContext:
    """Mutable per-session context that strategies can read / update.

    Attributes:
        lkgp_target_key: ``provider_id/model`` of the last successful target
                         (for ``LKGP`` strategy).
        round_robin_index: Current rotation index (for ``ROUND_ROBIN``).
        request_counts: Per-target request counts keyed by ``provider_id/model``
                        (for ``HEADROOM``).
        context_relay_target_key: Target that served recent turns of the
                                  current conversation (for ``CONTEXT_RELAY``).
    """

    lkgp_target_key: str | None = None
    round_robin_index: int = 0
    request_counts: dict[str, int] = field(default_factory=dict)
    context_relay_target_key: str | None = None


def _target_key(t: ComboTarget) -> str:
    return f"{t.provider_id}/{t.model}"


def _apply_priority(targets: list[ComboTarget]) -> list[ComboTarget]:
    return sorted(targets, key=lambda t: t.priority)


def _apply_cost_optimized(targets: list[ComboTarget]) -> list[ComboTarget]:
    """Sort by ``priority`` as cost proxy — lower priority = cheaper."""
    return sorted(targets, key=lambda t: t.priority)


def _apply_round_robin(
    targets: list[ComboTarget],
    ctx: StrategyContext,
) -> list[ComboTarget]:
    n = len(targets)
    if n <= 1:
        return list(targets)
    idx = ctx.round_robin_index % n
    ctx.round_robin_index = (idx + 1) % n
    return targets[idx:] + targets[:idx]


def _apply_random(targets: list[ComboTarget]) -> list[ComboTarget]:
    shuffled = list(targets)
    _random.shuffle(shuffled)
    return shuffled


def _apply_lkgp(
    targets: list[ComboTarget],
    ctx: StrategyContext,
) -> list[ComboTarget]:
    """Sticky on last known good provider — move it to front if still available."""
    if not ctx.lkgp_target_key:
        return list(targets)
    sticky_idx: int | None = None
    for i, t in enumerate(targets):
        if _target_key(t) == ctx.lkgp_target_key:
            sticky_idx = i
            break
    if sticky_idx is None:
        return list(targets)
    return [targets[sticky_idx], *(t for i, t in enumerate(targets) if i != sticky_idx)]


def _apply_context_relay(
    targets: list[ComboTarget],
    ctx: StrategyContext,
) -> list[ComboTarget]:
    """Prefer the target that served recent turns for prompt-cache affinity."""
    if not ctx.context_relay_target_key:
        return list(targets)
    affinity_idx: int | None = None
    for i, t in enumerate(targets):
        if _target_key(t) == ctx.context_relay_target_key:
            affinity_idx = i
            break
    if affinity_idx is None:
        return list(targets)
    return [targets[affinity_idx], *(t for i, t in enumerate(targets) if i != affinity_idx)]


def _apply_headroom(
    targets: list[ComboTarget],
    ctx: StrategyContext,
) -> list[ComboTarget]:
    """Prefer targets with the most remaining request headroom.

    Headroom ≈ RPM cap − requests sent.  Targets without a cap are treated
    as having infinite headroom and are placed first (preserving original
    order among themselves).
    """

    def _headroom(t: ComboTarget) -> float:
        if t.max_requests_per_minute is None:
            return float("inf")
        used = ctx.request_counts.get(_target_key(t), 0)
        return max(0.0, t.max_requests_per_minute - used)

    return sorted(targets, key=lambda t: -_headroom(t))


def apply_strategy(
    targets: list[ComboTarget],
    strategy: RoutingStrategy,
    ctx: StrategyContext,
) -> list[ComboTarget]:
    """Reorder *targets* according to *strategy*, mutating *ctx* as needed.

    Returns a new list — the caller's original list is never modified.

    Raises:
        ValueError: on unrecognised strategy (should never happen unless
                    new enum members are added without handler).
    """
    match strategy:
        case RoutingStrategy.PRIORITY:
            return _apply_priority(targets)
        case RoutingStrategy.COST_OPTIMIZED:
            return _apply_cost_optimized(targets)
        case RoutingStrategy.ROUND_ROBIN:
            return _apply_round_robin(targets, ctx)
        case RoutingStrategy.RANDOM:
            return _apply_random(targets)
        case RoutingStrategy.LKGP:
            return _apply_lkgp(targets, ctx)
        case RoutingStrategy.CONTEXT_RELAY:
            return _apply_context_relay(targets, ctx)
        case RoutingStrategy.HEADROOM:
            return _apply_headroom(targets, ctx)
        case _:
            raise ValueError(f"Unknown routing strategy: {strategy}")
