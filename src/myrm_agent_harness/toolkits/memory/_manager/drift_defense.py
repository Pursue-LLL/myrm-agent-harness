"""MemoryManager mixin for ground truth priority and memory drift stale defense.

[INPUT]
- toolkits.memory.drift_defense.detector::GroundTruthDriftDetector (POS: drift detector)
- toolkits.memory.drift_defense.decorator::StaleMemoryDecorator (POS: stale decorator)
- toolkits.memory.drift_defense.types::DriftCheckRequest, DriftCheckResult (POS: contracts)

[OUTPUT]
- MemoryManagerDriftDefenseMixin: runtime orchestration methods for ground truth drift verification

[POS]
Partial mixin for MemoryManager providing pre-injection ground truth validation, sub-5ms physical presence checks, and stale memory decoration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.drift_defense.decorator import (
        StaleMemoryDecorator,
    )
    from myrm_agent_harness.toolkits.memory.drift_defense.detector import (
        GroundTruthDriftDetector,
    )
    from myrm_agent_harness.toolkits.memory.drift_defense.types import (
        DriftCheckRequest,
        DriftCheckResult,
    )


class MemoryManagerDriftDefenseMixin:
    """Provides methods for validating memories against physical repository state and decorating stale items."""

    def check_memory_ground_truth_drift(
        self,
        request: DriftCheckRequest,
        *,
        detector: GroundTruthDriftDetector | None = None,
    ) -> DriftCheckResult:
        """Inspect candidate memory against physical filesystem and symbols to prevent stale hallucinations."""
        from myrm_agent_harness.toolkits.memory.drift_defense.detector import (
            GroundTruthDriftDetector,
        )

        active_detector = detector or GroundTruthDriftDetector()
        return active_detector.check(request)

    def batch_check_memory_drift(
        self,
        requests: list[DriftCheckRequest],
        *,
        detector: GroundTruthDriftDetector | None = None,
    ) -> list[DriftCheckResult]:
        """Batch evaluate candidate memories before prompt injection or task retrieval."""
        from myrm_agent_harness.toolkits.memory.drift_defense.detector import (
            GroundTruthDriftDetector,
        )

        active_detector = detector or GroundTruthDriftDetector()
        return [active_detector.check(req) for req in requests]

    def decorate_stale_memories(
        self,
        contents: list[str],
        results: list[DriftCheckResult],
        *,
        decorator: StaleMemoryDecorator | None = None,
    ) -> list[str]:
        """Apply stale warning prefixes and confidence adjustments to drifted memories."""
        from myrm_agent_harness.toolkits.memory.drift_defense.decorator import (
            StaleMemoryDecorator,
        )

        active_decorator = decorator or StaleMemoryDecorator()
        return [
            active_decorator.decorate(content, res.is_drifted)
            for content, res in zip(contents, results, strict=False)
        ]
