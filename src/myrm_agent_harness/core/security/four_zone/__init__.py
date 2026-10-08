"""Four-Zone Workspace Layout and Read-Only Source Protection module.

[INPUT]
None.

[OUTPUT]
Exported public classes, functions, and exceptions.

[POS]
Harness core security subsystem providing 4-zone physical layout scaffolding,
absolute read-only protection of customer raw materials, and one-way deliverable promotion.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.four_zone.guard import (
    FourZoneProtectionGuard,
)
from myrm_agent_harness.core.security.four_zone.pipeline import (
    OneWayPromotionPipeline,
)
from myrm_agent_harness.core.security.four_zone.scaffold import (
    FourZoneScaffold,
)
from myrm_agent_harness.core.security.four_zone.types import (
    ReadOnlySourceZoneViolationError,
    WorkspaceZone,
    ZoneOperationType,
    ZonePromotionRecord,
    ZoneValidationResult,
)

__all__ = [
    "FourZoneProtectionGuard",
    "FourZoneScaffold",
    "OneWayPromotionPipeline",
    "ReadOnlySourceZoneViolationError",
    "WorkspaceZone",
    "ZoneOperationType",
    "ZonePromotionRecord",
    "ZoneValidationResult",
]
