"""
[POS] src/myrm_agent_harness/core/security/readonly_research_sandbox/__init__.py
[INPUT] .ephemeral_cow_overlay, .facade, .readonly_lease_manager, .types
[OUTPUT] Public API exports for readonly_research_sandbox subsystem

Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .ephemeral_cow_overlay import EphemeralCowOverlay
from .facade import (
    ReadOnlyResearchSandboxFacade,
    get_readonly_research_sandbox_facade,
)
from .readonly_lease_manager import ReadOnlyLeaseManager
from .types import (
    EphemeralCowFileRecord,
    LeaseStatusEnum,
    ReadOnlyLeaseRecord,
    ReadOnlyResearchMetrics,
    ReadOnlyShieldBadge,
    ResearchModeEnum,
    WorkspaceSnapshot,
)

__all__ = [
    "EphemeralCowFileRecord",
    "EphemeralCowOverlay",
    "LeaseStatusEnum",
    "ReadOnlyLeaseManager",
    "ReadOnlyLeaseRecord",
    "ReadOnlyResearchMetrics",
    "ReadOnlyResearchSandboxFacade",
    "ReadOnlyShieldBadge",
    "ResearchModeEnum",
    "WorkspaceSnapshot",
    "get_readonly_research_sandbox_facade",
]
