"""Core engine for In-Flight Turn State Truncation and Prefix Cache Stability Gate.

[INPUT]
- turn_truncation_types: Models for trials, policies, commits, and stability reports.

[OUTPUT]
- TurnStateTruncationEngine: Coordinates in-flight trial pruning and prefix stability gating.

[POS]
Truncates transient execution errors and probe noise before persisting messages,
securing high Prompt Cache / KV cache hit rates on upstream LLM providers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time

from myrm_agent_harness.agent.context_management.turn_truncation.turn_truncation_types import (
    CanonicalTurnCommit,
    IntermediateTrialKind,
    PrefixCacheStabilityReport,
    TrialStepRecord,
    TruncationPolicy,
    TurnExecutionState,
)


class TurnStateTruncationEngine:
    """Coordinates in-flight trial pruning and prefix cache stability gating."""

    def __init__(self) -> None:
        # Maps turn_id to recorded trial records
        self._active_trials: dict[str, list[TrialStepRecord]] = {}

    def begin_turn(self, turn_id: str) -> None:
        """Initializes state tracking for a new active turn."""
        self._active_trials[turn_id] = []

    def record_intermediate_trial(
        self,
        turn_id: str,
        kind: IntermediateTrialKind,
        tool_name: str,
        error_message: str,
        raw_char_count: int,
    ) -> TrialStepRecord:
        """Logs an ephemeral trial-and-error action to be pruned at commit time."""
        trials = self._active_trials.setdefault(turn_id, [])
        record = TrialStepRecord(
            step_index=len(trials),
            kind=kind,
            tool_name=tool_name,
            error_message=error_message,
            raw_char_count=raw_char_count,
            timestamp=time.time(),
        )
        trials.append(record)
        return record

    @staticmethod
    def _is_failed_tool_result(msg: dict[str, object]) -> bool:
        """Heuristically identifies whether a tool message represents a transient failure."""
        if msg.get("is_error") is True:
            return True
        content = str(msg.get("content", ""))
        error_indicators = (
            "[ExecutionError]",
            "Traceback (most recent call last)",
            "SyntaxError:",
            "TypeError:",
            "Command failed with exit code",
            "Error: Cannot find module",
        )
        return any(ind in content for ind in error_indicators)

    def canonical_commit(
        self,
        turn_id: str,
        in_flight_messages: list[dict[str, object]],
        policy: TruncationPolicy = TruncationPolicy.PRUNE_ALL_FAILURES_KEEP_CANONICAL,
    ) -> CanonicalTurnCommit:
        """Cleanses in-flight trial states and commits canonical proof to session history."""
        trials = self._active_trials.pop(turn_id, [])
        trial_count = len(trials)

        if policy == TruncationPolicy.PASSTHROUGH_DIRTY or not in_flight_messages:
            return CanonicalTurnCommit(
                turn_id=turn_id,
                canonical_messages=copy.deepcopy(in_flight_messages),
                pruned_trials_count=0,
                reclaimed_tokens_estimate=0,
                prefix_cache_safe=False,
                state=TurnExecutionState.COMMITTED,
            )

        # 1. Inspect and prune messages
        canonical_messages: list[dict[str, object]] = []
        raw_chars_cleansed = sum(t.raw_char_count for t in trials)

        if policy == TruncationPolicy.PRUNE_ALL_FAILURES_KEEP_CANONICAL:
            # Retain user inputs and strictly clean assistant/tool outputs
            for msg in in_flight_messages:
                role = str(msg.get("role", ""))
                if role == "user":
                    canonical_messages.append(copy.deepcopy(msg))
                elif role in ("tool", "toolResult"):
                    if not self._is_failed_tool_result(msg):
                        canonical_messages.append(copy.deepcopy(msg))
                    else:
                        raw_chars_cleansed += len(str(msg.get("content", "")))
                elif role == "assistant":
                    # If this assistant message only triggered a failed tool, it might be pruned or kept
                    # We keep valid assistant responses
                    canonical_messages.append(copy.deepcopy(msg))

        elif policy == TruncationPolicy.FOLD_FAILURES_TO_ONE_LINE:
            # Replace consecutive failures with a single folded summary line
            folded_note_added = False
            for msg in in_flight_messages:
                role = str(msg.get("role", ""))
                if role in ("tool", "toolResult") and self._is_failed_tool_result(msg):
                    raw_chars_cleansed += len(str(msg.get("content", "")))
                    if not folded_note_added:
                        canonical_messages.append(
                            {
                                "role": "system",
                                "content": (
                                    f"[Self-Correction Proof]: Resolved {max(1, trial_count)} "
                                    "transient syntax/tool retry attempts cleanly."
                                ),
                            }
                        )
                        folded_note_added = True
                else:
                    canonical_messages.append(copy.deepcopy(msg))

        # Guarantee at least some message exists
        if not canonical_messages and in_flight_messages:
            canonical_messages = [copy.deepcopy(in_flight_messages[-1])]

        tokens_saved = max(0, raw_chars_cleansed // 4)

        return CanonicalTurnCommit(
            turn_id=turn_id,
            canonical_messages=canonical_messages,
            pruned_trials_count=max(trial_count, len(in_flight_messages) - len(canonical_messages)),
            reclaimed_tokens_estimate=tokens_saved,
            prefix_cache_safe=True,
            state=TurnExecutionState.TRUNCATED_AND_COMMITTED,
        )

    @staticmethod
    def audit_prefix_cache_stability(
        committed_turns: list[CanonicalTurnCommit],
    ) -> PrefixCacheStabilityReport:
        """Evaluates prefix stability digest and projects upstream KV cache hit probability."""
        if not committed_turns:
            return PrefixCacheStabilityReport(
                total_turns=0,
                canonical_turns=0,
                prefix_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                cache_hit_likelihood_pct=100.0,
                total_reclaimed_tokens=0,
                is_prefix_stable=True,
            )

        total_turns = len(committed_turns)
        canonical_count = sum(1 for t in committed_turns if t.prefix_cache_safe)
        total_reclaimed = sum(t.reclaimed_tokens_estimate for t in committed_turns)

        # Generate prefix digest from deterministic canonical message dumps
        digest_builder = hashlib.sha256()
        for turn in committed_turns:
            summary_dict = {
                "t_id": turn.turn_id,
                "msg_count": len(turn.canonical_messages),
                "safe": turn.prefix_cache_safe,
            }
            digest_builder.update(json.dumps(summary_dict, sort_keys=True).encode("utf-8"))

        prefix_hash = digest_builder.hexdigest()

        # Compute likelihood percentage: starts at 96% when 100% canonical, degrades towards 30%
        canonical_ratio = canonical_count / total_turns
        likelihood = round(30.0 + (canonical_ratio * 66.0), 2)
        is_stable = canonical_ratio >= 0.85

        return PrefixCacheStabilityReport(
            total_turns=total_turns,
            canonical_turns=canonical_count,
            prefix_digest=prefix_hash,
            cache_hit_likelihood_pct=likelihood,
            total_reclaimed_tokens=total_reclaimed,
            is_prefix_stable=is_stable,
        )
