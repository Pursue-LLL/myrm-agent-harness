"""Unified facade for context compression fallback guard, window alignment, and anti-amnesia pipeline.

[INPUT]
- anti_amnesia_types::* (POS: Domain data models)
- window_capacity_asserter::WindowCapacityAsserter, InsufficientWindowCapacityError (POS: Capacity asserter)
- chunked_map_reduce_compactor::ChunkedMapReduceCompactor (POS: Map-reduce compactor)
- compression_guard_and_watchdog::CompressionTransparencyAndLockGuard, AdaptiveTurnBudgetWatchdog (POS: Watchdogs and HUD)
- langchain_core.messages::BaseMessage, SystemMessage (POS: LangChain message abstractions)
- utils.token_estimation::estimate_content_tokens (POS: Token estimation)

[OUTPUT]
- AntiAmnesiaSuite: Developer-facing facade orchestrating physical assertions, map-reduce, HUD, and 500-turn watchdog.

[POS]
Top-level entry point preventing silent fallback truncation and catastrophic amnesia,
and granting long-running agent tasks adaptive iteration fuel up to 500 turns.
"""

from __future__ import annotations

from typing import Sequence

from langchain_core.messages import BaseMessage, SystemMessage

from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

from .anti_amnesia_types import (
    AntiAmnesiaExecutionReport,
    CapacityAssertionResult,
    CompressionFallbackTier,
    ModelWindowSpec,
)
from .chunked_map_reduce_compactor import ChunkedMapReduceCompactor
from .compression_guard_and_watchdog import (
    AdaptiveTurnBudgetWatchdog,
    CompressionTransparencyAndLockGuard,
)
from .window_capacity_asserter import WindowCapacityAsserter


class AntiAmnesiaSuite:
    """Industrial-grade anti-amnesia guard for context compression and long-horizon tasks."""

    @classmethod
    def assert_model_capacity(
        cls,
        total_tokens: int,
        spec: ModelWindowSpec,
    ) -> CapacityAssertionResult:
        """Assert whether target compression model can safely ingest total_tokens without truncation."""
        return WindowCapacityAsserter.assert_capacity_or_raise(total_tokens, spec)

    @classmethod
    def create_turn_watchdog(
        cls,
        initial_budget: int = 50,
        max_ceiling: int = 500,
        fuel_step_turns: int = 20,
        max_consecutive_stalls: int = 5,
    ) -> AdaptiveTurnBudgetWatchdog:
        """Create a new adaptive 500-turn iteration watchdog."""
        return AdaptiveTurnBudgetWatchdog(
            initial_budget=initial_budget,
            max_ceiling=max_ceiling,
            fuel_step_turns=fuel_step_turns,
            max_consecutive_stalls=max_consecutive_stalls,
        )

    @classmethod
    async def compress_with_anti_amnesia_protection(
        cls,
        messages: Sequence[BaseMessage],
        *,
        primary_spec: ModelWindowSpec | None = None,
        fallback_spec: ModelWindowSpec | None = None,
        watchdog: AdaptiveTurnBudgetWatchdog | None = None,
        timeout_seconds: float = 30.0,
    ) -> tuple[list[BaseMessage], AntiAmnesiaExecutionReport]:
        """Execute context compression with strict anti-amnesia and anti-truncation gates.

        Returns:
            Tuple of (new_compressed_messages, audit_report).
        """
        orig_tokens = sum(estimate_content_tokens(str(m.content)) for m in messages)

        # 1. Select safe tier without silent truncation
        tier, chosen_spec = WindowCapacityAsserter.select_safe_compression_tier(
            total_tokens=orig_tokens,
            primary_spec=primary_spec,
            fallback_spec=fallback_spec,
        )

        model_name = chosen_spec.model_name if chosen_spec is not None else "local-deterministic"

        # 2. Execute with transaction timeout watchdog to avoid hanging locks
        async with CompressionTransparencyAndLockGuard.transaction_timeout_watchdog(timeout_seconds):
            if tier == CompressionFallbackTier.MAP_REDUCE_FALLBACK and chosen_spec is not None:
                # Hierarchical map-reduce with 15% continuity overlap
                unified_msg, _ = ChunkedMapReduceCompactor.execute_map_reduce_compaction(
                    messages=messages,
                    model_spec=chosen_spec,
                )
                new_messages: list[BaseMessage] = [unified_msg]
            elif tier == CompressionFallbackTier.PRIMARY_LONG_WINDOW and chosen_spec is not None:
                # Primary monolithic compression fits safely in target window
                unified_msg, _ = ChunkedMapReduceCompactor.execute_map_reduce_compaction(
                    messages=messages,
                    model_spec=chosen_spec,
                )
                new_messages = [unified_msg]
            else:
                # Deterministic rescue
                unified_msg, _ = ChunkedMapReduceCompactor.execute_map_reduce_compaction(
                    messages=messages,
                    model_spec=ModelWindowSpec(
                        model_name="local-rescue",
                        context_window=32768,
                        max_output_tokens=2048,
                    ),
                )
                new_messages = [unified_msg]

        # 3. Evaluate semantic fidelity and build HUD
        compressed_text = "\n".join(str(m.content) for m in new_messages)
        final_tokens = sum(estimate_content_tokens(str(m.content)) for m in new_messages)
        reclaimed = max(orig_tokens - final_tokens, 0)
        ratio = round(final_tokens / max(orig_tokens, 1), 3)

        fidelity_score, fidelity_passed = CompressionTransparencyAndLockGuard.evaluate_semantic_fidelity(
            original_messages=messages,
            compressed_text=compressed_text,
        )

        hud_state = CompressionTransparencyAndLockGuard.create_transparency_hud(
            tier=tier,
            model_name=model_name,
            fidelity_score=fidelity_score,
            fidelity_passed=fidelity_passed,
        )

        watchdog_state = watchdog.snapshot_state() if watchdog is not None else None

        report = AntiAmnesiaExecutionReport(
            fallback_tier=tier,
            tokens_before=orig_tokens,
            tokens_after=final_tokens,
            tokens_reclaimed=reclaimed,
            compression_ratio=ratio,
            hud_state=hud_state,
            key_entities_preserved_ratio=fidelity_score,
            watchdog_state=watchdog_state,
        )

        return new_messages, report


# Alias for full roadmap specification name
ContextCompressionSilentFallbackGuardAndWindowAlignedAntiAmnesiaSuite = AntiAmnesiaSuite
