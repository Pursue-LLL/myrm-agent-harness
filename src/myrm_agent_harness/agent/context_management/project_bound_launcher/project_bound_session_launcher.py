"""Core launcher engine for project-bound chat sessions.

[INPUT]
- launcher_types: ProjectMetadataSnapshot, SessionLaunchRequest,
  BoundSessionLaunchResult, SessionLaunchMode, LauncherSuiteConfig.
- workspace_metadata_inspector: WorkspaceMetadataInspector.
- context_inheritance_assembler: ContextInheritanceAssembler.

[OUTPUT]
- ProjectBoundSessionLauncher: Resolves project bindings, coordinates workspace
  inheritance, handles parent branch derivation, and produces ready-to-run sessions.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: project_bound_session_launcher.py
"""

from typing import Dict, Optional, Sequence
from myrm_agent_harness.agent.context_management.project_bound_launcher.context_inheritance_assembler import (
    ContextInheritanceAssembler,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.launcher_types import (
    BoundSessionLaunchResult,
    InheritedContextFrame,
    LauncherSuiteConfig,
    ProjectMetadataSnapshot,
    SessionLaunchMode,
    SessionLaunchRequest,
)
from myrm_agent_harness.agent.context_management.project_bound_launcher.workspace_metadata_inspector import (
    WorkspaceMetadataInspector,
)


class ProjectBoundSessionLauncher:
    """Orchestrates creation of chat sessions bound to project and workspace contexts."""

    def __init__(self, config: Optional[LauncherSuiteConfig] = None) -> None:
        self._config = config or LauncherSuiteConfig()
        self._inspector = WorkspaceMetadataInspector()
        self._assembler = ContextInheritanceAssembler()
        self._project_registry: Dict[str, ProjectMetadataSnapshot] = {}
        # Records of launched sessions: session_id -> BoundSessionLaunchResult
        self._launched_sessions: Dict[str, BoundSessionLaunchResult] = {}

    def register_project(self, snapshot: ProjectMetadataSnapshot) -> None:
        """Registers or updates a project metadata snapshot in the launcher registry."""
        self._project_registry[snapshot.project_id] = snapshot

    def get_project(self, project_id: str) -> Optional[ProjectMetadataSnapshot]:
        """Retrieves a registered project snapshot by its identifier."""
        return self._project_registry.get(project_id)

    def list_projects(self) -> Sequence[ProjectMetadataSnapshot]:
        """Returns all registered projects."""
        return tuple(self._project_registry.values())

    def launch_session(self, request: SessionLaunchRequest) -> BoundSessionLaunchResult:
        """Processes a launch request and synthesizes the bound session context.

        Args:
            request: The session launch specification.

        Returns:
            BoundSessionLaunchResult with initialized workspace and context frame.
        """
        # Determine launch mode
        if request.parent_session_id is not None:
            launch_mode = SessionLaunchMode.BRANCHED_FROM_PARENT
        elif request.project_id is not None:
            launch_mode = SessionLaunchMode.PROJECT_BOUND
        else:
            launch_mode = SessionLaunchMode.STANDALONE_QUICK_CHAT

        # 1. Resolve project snapshot if applicable
        target_project: Optional[ProjectMetadataSnapshot] = None
        if launch_mode == SessionLaunchMode.BRANCHED_FROM_PARENT:
            parent_result = self._launched_sessions.get(request.parent_session_id)
            if parent_result and parent_result.inherited_frame.project_id:
                target_project = self._project_registry.get(
                    parent_result.inherited_frame.project_id
                )
        elif request.project_id:
            target_project = self._project_registry.get(request.project_id)
            if target_project is None and not self._config.allow_empty_project:
                return BoundSessionLaunchResult(
                    session_id=request.target_session_id,
                    launch_mode=launch_mode,
                    inherited_frame=InheritedContextFrame(
                        project_id=request.project_id,
                        workspace_path=self._config.fallback_workspace_path,
                        agent_id=self._config.fallback_default_agent_id,
                        context_prompt_block="",
                    ),
                    success=False,
                    message=f"Project '{request.project_id}' not found and allow_empty_project is False.",
                )

        # 2. Resolve working directory (custom_cwd overrides project workspace_path)
        if request.custom_cwd:
            raw_cwd = request.custom_cwd
        elif target_project and target_project.workspace_path:
            raw_cwd = target_project.workspace_path
        elif (
            launch_mode == SessionLaunchMode.BRANCHED_FROM_PARENT
            and request.parent_session_id in self._launched_sessions
        ):
            raw_cwd = self._launched_sessions[
                request.parent_session_id
            ].inherited_frame.workspace_path
        else:
            raw_cwd = self._config.fallback_workspace_path

        is_valid, resolved_cwd = self._inspector.validate_workspace_path(raw_cwd)
        if not is_valid:
            resolved_cwd = self._config.fallback_workspace_path

        # 3. Resolve executing agent ID
        if request.custom_agent_id:
            agent_id = request.custom_agent_id
        elif target_project and target_project.default_agent_id:
            agent_id = target_project.default_agent_id
        else:
            agent_id = self._config.fallback_default_agent_id

        # 4. Resolve git metadata
        if request.inherited_git_branch:
            git_branch = request.inherited_git_branch
            _, git_repo_root = self._inspector.inspect_git_metadata(resolved_cwd)
        elif target_project and target_project.git_branch:
            git_branch = target_project.git_branch
            git_repo_root = target_project.git_repo_root or resolved_cwd
        else:
            git_branch, git_repo_root = self._inspector.inspect_git_metadata(resolved_cwd)

        # 5. Assemble first-turn context prompt block
        frame = self._assembler.assemble(
            project=target_project,
            effective_cwd=resolved_cwd,
            effective_agent_id=agent_id,
            git_branch=git_branch,
            git_repo_root=git_repo_root,
            max_chars=self._config.max_context_summary_chars,
        )

        outcome = BoundSessionLaunchResult(
            session_id=request.target_session_id,
            launch_mode=launch_mode,
            inherited_frame=frame,
            success=True,
            message="Session launched successfully with inherited workspace context.",
        )
        self._launched_sessions[request.target_session_id] = outcome
        return outcome

    def get_launched_session(
        self, session_id: str
    ) -> Optional[BoundSessionLaunchResult]:
        """Retrieves outcome record for a previously launched session."""
        return self._launched_sessions.get(session_id)
