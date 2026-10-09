"""Project-bound session launcher and context inheritance package.

[INPUT]
- launcher_types: contracts and data models.
- workspace_metadata_inspector: WorkspaceMetadataInspector.
- context_inheritance_assembler: ContextInheritanceAssembler.
- project_bound_session_launcher: ProjectBoundSessionLauncher.
- project_bound_session_suite: ProjectBoundSessionLauncherSuite.

[OUTPUT]
- Exposes all core contracts and master facade for project-bound launching.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: __init__.py
"""

from myrm_agent_harness.agent.context_management.project_bound_launcher.context_inheritance_assembler import (
    ContextInheritanceAssembler,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.launcher_types import (
    BoundSessionLaunchResult,
    InheritedContextFrame,
    InheritanceStatus,
    LauncherSuiteConfig,
    ProjectMetadataSnapshot,
    SessionLaunchMode,
    SessionLaunchRequest,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.project_bound_session_launcher import (
    ProjectBoundSessionLauncher,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.project_bound_session_suite import (
    ProjectBoundSessionLauncherSuite,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.workspace_metadata_inspector import (
    WorkspaceMetadataInspector,
)

__all__ = [
    "BoundSessionLaunchResult",
    "ContextInheritanceAssembler",
    "InheritedContextFrame",
    "InheritanceStatus",
    "LauncherSuiteConfig",
    "ProjectBoundSessionLauncher",
    "ProjectBoundSessionLauncherSuite",
    "ProjectMetadataSnapshot",
    "SessionLaunchMode",
    "SessionLaunchRequest",
    "WorkspaceMetadataInspector",
]
