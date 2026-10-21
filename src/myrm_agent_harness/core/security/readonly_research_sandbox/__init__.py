"""Read-only research lease package: while a session's lease is active only the lease's tools may run.

[INPUT]
- .facade::ReadOnlyResearchSandboxFacade, get_readonly_research_sandbox_facade (POS: Process-wide entry to read-only research leases.)
- .readonly_lease_manager::ReadOnlyLeaseManager (POS: Lease lifecycle and default-deny tool check.)
- .types::DEFAULT_READ_ONLY_TOOLS, LeaseStatusEnum, ReadOnlyLeaseRecord, ReadOnlyResearchMetrics, ResearchModeEnum (POS: Lease data shapes and the default read-only tool set.)

[OUTPUT]
- ReadOnlyResearchSandboxFacade, get_readonly_research_sandbox_facade, ReadOnlyLeaseManager, ReadOnlyLeaseRecord, ReadOnlyResearchMetrics, LeaseStatusEnum, ResearchModeEnum, DEFAULT_READ_ONLY_TOOLS: the package's public API

[POS]
Entry of the read-only research lease package.
"""

from __future__ import annotations

from .facade import (
    ReadOnlyResearchSandboxFacade,
    get_readonly_research_sandbox_facade,
)
from .readonly_lease_manager import ReadOnlyLeaseManager
from .types import (
    DEFAULT_READ_ONLY_TOOLS,
    LeaseStatusEnum,
    ReadOnlyLeaseRecord,
    ReadOnlyResearchMetrics,
    ResearchModeEnum,
)

__all__ = [
    "DEFAULT_READ_ONLY_TOOLS",
    "LeaseStatusEnum",
    "ReadOnlyLeaseManager",
    "ReadOnlyLeaseRecord",
    "ReadOnlyResearchMetrics",
    "ReadOnlyResearchSandboxFacade",
    "ResearchModeEnum",
    "get_readonly_research_sandbox_facade",
]
