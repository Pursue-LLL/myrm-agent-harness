"""Screen observation memory anti-injection boundary and descriptive-only fact validation toolkit.

[POS]
Harness framework layer toolkit providing ChatGPT Desktop Skysight-style
evidence boundaries, descriptive-only grammar enforcement, and anti-overpromotion gate (Topic 01 Item 85).
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.screen_observation.boundary import (
    UntrustedObservationEvidenceBoundary,
)
from myrm_agent_harness.toolkits.memory.screen_observation.gate import (
    AntiOverpromotionGate,
)
from myrm_agent_harness.toolkits.memory.screen_observation.manager import (
    ScreenObservationMemoryManager,
    ScreenObservationSafetyResult,
)
from myrm_agent_harness.toolkits.memory.screen_observation.types import (
    DescriptiveFactCandidate,
    ObservationPayload,
    ObservationSourceType,
    OverpromotionGateResult,
    PromotionStatus,
    SanitizedObservationEvidence,
    ScreenSafetyAuditRecord,
)
from myrm_agent_harness.toolkits.memory.screen_observation.validator import (
    DescriptiveFactValidator,
)

__all__ = [
    "ObservationSourceType",
    "PromotionStatus",
    "ObservationPayload",
    "SanitizedObservationEvidence",
    "DescriptiveFactCandidate",
    "OverpromotionGateResult",
    "ScreenSafetyAuditRecord",
    "UntrustedObservationEvidenceBoundary",
    "DescriptiveFactValidator",
    "AntiOverpromotionGate",
    "ScreenObservationSafetyResult",
    "ScreenObservationMemoryManager",
]
