"""Skill Workspace Manager

Manages skill file copying, caching, and validation within workspaces.

[INPUT]
- toolkits.code_execution::Workspace (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- toolkits.code_execution.workspace::WorkspaceService (POS: Workspace data models for code execution sessions.)

[OUTPUT]
- SkillWorkspaceManager: Skill workspace manager.

[POS]
Skill Workspace Manager
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution import Workspace
    from myrm_agent_harness.toolkits.code_execution.workspace import WorkspaceService

logger = logging.getLogger(__name__)


class SkillWorkspaceManager:
    """Skill workspace manager.

    Responsibilities:
    - Copy skills from storage to workspace on demand
    - Cache copied skill paths
    - Validate skill file integrity
    """

    def __init__(self, workspace_service: "WorkspaceService | None" = None) -> None:
        self._workspace_service = workspace_service
        self._skills_cache: dict[str, dict[str, str]] = {}

    def _get_service(self) -> "WorkspaceService":
        if self._workspace_service is None:
            from myrm_agent_harness.toolkits.code_execution import create_workspace_service
            from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
                workspace_storage_fs_root_strict,
            )

            self._workspace_service = create_workspace_service(
                root_dir=workspace_storage_fs_root_strict(),
            )
        return self._workspace_service

    async def ensure_skills_in_workspace(self, workspace: "Workspace", skill_storage_paths: list[str]) -> list[str]:
        """Ensure skill files exist in the workspace, copying on demand.

        Args:
            workspace: Current workspace.
            skill_storage_paths: Absolute paths to skills in storage.

        Returns:
            List of skill paths within the workspace.
        """
        if not skill_storage_paths:
            return []

        workspace_svc = self._get_service()
        workspace_abs_path = Path(workspace_svc.get_workspace_absolute_path(workspace))

        if workspace.id not in self._skills_cache:
            self._skills_cache[workspace.id] = {}

        workspace_skill_paths: list[str] = []
        failed_skills: list[str] = []

        for skill_storage_path in skill_storage_paths:
            if not skill_storage_path or not isinstance(skill_storage_path, str):
                logger.warning("Skipping invalid skill path: %s", skill_storage_path)
                continue

            skill_name = Path(skill_storage_path).name

            workspace_skill_path = await self._get_skill_path(
                workspace=workspace, workspace_abs_path=workspace_abs_path, skill_name=skill_name
            )

            if workspace_skill_path:
                workspace_skill_paths.append(workspace_skill_path)
                continue

            copied_path = await self._copy_skill_to_workspace(
                workspace=workspace,
                workspace_abs_path=workspace_abs_path,
                skill_storage_path=skill_storage_path,
                skill_name=skill_name,
            )

            if copied_path:
                workspace_skill_paths.append(copied_path)
            else:
                failed_skills.append(skill_name)

        if failed_skills:
            logger.warning("Failed to copy skills: %s", ", ".join(failed_skills))

        return workspace_skill_paths

    async def _get_skill_path(self, workspace: "Workspace", workspace_abs_path: Path, skill_name: str) -> str | None:
        """Get skill path from cache or filesystem."""
        if skill_name in self._skills_cache[workspace.id]:
            cached_path = self._skills_cache[workspace.id][skill_name]
            if Path(cached_path).exists():
                logger.info("Skill path from cache: %s", skill_name)
                return cached_path

            logger.warning("Cache invalidated, skill dir missing: %s", cached_path)
            del self._skills_cache[workspace.id][skill_name]

        workspace_skill_dir = workspace_abs_path / ".claude" / "skills" / skill_name
        if workspace_skill_dir.exists():
            workspace_skill_path = str(workspace_skill_dir)
            self._skills_cache[workspace.id][skill_name] = workspace_skill_path
            logger.info("Skill already in workspace: %s", skill_name)
            return workspace_skill_path

        return None

    async def _copy_skill_to_workspace(
        self, workspace: "Workspace", workspace_abs_path: Path, skill_storage_path: str, skill_name: str
    ) -> str | None:
        """Copy a skill to the workspace."""
        logger.info("Copying skill to workspace: %s", skill_name)

        try:
            skill_storage_dir = Path(skill_storage_path)
            if not skill_storage_dir.exists():
                logger.warning("Skill storage path not found: %s", skill_storage_path)
                return None

            workspace_svc = self._get_service()
            storage = workspace_svc.get_storage(workspace)
            copied_count = 0

            for file_path in skill_storage_dir.rglob("*"):
                if file_path.is_dir():
                    continue

                relative_path = file_path.relative_to(skill_storage_dir)

                if any(part.startswith(".") or part == "__pycache__" for part in relative_path.parts):
                    continue

                target_path = f".claude/skills/{skill_name}/{relative_path}"
                content = file_path.read_bytes()
                await storage.write(target_path, content)
                copied_count += 1

            if copied_count > 0:
                logger.info("Copied %d files to workspace: %s", copied_count, skill_name)
                workspace_skill_dir = workspace_abs_path / ".claude" / "skills" / skill_name
                workspace_skill_path = str(workspace_skill_dir)
                self._skills_cache[workspace.id][skill_name] = workspace_skill_path
                return workspace_skill_path

            logger.warning("Skill directory empty or no valid files: %s", skill_name)
            return None

        except Exception as e:
            logger.warning("Failed to copy skill %s: %s", skill_name, e)
            return None

    def clear_workspace_cache(self, workspace_id: str) -> None:
        """Clear skill cache for a workspace."""
        if workspace_id in self._skills_cache:
            del self._skills_cache[workspace_id]
            logger.info("Cleared skill cache for workspace: %s", workspace_id)
