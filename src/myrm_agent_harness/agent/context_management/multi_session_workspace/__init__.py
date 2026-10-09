"""Multi-session parallel workspace and root discovery package.

[INPUT]
- workspace_types: all contracts and enumerations.
- project_root_sniffer: ProjectRootSniffer.
- parallel_workspace_deck: ParallelWorkspaceDeck.
- cross_session_reference_bus: CrossSessionReferenceBus.
- multi_session_workspace_suite: MultiSessionParallelWorkspaceAndRootDiscoverySuite.

[OUTPUT]
- Exposes all core contracts and master facade for multi-session workspaces.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.multi_session_workspace
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.multi_session_workspace.cross_session_reference_bus import (
    CrossSessionReferenceBus,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.multi_session_workspace_suite import (
    MultiSessionParallelWorkspaceAndRootDiscoverySuite,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.parallel_workspace_deck import (
    ParallelWorkspaceDeck,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.project_root_sniffer import (
    ProjectRootSniffer,
)
from myrm_agent_harness.agent.context_management.multi_session_workspace.workspace_types import (
    CrossSessionArtifactItem,
    CrossSessionReferenceBundle,
    DiscoveredRootResult,
    GridLayoutType,
    MultiSessionWorkspaceConfig,
    RootIndicatorKind,
    SlotRoleTag,
    WorkspaceDeckState,
    WorkspaceSlot,
)

__all__ = [
    "CrossSessionArtifactItem",
    "CrossSessionReferenceBundle",
    "CrossSessionReferenceBus",
    "DiscoveredRootResult",
    "GridLayoutType",
    "MultiSessionParallelWorkspaceAndRootDiscoverySuite",
    "MultiSessionWorkspaceConfig",
    "ParallelWorkspaceDeck",
    "ProjectRootSniffer",
    "RootIndicatorKind",
    "SlotRoleTag",
    "WorkspaceDeckState",
    "WorkspaceSlot",
]
