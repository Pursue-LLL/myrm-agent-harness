"""Types and data contracts for project-bound session launching and context inheritance.

[INPUT]
- None (pure type definitions and immutable data contracts).

[OUTPUT]
- Exports enumerations and dataclasses for project metadata snapshots,
  launch requests, inherited context frames, and launch outcomes.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: launcher_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Sequence


class SessionLaunchMode(str, Enum):
    """Operational mode when launching a chat session."""

    STANDALONE_QUICK_CHAT = "standalone_quick_chat"
    PROJECT_BOUND = "project_bound"
    BRANCHED_FROM_PARENT = "branched_from_parent"


class InheritanceStatus(str, Enum):
    """Status indicating how workspace and project metadata were inherited."""

    INHERITED_FULL = "inherited_full"
    INHERITED_PARTIAL = "inherited_partial"
    NONE = "none"


@dataclass(frozen=True)
class ProjectMetadataSnapshot:
    """Immutable snapshot of project metadata used to seed new session context."""

    project_id: str
    name: str
    workspace_path: str
    default_agent_id: str = "general_agent"
    goal_summary: str = ""
    description: str = ""
    git_branch: str = ""
    git_repo_root: str = ""
    tags: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class SessionLaunchRequest:
    """Request payload to instantiate a new session with workspace binding."""

    target_session_id: str
    project_id: Optional[str] = None
    custom_cwd: Optional[str] = None
    custom_agent_id: Optional[str] = None
    initial_user_prompt: str = ""
    parent_session_id: Optional[str] = None
    inherited_git_branch: Optional[str] = None


@dataclass(frozen=True)
class InheritedContextFrame:
    """Context frame to inject into the session's first turn prompt and environment."""

    project_id: Optional[str]
    workspace_path: str
    agent_id: str
    context_prompt_block: str
    git_branch: str = ""
    git_repo_root: str = ""
    inheritance_status: InheritanceStatus = InheritanceStatus.NONE


@dataclass(frozen=True)
class BoundSessionLaunchResult:
    """Outcome returned after processing a project-bound session launch request."""

    session_id: str
    launch_mode: SessionLaunchMode
    inherited_frame: InheritedContextFrame
    success: bool = True
    message: str = ""


@dataclass(frozen=True)
class LauncherSuiteConfig:
    """Configuration options for the project-bound session launcher."""

    allow_empty_project: bool = True
    require_existing_workspace_path: bool = False
    max_context_summary_chars: int = 1200
    fallback_default_agent_id: str = "general_agent"
    fallback_workspace_path: str = "/tmp/sandbox/workspace"
