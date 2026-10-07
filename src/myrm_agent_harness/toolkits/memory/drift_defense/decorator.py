"""Prompt decorator and confidence decay applier for stale memories.

Applies warning banners and confidence adjustments to ensure LLMs treat drifted
memories as weak historical references rather than absolute ground truth.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.drift_defense.types::DriftCheckResult, DriftDefenseConfig (POS: Type definitions for
  ground truth priority and memory drift stale defense.)

[OUTPUT]
- StaleMemoryDecorator: Decorates drifted memories with prompt warnings and computes decayed confidence.

[POS]
Prompt decorator and confidence decay applier for stale memories.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.drift_defense.types import (
    DriftCheckResult,
    DriftDefenseConfig,
)


class StaleMemoryDecorator:
    """Decorates drifted memories with prompt warnings and computes decayed confidence."""

    def __init__(self, config: DriftDefenseConfig | None = None) -> None:
        self.config = config or DriftDefenseConfig()

    def decorate(self, content: str, is_drifted: bool) -> str:
        """Apply warning decoration if memory has drifted from ground truth."""
        if not is_drifted or not self.config.enabled:
            return content
        return self.config.stale_warning_template.format(content=content)

    def compute_effective_confidence(
        self,
        base_confidence: float,
        drift_result: DriftCheckResult,
    ) -> float:
        """Calculate penalised confidence score if drift is confirmed."""
        if not drift_result.is_drifted:
            return base_confidence
        # Apply additive penalty floor at 0.0
        penalized = base_confidence - drift_result.confidence_penalty
        return max(0.0, min(1.0, penalized))
