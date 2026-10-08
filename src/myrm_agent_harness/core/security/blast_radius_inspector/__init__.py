"""Agent Action Surface Blast Radius Static Inspector and Guard Attribution Suite.

Provides zero-LLM 4D action surface mapping (Tools, Files, APIs, Sends × 8 Actions),
two-tier danger stratification (Reachable-verified vs Install-liability),
guard attribution matrix, least-privilege policy auto-repairer,
and a global action emergency kill switch.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.blast_radius_inspector.guard_attribution import (
    GuardAttributionEngine,
)
from myrm_agent_harness.core.security.blast_radius_inspector.kill_switch import (
    GlobalActionKillSwitch,
)
from myrm_agent_harness.core.security.blast_radius_inspector.static_inspector import (
    ActionSurfaceStaticInspector,
)
from myrm_agent_harness.core.security.blast_radius_inspector.types import (
    ActionSurfaceDimension,
    ActionSurfaceExposureReport,
    AtomicActionCategory,
    DangerTier,
    GuardAttributionItem,
    GuardStatus,
    KillSwitchState,
    RepairPolicyPatch,
    SinkVulnerabilityItem,
)

__all__ = [
    "ActionSurfaceDimension",
    "ActionSurfaceExposureReport",
    "ActionSurfaceStaticInspector",
    "AtomicActionCategory",
    "DangerTier",
    "GlobalActionKillSwitch",
    "GuardAttributionEngine",
    "GuardAttributionItem",
    "GuardStatus",
    "KillSwitchState",
    "RepairPolicyPatch",
    "SinkVulnerabilityItem",
]
