"""Future Action Impact Filtering Gate for Memory Extraction.

Quantifies candidate memory utility on downstream agent decisions and enforces
strict 3-tier admission routing (long-term persist, L2 session buffer, immediate discard)
to prevent database noise pollution and maintain high signal-to-noise ratio.

[INPUT]
- toolkits.memory.action_impact.evaluator::FutureActionImpactEvaluator (POS: Future Action Impact Evaluator
  quantifying memory utility for downstream decisions.)
- toolkits.memory.action_impact.gate::ActionImpactFilteringGate (POS: Action Impact Filtering Gate executing
  3-tier admission routing.)
- toolkits.memory.action_impact.models::ActionImpactAssessment, ActionImpactCategory, ActionImpactTier,
  BatchFilteringSummary (POS: Data models for Future Action Impact Filtering Gate.)

[OUTPUT]
- Package facade re-exporting 6 public names: ActionImpactAssessment, ActionImpactCategory,
  ActionImpactFilteringGate, ActionImpactTier, BatchFilteringSummary, FutureActionImpactEvaluator

[POS]
Future Action Impact Filtering Gate for Memory Extraction.
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
