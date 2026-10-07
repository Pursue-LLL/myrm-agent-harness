"""In-Context Next Action and Question Predictor.

Coordinates artifact-aware heuristic derivation and optional lightweight
model inference to proactively surface clickable next actions to the user.

[INPUT]
- runtime.context.artifact_heuristic_rule_engine::ArtifactHeuristicRuleEngine (POS: Artifact-aware heuristic
  rule engine for next action prediction.)
- runtime.context.next_action_predictor_types::ActionIntentType, NextActionPredictionReport,
  NextActionPredictorConfig, PredictedActionChip, PredictionContextInput (POS: Types and data contracts for
  In-Context Next Action and Question Predictor.)

[OUTPUT]
- InContextNextActionPredictor: Predictor orchestrating heuristic evaluation and optional model-assisted
  chips.

[POS]
In-Context Next Action and Question Predictor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from myrm_agent_harness.runtime.context.artifact_heuristic_rule_engine import (
    ArtifactHeuristicRuleEngine,
)
from myrm_agent_harness.runtime.context.next_action_predictor_types import (
    ActionIntentType,
    NextActionPredictionReport,
    NextActionPredictorConfig,
    PredictedActionChip,
    PredictionContextInput,
)

logger = logging.getLogger(__name__)

LlmActionPredictorCallable = Callable[
    [PredictionContextInput], Awaitable[list[PredictedActionChip]]
]


class InContextNextActionPredictor:
    """Predictor orchestrating heuristic evaluation and optional model-assisted chips."""

    def __init__(
        self,
        config: NextActionPredictorConfig | None = None,
        rule_engine: ArtifactHeuristicRuleEngine | None = None,
        llm_predictor: LlmActionPredictorCallable | None = None,
    ) -> None:
        self._config = config or NextActionPredictorConfig()
        self._rule_engine = rule_engine or ArtifactHeuristicRuleEngine()
        self._llm_predictor = llm_predictor

    def predict_sync(self, ctx: PredictionContextInput) -> NextActionPredictionReport:
        """Derive action chips synchronously using the deterministic rule engine."""
        start_time = time.perf_counter()

        raw_chips: list[PredictedActionChip] = []
        if self._config.enable_heuristic:
            raw_chips = self._rule_engine.evaluate(ctx)

        final_chips = self._filter_and_rank(raw_chips)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return NextActionPredictionReport(
            session_id=ctx.session_id,
            chips=final_chips,
            engine_source="heuristic_engine",
            duration_ms=round(duration_ms, 2),
            has_test_recommendation=any(
                c.intent == ActionIntentType.TEST_VERIFICATION for c in final_chips
            ),
            fallback_used=False,
        )

    async def predict_async(
        self,
        ctx: PredictionContextInput,
        timeout_seconds: float = 3.0,
    ) -> NextActionPredictionReport:
        """Derive action chips asynchronously, blending heuristics and optional LLM."""
        start_time = time.perf_counter()
        fallback_used = False
        source = "heuristic_engine"
        candidates: list[PredictedActionChip] = []

        # 1. Deterministic heuristic run
        if self._config.enable_heuristic:
            candidates.extend(self._rule_engine.evaluate(ctx))

        # 2. Optional light model invocation with strict timeout guard
        if self._llm_predictor is not None:
            try:
                llm_chips = await asyncio.wait_for(
                    self._llm_predictor(ctx),
                    timeout=timeout_seconds,
                )
                if llm_chips:
                    candidates.extend(llm_chips)
                    source = "blended_heuristic_and_llm"
            except (TimeoutError, Exception) as exc:
                logger.warning(
                    "Optional LLM next-action prediction bypassed: %s",
                    str(exc),
                )
                fallback_used = True

        final_chips = self._filter_and_rank(candidates)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return NextActionPredictionReport(
            session_id=ctx.session_id,
            chips=final_chips,
            engine_source=source,
            duration_ms=round(duration_ms, 2),
            has_test_recommendation=any(
                c.intent == ActionIntentType.TEST_VERIFICATION for c in final_chips
            ),
            fallback_used=fallback_used,
        )

    def _filter_and_rank(
        self, chips: list[PredictedActionChip]
    ) -> list[PredictedActionChip]:
        """Deduplicate, filter by confidence threshold, and truncate to max count."""
        # Filter by minimum confidence
        valid_chips = [
            c for c in chips if c.confidence >= self._config.min_confidence
        ]

        # Sort primarily by confidence descending
        valid_chips.sort(key=lambda c: c.confidence, reverse=True)

        # Deduplication
        seen_keys: set[str] = set()
        deduped: list[PredictedActionChip] = []

        for chip in valid_chips:
            key = (
                chip.intent.value
                if self._config.deduplicate_by_intent
                else chip.label.strip().lower()
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(chip)
            if len(deduped) >= self._config.max_chips:
                break

        return deduped
