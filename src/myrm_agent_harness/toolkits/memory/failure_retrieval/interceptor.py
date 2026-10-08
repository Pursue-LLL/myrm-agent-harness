"""Failure trigger interceptor for AI agent tool invocations.

P0 delivery for Item 109 in topic_01 memory roadmap.
Acts as an automated Skill-style hook: intercepts execution errors, extracts fingerprints,
and queries historical session solutions to inject direct fixes without requiring user instruction.

[INPUT]
- toolkits.memory.failure_retrieval.fingerprint::ErrorFingerprintExtractor (POS: Error fingerprint extractor
  for failure-triggered session retrieval.)
- toolkits.memory.failure_retrieval.models::FailureRetrievalResult, FailureTriggerConfig (POS: Domain models
  for failure-triggered historical session retrieval.)
- toolkits.memory.failure_retrieval.search_engine::FailureHistoricalSessionSearchEngine (POS: Search engine
  indexing and retrieving historical session solutions and failures.)

[OUTPUT]
- FailureTriggerInterceptor: Non-invasive error interceptor that automatically triggers historical session
  resolution searches.

[POS]
Failure trigger interceptor for AI agent tool invocations.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.failure_retrieval.fingerprint import (
    ErrorFingerprintExtractor,
)
from myrm_agent_harness.toolkits.memory.failure_retrieval.models import (
    FailureRetrievalResult,
    FailureTriggerConfig,
)
from myrm_agent_harness.toolkits.memory.failure_retrieval.search_engine import (
    FailureHistoricalSessionSearchEngine,
)

logger = logging.getLogger(__name__)


class FailureTriggerInterceptor:
    """Non-invasive error interceptor that automatically triggers historical session resolution searches."""

    def __init__(
        self,
        search_engine: FailureHistoricalSessionSearchEngine | None = None,
        extractor: ErrorFingerprintExtractor | None = None,
        config: FailureTriggerConfig | None = None,
    ) -> None:
        self._search_engine = search_engine or FailureHistoricalSessionSearchEngine()
        self._extractor = extractor or ErrorFingerprintExtractor()
        self._config = config or FailureTriggerConfig()

    @property
    def config(self) -> FailureTriggerConfig:
        """Current interceptor runtime configuration."""
        return self._config

    def on_execution_failure(
        self,
        raw_error: str,
        tool_name: str = "",
        exit_code: int | None = None,
        error_type: str | None = None,
    ) -> FailureRetrievalResult | None:
        """Hook invoked when a tool call fails or command exits with non-zero status.

        Extracts error fingerprint and automatically searches historical sessions for solutions.
        """
        if not self._config.enabled or not self._config.auto_trigger_on_error:
            logger.debug("FailureTriggerInterceptor skipped (enabled=%s)", self._config.enabled)
            return None

        # 1. Extract error fingerprint
        fingerprint = self._extractor.extract(
            raw_error=raw_error,
            error_type=error_type,
            tool_name=tool_name,
            exit_code=exit_code,
        )

        # 2. Search historical sessions
        result = self._search_engine.search(
            fingerprint=fingerprint,
            top_n=self._config.max_matches,
            include_cautionary=self._config.include_cautionary_failures,
        )

        logger.info(
            "FailureTriggerInterceptor: error=%s on tool=%s -> found %d historical resolutions",
            fingerprint.error_type,
            tool_name,
            result.total_matched,
        )
        return result

    def format_resolution_guidance(self, result: FailureRetrievalResult) -> str:
        """Format retrieval result into a prompt guidance block ready for agent self-correction."""
        if result.total_matched == 0:
            return ""

        lines = [
            f"[FAILURE SELF-HEALING ADVICE for {result.query_fingerprint.error_type}]:",
        ]

        if result.successful_resolutions:
            lines.append("  PROVEN HISTORICAL FIXES:")
            for s in result.successful_resolutions:
                lines.append(f"  - Session [{s.session_id} Turn {s.turn_index}]: {s.solution_snippet}")
                if s.explanation:
                    lines.append(f"    Rationale: {s.explanation}")

        if result.cautionary_failures:
            lines.append("  KNOWN DEAD-ENDS (DO NOT ATTEMPT):")
            for c in result.cautionary_failures:
                lines.append(f"  - Cautionary [{c.session_id}]: {c.solution_snippet}")
                if c.explanation:
                    lines.append(f"    Why it failed: {c.explanation}")

        return "\n".join(lines)
