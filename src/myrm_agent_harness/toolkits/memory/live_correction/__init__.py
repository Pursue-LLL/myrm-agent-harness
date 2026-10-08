"""Natural language live memory correction and feedback package.

[INPUT]
- None (internal submodules)

[OUTPUT]
- Public types and classes for natural language memory feedback and live correction.

[POS]
myrm_agent_harness.toolkits.memory.live_correction
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.live_correction.detector import (
    NaturalLanguageCorrectionDetector,
)
from myrm_agent_harness.toolkits.memory.live_correction.localizer import (
    CorrectionTargetLocalizer,
)
from myrm_agent_harness.toolkits.memory.live_correction.models import (
    CorrectionAckReceipt,
    CorrectionIntentKind,
    CorrectionSlot,
    LiveCorrectionMutationResult,
    MutationAction,
    TargetNodeCandidate,
)
from myrm_agent_harness.toolkits.memory.live_correction.mutator import (
    AtomicMemoryMutator,
    MutationSinkProtocol,
)
from myrm_agent_harness.toolkits.memory.live_correction.orchestrator import (
    LiveCorrectionOrchestrator,
)

__all__ = [
    "AtomicMemoryMutator",
    "CorrectionAckReceipt",
    "CorrectionIntentKind",
    "CorrectionSlot",
    "CorrectionTargetLocalizer",
    "LiveCorrectionMutationResult",
    "LiveCorrectionOrchestrator",
    "MutationAction",
    "MutationSinkProtocol",
    "NaturalLanguageCorrectionDetector",
    "TargetNodeCandidate",
]
