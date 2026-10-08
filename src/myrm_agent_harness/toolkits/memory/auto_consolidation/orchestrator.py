"""Unified orchestrator for Idle & Budget Gated Auto-Memory Consolidation Suite.

[INPUT]
- collections.abc.Mapping, collections.abc.Sequence
- logging
- auto_consolidation.models::{AutoMemoryGatingConfig, OverallGatingReport, SixDimensionalMemoryArtifact}
- auto_consolidation.gating_engine::{estimate_consolidation_token_cost, evaluate_composite_gating}
- auto_consolidation.six_dimensional_extractor::SixDimensionalMemoryExtractor

[OUTPUT]
- AutoMemoryConsolidationOrchestrator: High-level coordination facade managing admission gates & distillation.

[POS]
Main entry facade for auto-consolidation operations in the harness layer (Item 123).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from myrm_agent_harness.toolkits.memory.auto_consolidation.gating_engine import (
    estimate_consolidation_token_cost,
    evaluate_composite_gating,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.models import (
    AutoMemoryGatingConfig,
    OverallGatingReport,
    SixDimensionalMemoryArtifact,
)
from myrm_agent_harness.toolkits.memory.auto_consolidation.six_dimensional_extractor import (
    SixDimensionalMemoryExtractor,
)

logger = logging.getLogger(__name__)


class AutoMemoryConsolidationOrchestrator:
    """Coordinates session inactivity tracking, admission gates, and structured distillation."""

    def __init__(
        self,
        config: AutoMemoryGatingConfig | None = None,
        extractor: SixDimensionalMemoryExtractor | None = None,
    ) -> None:
        self._config = config or AutoMemoryGatingConfig()
        self._extractor = extractor or SixDimensionalMemoryExtractor()

    @property
    def config(self) -> AutoMemoryGatingConfig:
        """Access current active configuration."""
        return self._config

    def update_config(self, new_config: AutoMemoryGatingConfig) -> AutoMemoryGatingConfig:
        """Update runtime gating configuration."""
        self._config = new_config
        logger.info("Updated AutoMemoryGatingConfig: enabled=%s", new_config.enabled)
        return self._config

    def evaluate_session_gating(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, str]],
        remaining_tokens: int,
        last_active_timestamp: float,
        current_timestamp: float | None = None,
        require_idle: bool = True,
    ) -> OverallGatingReport:
        """Audit session against idle detection and dual turn/budget gates without mutating state."""
        return evaluate_composite_gating(
            session_id=session_id,
            messages=messages,
            remaining_tokens=remaining_tokens,
            last_active_timestamp=last_active_timestamp,
            current_timestamp=current_timestamp,
            config=self._config,
            require_idle=require_idle,
        )

    def consolidate_session(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, str]],
        remaining_tokens: int,
        working_directory: str = "",
        tool_call_records: Sequence[str] | None = None,
        last_active_timestamp: float = 0.0,
        current_timestamp: float | None = None,
        force_bypass_gating: bool = False,
        require_idle: bool = True,
    ) -> tuple[OverallGatingReport, SixDimensionalMemoryArtifact | None]:
        """Execute gated auto-consolidation for a session.

        Returns:
            Tuple of (OverallGatingReport, SixDimensionalMemoryArtifact | None).
            The artifact is None if gating rejects the session and force_bypass_gating is False.
        """
        report = self.evaluate_session_gating(
            session_id=session_id,
            messages=messages,
            remaining_tokens=remaining_tokens,
            last_active_timestamp=last_active_timestamp,
            current_timestamp=current_timestamp,
            require_idle=require_idle,
        )

        if not report.should_consolidate and not force_bypass_gating:
            logger.info(
                "Auto-consolidation bypassed for session %s: %s",
                session_id,
                report.final_rationale,
            )
            return report, None

        token_cost = estimate_consolidation_token_cost(messages)
        artifact = self._extractor.extract(
            session_id=session_id,
            messages=messages,
            working_directory=working_directory,
            tool_call_records=tool_call_records,
            token_cost=token_cost,
        )

        logger.info(
            "Auto-consolidation successful for session %s: generated %s (cost %d tokens)",
            session_id,
            artifact.artifact_id,
            token_cost,
        )
        return report, artifact
