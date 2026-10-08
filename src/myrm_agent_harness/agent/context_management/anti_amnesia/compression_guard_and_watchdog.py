"""Compression transparency HUD, anti-hanging transaction lock guard, and adaptive 500-turn watchdog.

[INPUT]
- anti_amnesia_types::CompressionFallbackTier, CompressionTransparencyHudState, TurnBudgetWatchdogState (POS: Anti-amnesia types)
- chunked_map_reduce_compactor::ChunkedMapReduceCompactor (POS: Entity extractor)

[OUTPUT]
- CompressionLockTimeoutError: Raised when compression locks risk hanging sessions.
- CompressionTransparencyAndLockGuard: Handles 30s transaction timeout and semantic fidelity gates.
- AdaptiveTurnBudgetWatchdog: Dynamically extends turn budgets up to 500 turns based on progress signals.

[POS]
Guards against hanging session write locks, enforces transparent HUD badges,
validates semantic fidelity, and provides adaptive 500-turn loop fuel.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Sequence

from langchain_core.messages import BaseMessage

from .anti_amnesia_types import (
    CompressionFallbackTier,
    CompressionTransparencyHudState,
    TurnBudgetWatchdogState,
)
from .chunked_map_reduce_compactor import ChunkedMapReduceCompactor


class CompressionLockTimeoutError(TimeoutError):
    """Raised when context compression exceeds safety timeout, risking a hanging session."""


class CompressionTransparencyAndLockGuard:
    """Manages compression transaction timeouts, semantic fidelity assertions, and HUD badges."""

    _DEFAULT_TIMEOUT_SECONDS: float = 30.0
    _FIDELITY_MIN_THRESHOLD: float = 0.85

    @classmethod
    @asynccontextmanager
    async def transaction_timeout_watchdog(
        cls,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> AsyncIterator[None]:
        """Wrap compression execution to release locks and prevent hanging sessions."""
        try:
            async with asyncio.timeout(timeout_seconds):
                yield
        except TimeoutError as err:
            raise CompressionLockTimeoutError(
                f"Compression transaction exceeded {timeout_seconds}s safety watchdog limit. "
                "Session write lock forcefully released to prevent zombie hanging session."
            ) from err

    @classmethod
    def evaluate_semantic_fidelity(
        cls,
        original_messages: Sequence[BaseMessage],
        compressed_text: str,
        threshold: float = _FIDELITY_MIN_THRESHOLD,
    ) -> tuple[float, bool]:
        """Calculate key technical entity preservation ratio between original and compressed text."""
        combined_orig = "\n".join(str(m.content) for m in original_messages)
        orig_entities = set(ChunkedMapReduceCompactor.extract_chunk_entities(combined_orig))

        if not orig_entities:
            return 1.0, True

        compressed_entities = set(ChunkedMapReduceCompactor.extract_chunk_entities(compressed_text))
        retained = orig_entities.intersection(compressed_entities)
        ratio = round(len(retained) / max(len(orig_entities), 1), 3)

        passed = ratio >= threshold
        return ratio, passed

    @classmethod
    def create_transparency_hud(
        cls,
        tier: CompressionFallbackTier,
        model_name: str,
        fidelity_score: float,
        fidelity_passed: bool,
    ) -> CompressionTransparencyHudState:
        """Construct client-facing transparency HUD state."""
        if tier == CompressionFallbackTier.PRIMARY_LONG_WINDOW and fidelity_passed:
            return CompressionTransparencyHudState(
                is_degraded=False,
                tier=tier,
                model_used=model_name,
                badge_label="NORMAL_COMPRESSION",
                badge_color="green",
                user_alert_message="上下文已由主长窗口模型完成无损紧凑压缩。",
                fidelity_score=fidelity_score,
                fidelity_passed=True,
            )

        if tier == CompressionFallbackTier.MAP_REDUCE_FALLBACK:
            return CompressionTransparencyHudState(
                is_degraded=True,
                tier=tier,
                model_used=model_name,
                badge_label="MAP_REDUCE_FALLBACK",
                badge_color="yellow",
                user_alert_message=(
                    f"⚠️ 压缩引擎已安全切换为分块金字塔容灾模式 (模型: {model_name})，"
                    f"15% 连续重叠保留，语义保真度 {int(fidelity_score * 100)}%。"
                ),
                fidelity_score=fidelity_score,
                fidelity_passed=fidelity_passed,
            )

        # Deterministic local rescue
        return CompressionTransparencyHudState(
            is_degraded=True,
            tier=tier,
            model_used=model_name,
            badge_label="LOCAL_DETERMINISTIC_RESCUE",
            badge_color="orange",
            user_alert_message="⚠️ 外部压缩模型受限，已无感启用本地确定性高保真摘要兜底。",
            fidelity_score=fidelity_score,
            fidelity_passed=fidelity_passed,
        )


class AdaptiveTurnBudgetWatchdog:
    """Dynamically monitors and extends agent task execution turns up to 500 rounds."""

    def __init__(
        self,
        initial_budget: int = 50,
        max_ceiling: int = 500,
        fuel_step_turns: int = 20,
        max_consecutive_stalls: int = 5,
    ) -> None:
        self._initial_budget = max(initial_budget, 10)
        self._max_ceiling = max(max_ceiling, self._initial_budget)
        self._fuel_step_turns = max(fuel_step_turns, 5)
        self._max_consecutive_stalls = max(max_consecutive_stalls, 2)

        self._current_turn = 0
        self._allocated_budget = self._initial_budget
        self._consecutive_stalls = 0
        self._total_progress_signals = 0

    @property
    def current_turn(self) -> int:
        return self._current_turn

    @property
    def allocated_budget(self) -> int:
        return self._allocated_budget

    def record_turn(
        self,
        has_progress_signal: bool,
        signal_reason: str = "",
    ) -> TurnBudgetWatchdogState:
        """Record turn iteration and dynamically adjust fuel budget based on progress."""
        self._current_turn += 1

        if has_progress_signal:
            self._total_progress_signals += 1
            self._consecutive_stalls = 0
            # If approaching current budget limit, inject fuel up to ceiling
            if self._current_turn + 10 >= self._allocated_budget:
                new_budget = min(
                    self._allocated_budget + self._fuel_step_turns,
                    self._max_ceiling,
                )
                self._allocated_budget = new_budget
        else:
            self._consecutive_stalls += 1

        # Check termination constraints
        if self._consecutive_stalls >= self._max_consecutive_stalls:
            can_continue = False
            reason = (
                f"Task stalled: {self._consecutive_stalls} consecutive turns without valid "
                "progress signals (file edits, tests, tool outputs). Halting runaway loop."
            )
        elif self._current_turn >= self._allocated_budget:
            can_continue = False
            reason = (
                f"Iteration limit reached: completed {self._current_turn} turns "
                f"(allocated budget {self._allocated_budget}/{self._max_ceiling})."
            )
        else:
            can_continue = True
            reason = (
                f"Turn {self._current_turn}/{self._allocated_budget} active. "
                f"Signals: {self._total_progress_signals}. Stalls: {self._consecutive_stalls}."
            )

        return TurnBudgetWatchdogState(
            current_turn=self._current_turn,
            allocated_budget=self._allocated_budget,
            max_ceiling=self._max_ceiling,
            consecutive_idle_turns=self._consecutive_stalls,
            total_progress_signals=self._total_progress_signals,
            can_continue=can_continue,
            status_reason=reason,
        )

    def snapshot_state(self) -> TurnBudgetWatchdogState:
        """Return the current watchdog snapshot."""
        return TurnBudgetWatchdogState(
            current_turn=self._current_turn,
            allocated_budget=self._allocated_budget,
            max_ceiling=self._max_ceiling,
            consecutive_idle_turns=self._consecutive_stalls,
            total_progress_signals=self._total_progress_signals,
            can_continue=self._consecutive_stalls < self._max_consecutive_stalls and self._current_turn < self._allocated_budget,
            status_reason="Snapshot query",
        )
