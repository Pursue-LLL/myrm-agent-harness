"""Future Action Impact Filtering Gate for Memory Extraction.

Quantifies candidate memory utility on downstream agent decisions and enforces
strict 3-tier admission routing (long-term persist, L2 session buffer, immediate discard)
to prevent database noise pollution and maintain high signal-to-noise ratio.
"""

from .evaluator import FutureActionImpactEvaluator
from .gate import ActionImpactFilteringGate
from .models import (
    ActionImpactAssessment,
    ActionImpactCategory,
    ActionImpactTier,
    BatchFilteringSummary,
)

__all__ = [
    "ActionImpactAssessment",
    "ActionImpactCategory",
    "ActionImpactFilteringGate",
    "ActionImpactTier",
    "BatchFilteringSummary",
    "FutureActionImpactEvaluator",
]
