"""Workspace service for code execution sessions.

Manages workspace lifecycle: create, find, update, delete.
The service is stateless — callers manage the instance lifecycle.

Workspace path layout::

    {root_dir}/
    └── workspaces/
        └── {session_id}/
            ├── .claude/skills/
            ├── sessions/
            └── _metadata.json

[INPUT]
- toolkits.storage.base::StorageProvider (POS: Storage provider abstract base class. Defines the unified storage interface contract for all storage backends. Supports file read/write, delete, list, info query, and namespace isolation. Method names use read/write (not get/put), fully compatible with the StorageBackend Protocol.)
- toolkits.storage.local::LocalStorageBackend (POS: Local file system storage backend. Stores files on local filesystem, suitable for development and single-machine deployments. Inherits BaseFileSystemBackend; common I/O operations and errno error handling provided by base class. This class only handles path resolution (_resolve_key_to_path) and local-specific logic (chmod, list). Naming convention: Provider: protocol/interface defining the contract (e.g. StorageProvider) Backend: concrete implementation, directly usable (e.g. LocalStorageBackend))

[OUTPUT]
- WorkspaceService: Workspace service for code execution sessions.
- create_workspace_service: Factory requiring keyword ``root_dir`` (host aggregate directory containing ``workspaces/``).

[POS]
Workspace service for code execution sessions.
"""

import json
import logging
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.workspace.models import (
    Workspace,
    WorkspaceStatus,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Workspace service for code execution sessions.

    Provides session-based workspace management without multi-tenant logic.
    The caller is responsible for composing session_id from business concepts
    (e.g. ``f"{user_id}_{chat_id}"``).

    Usage::

        svc = WorkspaceService(root_dir=Path("/data/storage"))
        workspace = await svc.get_or_create(session_id="session_abc123")
        storage = svc.get_storage(workspace)
    """

    def __init__(self, root_dir: Path, storage_backend: "StorageProvider | None" = None) -> None:
        """Initialize workspace service.

        Args:
            root_dir: Root directory for workspace storage.
            storage_backend: Optional injected storage backend (e.g. S3 for Sandbox mode).
                When None, a local filesystem backend is used.
        """
        self._root = root_dir
        self._storage_backend = storage_backend

    @property
    def workspaces_root(self) -> Path:
        """Root directory containing all workspaces (for batch operations like cleanup)."""
        return self._root / "workspaces"

    def _get_workspace_dir(self, workspace: Workspace) -> Path:
        return self._root / workspace.path

    def _get_metadata_path(self, workspace: Workspace) -> Path:
        return self._get_workspace_dir(workspace) / "_metadata.json"

    def get_storage(self, workspace: Workspace) -> "StorageProvider":
        """Get a StorageProvider instance rooted at the workspace directory.

        Args:
            workspace: Target workspace.

        Returns:
            StorageProvider instance for file operations within the workspace.
        """
        from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend

        if self._storage_backend:
            return self._storage_backend

        workspace_abs_path = str(self._get_workspace_dir(workspace))
        return LocalStorageBackend(base_path=workspace_abs_path)

    async def create(self, session_id: str) -> Workspace:
        """Create a new workspace for the given session.

        Args:
            session_id: Unique session identifier (framework concept).

        Returns:
            Newly created workspace.
        """
        workspace_id = f"workspace_{secrets.token_urlsafe(9)}"
        now = datetime.now()

        workspace = Workspace(
            id=workspace_id,
            session_id=session_id,
            status=WorkspaceStatus.ACTIVE,
            created_at=now,
            last_used_at=now,
        )

        workspace_dir = self._get_workspace_dir(workspace)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / ".keep").touch()

        await self._save_metadata(workspace)

        logger.info("Created workspace: %s (session=%s)", workspace_id, session_id)
        return workspace

    async def get_or_create(self, session_id: str) -> Workspace:
        """Find an existing active workspace or create a new one.

        Args:
            session_id: Unique session identifier.

        Returns:
            Active workspace for the session.
        """
        existing = await self.find_by_session_id(session_id)
        if existing:
            existing.last_used_at = datetime.now()
            await self._save_metadata(existing)
            logger.info("Reusing workspace: %s (session=%s)", existing.id, session_id)
            return existing

        return await self.create(session_id)

    async def find_by_session_id(self, session_id: str) -> Workspace | None:
        """Find an active workspace by session_id.

        Uses direct path lookup: ``workspaces/{session_id}/_metadata.json``.

        Args:
            session_id: Unique session identifier.

        Returns:
            Active workspace or None.
        """
        try:
            session_dir = self._root / "workspaces" / session_id
            metadata_path = session_dir / "_metadata.json"

            if metadata_path.exists():
                content = metadata_path.read_text(encoding="utf-8")
                data = json.loads(content)
                workspace = Workspace.from_dict(data)

                if workspace.status == WorkspaceStatus.ACTIVE:
                    return workspace

            return None
        except Exception as e:
            logger.warning("Failed to find workspace for session %s: %s", session_id, e)
            return None

    async def update(self, workspace: Workspace) -> None:
        """Update workspace metadata (touches last_used_at)."""
        workspace.last_used_at = datetime.now()
        await self._save_metadata(workspace)

    async def delete(self, workspace: Workspace) -> bool:
        """Delete a workspace and its files.

        Args:
            workspace: Workspace to delete.

        Returns:
            True if successfully deleted.
        """
        try:
            workspace_dir = self._get_workspace_dir(workspace)
            if not workspace_dir.exists():
                return False

            shutil.rmtree(workspace_dir, ignore_errors=True)
            logger.info("Deleted workspace: %s", workspace.id)
            return True
        except Exception as e:
            logger.error("Failed to delete workspace %s: %s", workspace.id, e)
            return False

    async def _save_metadata(self, workspace: Workspace) -> None:
        metadata_path = self._get_metadata_path(workspace)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2)
        metadata_path.write_text(content, encoding="utf-8")

    def get_workspace_absolute_path(self, workspace: Workspace) -> str:
        """Get the absolute filesystem path of a workspace."""
        return str(self._root / workspace.path)


def create_workspace_service(
    *,
    root_dir: Path,
    storage_backend: "StorageProvider | None" = None,
) -> WorkspaceService:
    """Create a WorkspaceService rooted at explicit ``root_dir``.

    Aggregate workspace trees live under ``{root_dir}/workspaces/``. Callers must
    pass a deterministic host-derived path — never implicitly use process cwd.

    Args:
        root_dir: Storage root directory containing the ``workspaces`` subtree.
        storage_backend: Optional injected storage backend.

    Returns:
        Configured WorkspaceService instance.
    """
    return WorkspaceService(root_dir=Path(root_dir).expanduser().resolve(), storage_backend=storage_backend)
