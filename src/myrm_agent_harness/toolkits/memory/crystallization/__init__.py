"""Public facade of the crystallization subsystem.

[INPUT]
- toolkits.memory.crystallization.governor::ProceduralCrystallizationGovernor (POS: Three-stage lifecycle
  governor for procedural judgment rules.)
- toolkits.memory.crystallization.types::CrystallizationLifecycleStage, CrystallizedRuleMetrics,
  ImportanceScoreResult, RuleFeedbackRecord, RuleLifecycleState (POS: Typed data contracts for the
  crystallization subsystem.)

[OUTPUT]
- Package facade re-exporting 6 public names: CrystallizationLifecycleStage, CrystallizedRuleMetrics,
  ImportanceScoreResult, ProceduralCrystallizationGovernor, RuleFeedbackRecord, RuleLifecycleState

[POS]
Public facade of the crystallization subsystem.
"""

from .governor import ProceduralCrystallizationGovernor
from .types import (
    CrystallizationLifecycleStage,
    CrystallizedRuleMetrics,
    ImportanceScoreResult,
    RuleFeedbackRecord,
    RuleLifecycleState,
)

__all__ = [
    "CrystallizationLifecycleStage",
    "CrystallizedRuleMetrics",
    "ImportanceScoreResult",
    "ProceduralCrystallizationGovernor",
    "RuleFeedbackRecord",
    "RuleLifecycleState",
]
