"""Default quality gate implementation.

Threshold-based skill quality gate — framework-provided, zero-LLM-cost.
Business layer can override with LLM-based multi-dimension verification.

[INPUT]
- .protocols::SkillQualityGateProtocol
- .types::GateVerdict

[OUTPUT]
- ThresholdQualityGate: Default threshold-based quality gate

[POS]
Default quality gate for skill push validation.
"""

from __future__ import annotations

import logging

from .types import GateVerdict

logger = logging.getLogger(__name__)

_MIN_EXECUTIONS = 3
_MIN_EFFECTIVE_RATE = 0.7


class ThresholdQualityGate:
    """Default threshold-based quality gate.

    Rejects skills that:
    1. Have too few executions (< min_executions) — insufficient evidence
    2. Have low effective rate (< min_effective_rate) — unreliable
    3. Have empty content — broken skill
    """

    def __init__(
        self,
        min_executions: int = _MIN_EXECUTIONS,
        min_effective_rate: float = _MIN_EFFECTIVE_RATE,
    ) -> None:
        self._min_executions = min_executions
        self._min_effective_rate = min_effective_rate

    async def evaluate(
        self,
        skill_name: str,
        skill_content: str,
        effective_rate: float,
        total_executions: int,
    ) -> GateVerdict:
        reasons: list[str] = []

        if not skill_content.strip():
            return GateVerdict(passed=False, score=0.0, reasons=["Empty skill content"])

        if total_executions < self._min_executions:
            reasons.append(f"Insufficient executions ({total_executions} < {self._min_executions})")

        if effective_rate < self._min_effective_rate:
            reasons.append(f"Low effective rate ({effective_rate:.2f} < {self._min_effective_rate:.2f})")

        passed = len(reasons) == 0
        score = effective_rate if passed else max(0.0, effective_rate * 0.5)

        if not passed:
            logger.info("Quality gate rejected '%s': %s", skill_name, "; ".join(reasons))

        return GateVerdict(passed=passed, score=score, reasons=reasons)
