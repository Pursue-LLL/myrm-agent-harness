"""Public facade of the override stack subsystem.

[INPUT]
- toolkits.memory.override_stack.detector::PlaybookConflictDetector (POS: Detects acute semantic
  contradictions between user turn instructions and crystallized playbooks.)
- toolkits.memory.override_stack.gate::DynamicUserOverrideStack, EphemeralBypassGate (POS: Evaluates turn
  prompt against procedural playbooks and temporarily bypasses conflicting rules.)
- toolkits.memory.override_stack.types::EphemeralBypassRecord, PlaybookOverrideEvaluation, PriorityLevel
  (POS: Typed data contracts for the override stack subsystem.)

[OUTPUT]
- Package facade re-exporting 6 public names: DynamicUserOverrideStack, EphemeralBypassGate,
  EphemeralBypassRecord, PlaybookConflictDetector, PlaybookOverrideEvaluation, PriorityLevel

[POS]
Public facade of the override stack subsystem.
"""

from myrm_agent_harness.toolkits.memory.override_stack.detector import (
    PlaybookConflictDetector,
)
from myrm_agent_harness.toolkits.memory.override_stack.gate import (
    DynamicUserOverrideStack,
    EphemeralBypassGate,
)
from myrm_agent_harness.toolkits.memory.override_stack.types import (
    EphemeralBypassRecord,
    PlaybookOverrideEvaluation,
    PriorityLevel,
)

__all__ = [
    "DynamicUserOverrideStack",
    "EphemeralBypassGate",
    "EphemeralBypassRecord",
    "PlaybookConflictDetector",
    "PlaybookOverrideEvaluation",
    "PriorityLevel",
]
