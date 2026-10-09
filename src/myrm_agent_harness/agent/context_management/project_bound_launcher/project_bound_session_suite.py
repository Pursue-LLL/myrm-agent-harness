"""Unified master suite for project-bound session launching and context inheritance.

[INPUT]
- launcher_types: All contracts, snapshot specifications, and configurations.
- project_bound_session_launcher: ProjectBoundSessionLauncher.
- workspace_metadata_inspector: WorkspaceMetadataInspector.
- context_inheritance_assembler: ContextInheritanceAssembler.

[OUTPUT]
- ProjectBoundSessionLauncherSuite: High-level facade orchestrating project binding,
  branch context inheritance, quick-chat fallback, and initial prompt priming.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: project_bound_session_suite.py
"""

from typing import Optional, Sequence
from myrm_agent_harness.agent.context_management.project_bound_launcher.launcher_types import (
    BoundSessionLaunchResult,
    InheritedContextFrame,
    LauncherSuiteConfig,
    ProjectMetadataSnapshot,
    SessionLaunchRequest,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.project_bound_session_launcher import (
    ProjectBoundSessionLauncher,
)


class ProjectBoundSessionLauncherSuite:
    """Master facade for launching chat sessions with automatic workspace & project inheritance."""

    def __init__(self, config: Optional[LauncherSuiteConfig] = None) -> None:
        self._config = config or LauncherSuiteConfig()
        self._launcher = ProjectBoundSessionLauncher(self._config)

    @property
    def launcher(self) -> ProjectBoundSessionLauncher:
        """Returns the underlying session launcher engine."""
        return self._launcher

    def register_project(self, snapshot: ProjectMetadataSnapshot) -> None:
        """Registers a project metadata snapshot into the suite."""
        self._launcher.register_project(snapshot)

    def get_project(self, project_id: str) -> Optional[ProjectMetadataSnapshot]:
        """Retrieves a registered project by its identifier."""
        return self._launcher.get_project(project_id)

    def list_projects(self) -> Sequence[ProjectMetadataSnapshot]:
        """Lists all registered projects."""
        return self._launcher.list_projects()

    def launch_project_session(
        self,
        session_id: str,
        project_id: str,
        custom_cwd: Optional[str] = None,
        custom_agent_id: Optional[str] = None,
        initial_prompt: str = "",
    ) -> BoundSessionLaunchResult:
        """Launches a new conversation bound to a specific project.

        Args:
            session_id: Unique identifier for the new session.
            project_id: Target project identifier.
            custom_cwd: Optional custom working directory override.
            custom_agent_id: Optional custom agent profile override.
            initial_prompt: Initial user instruction if available.

        Returns:
            BoundSessionLaunchResult containing the primed context frame.
        """
        request = SessionLaunchRequest(
            target_session_id=session_id,
            project_id=project_id,
            custom_cwd=custom_cwd,
            custom_agent_id=custom_agent_id,
            initial_user_prompt=initial_prompt,
        )
        return self._launcher.launch_session(request)

    def launch_branch_session(
        self,
        session_id: str,
        parent_session_id: str,
        inherited_git_branch: Optional[str] = None,
        custom_cwd: Optional[str] = None,
        custom_agent_id: Optional[str] = None,
        initial_prompt: str = "",
    ) -> BoundSessionLaunchResult:
        """Branches a new session from an existing parent, inheriting its project and workspace context.

        Args:
            session_id: Unique identifier for the branched session.
            parent_session_id: Parent session identifier to inherit from.
            inherited_git_branch: Optional git branch name for the branch.
            custom_cwd: Optional working directory override.
            custom_agent_id: Optional agent profile override.
            initial_prompt: Initial user instruction if available.

        Returns:
            BoundSessionLaunchResult with inherited parent context.
        """
        request = SessionLaunchRequest(
            target_session_id=session_id,
            parent_session_id=parent_session_id,
            inherited_git_branch=inherited_git_branch,
            custom_cwd=custom_cwd,
            custom_agent_id=custom_agent_id,
            initial_user_prompt=initial_prompt,
        )
        return self._launcher.launch_session(request)

    def launch_quick_chat(
        self,
        session_id: str,
        custom_cwd: Optional[str] = None,
        custom_agent_id: Optional[str] = None,
        initial_prompt: str = "",
    ) -> BoundSessionLaunchResult:
        """Launches a standalone quick chat without project binding.

        Args:
            session_id: Unique identifier for the session.
            custom_cwd: Optional working directory.
            custom_agent_id: Optional agent profile.
            initial_prompt: Initial user prompt.

        Returns:
            BoundSessionLaunchResult for the standalone chat.
        """
        request = SessionLaunchRequest(
            target_session_id=session_id,
            project_id=None,
            custom_cwd=custom_cwd,
            custom_agent_id=custom_agent_id,
            initial_user_prompt=initial_prompt,
        )
        return self._launcher.launch_session(request)

    def get_session_frame(self, session_id: str) -> Optional[InheritedContextFrame]:
        """Retrieves the context frame initialized for a given session."""
        result = self._launcher.get_launched_session(session_id)
        return result.inherited_frame if result else None
