"""Gating engine for Idle & Budget Gated Auto-Memory Consolidation Suite.

[INPUT]
- time (POS: epoch seconds)
- re (POS: text tokenization for info density)
- collections.abc.Sequence, collections.abc.Mapping
- auto_consolidation.models::{AutoMemoryGatingConfig, TurnGatingDecision, BudgetGatingDecision, IdleDetectionState, OverallGatingReport}

[OUTPUT]
- evaluate_idle_status: Checks session inactivity against threshold.
- evaluate_turn_and_info_gain: Enforces turn count and minimum information density.
- evaluate_budget_safety: Enforces token quota safety and cost-ratio guardrails.
- evaluate_composite_gating: Comprehensive gate aggregator producing OverallGatingReport.

[POS]
Dual-gate admission controller and idle detector protecting token quota and memory quality (Item 123).
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence

from myrm_agent_harness.toolkits.memory.auto_consolidation.models import (
    AutoMemoryGatingConfig,
    BudgetGatingDecision,
    IdleDetectionState,
    OverallGatingReport,
    TurnGatingDecision,
)

_TOKEN_PATTERN = re.compile(r"\b[a-zA-Z0-9_\u4e00-\u9fff]{2,}\b")
_TRIVIAL_STOP_WORDS = frozenset({
    "hi", "hello", "hey", "ok", "okay", "yes", "no", "thanks", "thank", "you",
    "there", "how", "can", "help", "are", "welcome", "please", "bye", "good",
    "好的", "好的收到", "收到", "在吗", "在", "嗯", "好", "谢谢", "谢谢你", "继续", "明白了", "行",
    "不客气", "不用谢", "您好", "你好", "再见", "拜拜",
})


def calculate_information_density(messages: Sequence[Mapping[str, str]]) -> float:
    """Compute lexical diversity and substantive content density from messages.

    Returns a normalized float in [0.0, 1.0]. Empty or trivial conversations score low.
    """
    total_tokens = 0
    informative_tokens = 0
    unique_informative: set[str] = set()

    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue
        words = _TOKEN_PATTERN.findall(content.lower())
        for w in words:
            total_tokens += 1
            if w not in _TRIVIAL_STOP_WORDS:
                informative_tokens += 1
                unique_informative.add(w)

    if total_tokens == 0:
        return 0.0

    # Information density combines substantive ratio with lexical richness and volume scale
    substantive_ratio = informative_tokens / total_tokens
    lexical_richness = min(1.0, len(unique_informative) / max(1, informative_tokens))
    volume_scale = min(1.0, informative_tokens / 18.0)
    density = (substantive_ratio * 0.5 + lexical_richness * 0.5) * volume_scale
    return round(density, 4)


def estimate_consolidation_token_cost(messages: Sequence[Mapping[str, str]]) -> int:
    """Heuristically estimate token cost for distilling the provided dialogue."""
    total_chars = sum(len(msg.get("content", "")) for msg in messages)
    # Approx 3.5 chars per token for bilingual text + 350 prompt overhead + 400 completion overhead
    input_tokens = int(total_chars / 3.5) + 350
    expected_output_tokens = 450
    return input_tokens + expected_output_tokens


def evaluate_idle_status(
    session_id: str,
    last_active_timestamp: float,
    current_timestamp: float | None = None,
    config: AutoMemoryGatingConfig | None = None,
) -> IdleDetectionState:
    """Inspect whether the session has been inactive long enough to trigger auto-consolidation."""
    active_config = config or AutoMemoryGatingConfig()
    now = current_timestamp if current_timestamp is not None else time.time()
    idle_seconds = max(0.0, now - last_active_timestamp)
    is_triggered = idle_seconds >= active_config.idle_timeout_seconds

    if is_triggered:
        reason = (
            f"Session inactive for {idle_seconds:.1f}s (threshold: "
            f"{active_config.idle_timeout_seconds:.1f}s). Background consolidation eligible."
        )
    else:
        reason = (
            f"Session still active or below idle threshold ({idle_seconds:.1f}s < "
            f"{active_config.idle_timeout_seconds:.1f}s)."
        )

    return IdleDetectionState(
        session_id=session_id,
        idle_seconds=round(idle_seconds, 2),
        idle_threshold_seconds=active_config.idle_timeout_seconds,
        is_idle_triggered=is_triggered,
        reason=reason,
    )


def evaluate_turn_and_info_gain(
    messages: Sequence[Mapping[str, str]],
    config: AutoMemoryGatingConfig | None = None,
) -> TurnGatingDecision:
    """Evaluate whether dialogue exhibits sufficient turns and non-trivial information."""
    active_config = config or AutoMemoryGatingConfig()
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    total_turns = len(messages)
    effective_turns = max(user_turns, total_turns // 2)

    if effective_turns < active_config.min_turn_count:
        return TurnGatingDecision(
            passed=False,
            turn_count=effective_turns,
            info_density=0.0,
            reason=(
                f"Conversation too brief: {effective_turns} turns (required: "
                f"{active_config.min_turn_count}). Bypassing low-value memory generation."
            ),
        )

    info_density = calculate_information_density(messages)
    if info_density < active_config.min_info_density:
        return TurnGatingDecision(
            passed=False,
            turn_count=effective_turns,
            info_density=info_density,
            reason=(
                f"Information density too low: {info_density:.3f} (required: "
                f"{active_config.min_info_density:.3f}). Classified as trivial chit-chat."
            ),
        )

    return TurnGatingDecision(
        passed=True,
        turn_count=effective_turns,
        info_density=info_density,
        reason=(
            f"Passed turn & info gate: {effective_turns} turns, density "
            f"{info_density:.3f} >= {active_config.min_info_density:.3f}."
        ),
    )


def evaluate_budget_safety(
    remaining_tokens: int,
    messages: Sequence[Mapping[str, str]],
    config: AutoMemoryGatingConfig | None = None,
) -> BudgetGatingDecision:
    """Evaluate token balance adequacy and prevent distillation runaway billing."""
    active_config = config or AutoMemoryGatingConfig()

    if remaining_tokens < active_config.min_remaining_budget_tokens:
        return BudgetGatingDecision(
            passed=False,
            remaining_tokens=remaining_tokens,
            estimated_cost_tokens=0,
            cost_ratio=1.0,
            reason=(
                f"Token budget depleted/critical: {remaining_tokens} tokens available "
                f"< minimum floor {active_config.min_remaining_budget_tokens}. Pausing background task."
            ),
        )

    estimated_cost = estimate_consolidation_token_cost(messages)
    cost_ratio = estimated_cost / max(1, remaining_tokens)

    if cost_ratio > active_config.max_consolidation_cost_ratio:
        return BudgetGatingDecision(
            passed=False,
            remaining_tokens=remaining_tokens,
            estimated_cost_tokens=estimated_cost,
            cost_ratio=round(cost_ratio, 4),
            reason=(
                f"Consolidation cost ratio ({cost_ratio:.2%}) exceeds safe ceiling "
                f"({active_config.max_consolidation_cost_ratio:.2%}). Estimated cost {estimated_cost} tokens."
            ),
        )

    return BudgetGatingDecision(
        passed=True,
        remaining_tokens=remaining_tokens,
        estimated_cost_tokens=estimated_cost,
        cost_ratio=round(cost_ratio, 4),
        reason=(
            f"Passed budget gate: remaining {remaining_tokens} tokens, cost {estimated_cost} "
            f"({cost_ratio:.2%} <= {active_config.max_consolidation_cost_ratio:.2%})."
        ),
    )


def evaluate_composite_gating(
    session_id: str,
    messages: Sequence[Mapping[str, str]],
    remaining_tokens: int,
    last_active_timestamp: float,
    current_timestamp: float | None = None,
    config: AutoMemoryGatingConfig | None = None,
    require_idle: bool = True,
) -> OverallGatingReport:
    """Combine idle inspection, turn/info gate, and budget gate into an authoritative verdict."""
    active_config = config or AutoMemoryGatingConfig()

    idle_state = evaluate_idle_status(
        session_id=session_id,
        last_active_timestamp=last_active_timestamp,
        current_timestamp=current_timestamp,
        config=active_config,
    )
    turn_decision = evaluate_turn_and_info_gain(messages, config=active_config)
    budget_decision = evaluate_budget_safety(remaining_tokens, messages, config=active_config)

    if not active_config.enabled:
        return OverallGatingReport(
            session_id=session_id,
            should_consolidate=False,
            turn_decision=turn_decision,
            budget_decision=budget_decision,
            idle_state=idle_state,
            final_rationale="Auto-memory consolidation is disabled in configuration.",
        )

    idle_condition_met = (not require_idle) or idle_state.is_idle_triggered
    should_consolidate = bool(
        idle_condition_met and turn_decision.passed and budget_decision.passed
    )

    reasons: list[str] = []
    if require_idle and not idle_state.is_idle_triggered:
        reasons.append("Waiting for idle timeout.")
    if not turn_decision.passed:
        reasons.append(turn_decision.reason)
    if not budget_decision.passed:
        reasons.append(budget_decision.reason)

    final_rationale = (
        "All gates cleared. Automated background memory consolidation approved."
        if should_consolidate
        else "; ".join(reasons)
    )

    return OverallGatingReport(
        session_id=session_id,
        should_consolidate=should_consolidate,
        turn_decision=turn_decision,
        budget_decision=budget_decision,
        idle_state=idle_state,
        final_rationale=final_rationale,
    )
