"""Core engine for Token Burn Rate Governor and Runaway Consumption Shield (Item 220).

[INPUT]
- TokenUsageRecord: Per-call token consumption data.
- TokenGovernorConfig: Threshold limits for rate velocity, backoff, and pruning.
- Tool schemas and intent descriptors for dynamic lean mode activation.

[OUTPUT]
- TokenBurnRateGovernorEngine: Rolling burn velocity monitor and 429 backoff governor.
- BurnRateTelemetry: Real-time tokens/minute and zone classification.
- LeanToolPruningDecision: JIT tool reduction reducing floor prompt noise by up to 70%.
- RateLimitBackoffDecision: Adaptive exponential backoff and model diversion recommendation.

[POS]
- Protects agents and users against runaway cost explosions and disruptive 429 rate limits,
- enabling long-running multi-turn workflows to execute sustainably and smoothly.
"""

from __future__ import annotations

import math
import threading
import time

from .token_governor_types import (
    BurnRateTelemetry,
    BurnRateZone,
    LeanToolPruningDecision,
    RateLimitBackoffDecision,
    TokenGovernorConfig,
    TokenUsageRecord,
    ToolLeanMode,
)


class TokenBurnRateGovernorEngine:
    """Monitors rolling token burn velocity, governs tool surface, and mitigates 429 errors."""

    def __init__(self, config: TokenGovernorConfig | None = None) -> None:
        self._config: TokenGovernorConfig = config or TokenGovernorConfig()
        self._usage_history: dict[str, list[TokenUsageRecord]] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def config(self) -> TokenGovernorConfig:
        """Returns active governor configuration."""
        return self._config

    def record_usage(
        self,
        session_id: str,
        record: TokenUsageRecord,
    ) -> BurnRateTelemetry:
        """Records a token consumption event and evaluates current burn velocity.

        Args:
            session_id: Identifier of the active conversation session.
            record: Strongly typed token consumption record.

        Returns:
            Computed BurnRateTelemetry reflecting updated rolling metrics.
        """
        with self._lock:
            if session_id not in self._usage_history:
                self._usage_history[session_id] = []

            history = self._usage_history[session_id]
            history.append(record)

            # Evict records older than capacity bounds
            if len(history) > self._config.max_history_records:
                history.pop(0)

        return self.evaluate_burn_rate(session_id)

    def evaluate_burn_rate(
        self,
        session_id: str,
        as_of_timestamp: float | None = None,
    ) -> BurnRateTelemetry:
        """Evaluates rolling window token consumption velocity for a session.

        Args:
            session_id: Session identifier.
            as_of_timestamp: Optional evaluation timestamp (defaults to current time).

        Returns:
            BurnRateTelemetry with calculated tokens-per-minute and health zone.
        """
        now = as_of_timestamp if as_of_timestamp is not None else time.time()
        window_sec = self._config.rolling_window_seconds
        cutoff_time = now - window_sec

        with self._lock:
            records = list(self._usage_history.get(session_id, []))

        # Filter records falling strictly within the rolling window
        in_window = [r for r in records if r.timestamp >= cutoff_time]

        if not in_window:
            return BurnRateTelemetry(
                session_id=session_id,
                window_seconds=window_sec,
                total_tokens_in_window=0,
                burn_rate_per_minute=0.0,
                burn_rate_per_hour=0.0,
                zone=BurnRateZone.NORMAL_GREEN,
                recommended_action="Token consumption rate is normal and sustainable.",
                sample_count=0,
            )

        total_tokens = sum(r.total_tokens for r in in_window)

        # In a rolling window of window_sec, normalize by the window base to reflect true window velocity
        # and prevent single-sample time-delta artifacts from triggering false spikes.
        oldest_ts = min(r.timestamp for r in in_window)
        elapsed_seconds = max(float(window_sec), now - oldest_ts)

        # Normalize to per-minute and per-hour rates
        tpm = (total_tokens / elapsed_seconds) * 60.0
        tph = tpm * 60.0

        # Classify operational zone
        if tpm >= self._config.red_exhaustion_tpm:
            zone = BurnRateZone.EXHAUSTION_RED
            action = (
                "Critical token exhaustion risk! Impose rate-limit throttle and prompt compaction."
            )
        elif tpm >= self._config.orange_throttle_tpm:
            zone = BurnRateZone.THROTTLE_ORANGE
            action = (
                "Elevated token burn velocity. Switch to lean tools and prune inactive schemas."
            )
        elif tpm >= self._config.yellow_spike_tpm:
            zone = BurnRateZone.SPIKE_YELLOW
            action = (
                "Consumption spike detected. Monitor subagent iterations and summarize history."
            )
        else:
            zone = BurnRateZone.NORMAL_GREEN
            action = "Token consumption rate is normal and sustainable."

        return BurnRateTelemetry(
            session_id=session_id,
            window_seconds=window_sec,
            total_tokens_in_window=total_tokens,
            burn_rate_per_minute=round(tpm, 2),
            burn_rate_per_hour=round(tph, 2),
            zone=zone,
            recommended_action=action,
            sample_count=len(in_window),
        )

    def resolve_lean_tool_pruning(
        self,
        all_tools: list[str],
        conversation_intent: str = "",
        active_zone: BurnRateZone = BurnRateZone.NORMAL_GREEN,
    ) -> LeanToolPruningDecision:
        """Determines which tool schemas to prune dynamically based on intent and burn rate.

        Args:
            all_tools: Full surface list of available tool names.
            conversation_intent: User's immediate conversational task description.
            active_zone: Current operational health zone.

        Returns:
            LeanToolPruningDecision with active vs pruned tool names and noise reduction ratio.
        """
        if len(all_tools) <= 2:
            return LeanToolPruningDecision(
                mode=ToolLeanMode.FULL_SURFACE,
                active_tool_names=list(all_tools),
                pruned_tool_names=[],
                noise_reduction_ratio=0.0,
                reason="Tool surface is already minimal; no pruning necessary.",
            )

        intent_lower = conversation_intent.lower()

        # Under exhaustion or pure conversational intent, retain only essential interaction tools
        is_simple_chat = any(
            token in intent_lower
            for token in ("hello", "hi", "你好", "简单问答", "chat", "explain", "解释")
        )
        if active_zone == BurnRateZone.EXHAUSTION_RED or is_simple_chat:
            essential_keywords = ("ask_question", "read_file", "view_file")
            active: list[str] = [
                t for t in all_tools if any(k in t.lower() for k in essential_keywords)
            ]
            if not active and all_tools:
                active = [all_tools[0]]

            pruned = [t for t in all_tools if t not in active]
            reduction = len(pruned) / len(all_tools)
            return LeanToolPruningDecision(
                mode=ToolLeanMode.MINIMAL_CONVERSATIONAL,
                active_tool_names=active,
                pruned_tool_names=pruned,
                noise_reduction_ratio=round(reduction, 2),
                reason="Minimal conversational mode activated to avert severe token burn.",
            )

        # Under elevated consumption or moderate intent, perform domain-scoped pruning
        if active_zone in (BurnRateZone.THROTTLE_ORANGE, BurnRateZone.SPIKE_YELLOW):
            active_set: set[str] = set()

            # Intent keywords mapping
            wants_execution = any(
                k in intent_lower for k in ("run", "exec", "test", "bash", "command", "build")
            )
            wants_files = any(
                k in intent_lower for k in ("file", "code", "read", "view", "write", "edit")
            )
            wants_search = any(k in intent_lower for k in ("search", "find", "grep", "lookup"))

            for t in all_tools:
                tl = t.lower()
                if wants_execution and any(k in tl for k in ("run", "command", "bash", "terminal")):
                    active_set.add(t)
                elif wants_files and any(k in tl for k in ("file", "edit", "write", "replace")):
                    active_set.add(t)
                elif wants_search and any(k in tl for k in ("search", "find", "view", "read")):
                    active_set.add(t)

            # Fallback to keep at least top 2 core tools if none matched
            if not active_set:
                active_set = set(all_tools[:2])

            active = [t for t in all_tools if t in active_set]
            pruned = [t for t in all_tools if t not in active_set]
            reduction = len(pruned) / len(all_tools)
            return LeanToolPruningDecision(
                mode=ToolLeanMode.LEAN_PRUNED,
                active_tool_names=active,
                pruned_tool_names=pruned,
                noise_reduction_ratio=round(reduction, 2),
                reason="Domain-scoped lean pruning applied due to elevated burn rate.",
            )

        # Default: Full surface retained
        return LeanToolPruningDecision(
            mode=ToolLeanMode.FULL_SURFACE,
            active_tool_names=list(all_tools),
            pruned_tool_names=[],
            noise_reduction_ratio=0.0,
            reason="Token burn velocity is healthy; full tool surface retained.",
        )

    def handle_provider_429_backoff(
        self,
        retry_after_header: float | str | None = None,
        attempt_index: int = 1,
        fallback_candidates: list[str] | None = None,
    ) -> RateLimitBackoffDecision:
        """Computes adaptive backoff delay and evaluates candidate model diversion for 429 limits.

        Args:
            retry_after_header: Optional raw value from Retry-After HTTP response header.
            attempt_index: 1-indexed count of consecutive retry attempts.
            fallback_candidates: Optional ordered list of cheaper/alternative model names.

        Returns:
            RateLimitBackoffDecision indicating retry clearance, backoff delay, and fallback advice.
        """
        # Determine backoff duration
        parsed_delay: float | None = None
        if retry_after_header is not None:
            try:
                val = float(retry_after_header)
                if val > 0:
                    parsed_delay = min(self._config.max_backoff_seconds, val)
            except (ValueError, TypeError):
                parsed_delay = None

        if parsed_delay is None:
            # Exponential backoff calculation: base * 2^(attempt - 1)
            raw_backoff = self._config.default_backoff_base_seconds * (2 ** (attempt_index - 1))
            parsed_delay = min(self._config.max_backoff_seconds, max(0.5, raw_backoff))

        # Check if max retry attempts exceeded
        if attempt_index > self._config.max_retry_attempts:
            fallback = fallback_candidates[0] if fallback_candidates else None
            return RateLimitBackoffDecision(
                should_retry=False,
                backoff_seconds=parsed_delay,
                suggest_model_fallback=bool(fallback),
                fallback_model_candidate=fallback,
                attempt_index=attempt_index,
                reason=f"Exceeded max retry attempts ({self._config.max_retry_attempts}) under persistent 429 limits.",
            )

        # Suggest fallback after repeated attempts if candidates exist
        suggest_fallback = attempt_index >= 2 and bool(fallback_candidates)
        fallback_candidate = fallback_candidates[0] if suggest_fallback else None

        reason = (
            f"Transient 429 rate limit. Backing off for {parsed_delay:.2f}s (attempt {attempt_index})."
        )
        if suggest_fallback and fallback_candidate:
            reason += f" Suggesting diversion to fallback model '{fallback_candidate}'."

        return RateLimitBackoffDecision(
            should_retry=True,
            backoff_seconds=parsed_delay,
            suggest_model_fallback=suggest_fallback,
            fallback_model_candidate=fallback_candidate,
            attempt_index=attempt_index,
            reason=reason,
        )

    def clear_session(self, session_id: str) -> None:
        """Clears all historical token usage records for the given session."""
        with self._lock:
            self._usage_history.pop(session_id, None)

    def get_session_summary(self, session_id: str) -> dict[str, object]:
        """Returns diagnostic statistics for an individual session."""
        with self._lock:
            records = list(self._usage_history.get(session_id, []))

        total_prompt = sum(r.prompt_tokens for r in records)
        total_completion = sum(r.completion_tokens for r in records)
        total_all = sum(r.total_tokens for r in records)

        return {
            "session_id": session_id,
            "record_count": len(records),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "cumulative_tokens": total_all,
        }
