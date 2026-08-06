"""Workflow events SQLite path resolution SSOT.

[INPUT]
- toolkits.code_execution.workspace.storage_root_bind::workspace_storage_fs_root_strict (POS: bound aggregate workspace root)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: workspace root auto-detection)

[OUTPUT]
- resolve_workflow_events_db_path: absolute path to workflow_events.db

[POS]
Shared path resolver for WorkflowEventStore and WorkflowTemplateStore.
Aligns with background_jobs.db under ``{harness_root}/.myrm/``.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_workflow_events_db_path(*, harness_root: Path | str | None = None) -> Path:
    """Resolve the workflow events SQLite file path.

    Resolution order:
    1. Explicit ``harness_root`` (server ContextBundleFacade.harness_path)
    2. Bound ``workspaces_storage_root`` ContextVar (active agent task)
    3. WorkspacePathResolver workspace root
    4. ``MYRM_DATA_DIR`` or cwd ``.myrm/`` fallback
    """
    if harness_root is not None:
        root = Path(harness_root).expanduser().resolve()
        return root / ".myrm" / "workflow_events.db"

    try:
        from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
            workspace_storage_fs_root_strict,
        )

        return workspace_storage_fs_root_strict() / ".myrm" / "workflow_events.db"
    except RuntimeError:
        pass

    try:
        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
            WorkspacePathResolver,
        )

        return WorkspacePathResolver.resolve_workspace_root() / ".myrm" / "workflow_events.db"
    except Exception:
        pass

    data_dir = os.environ.get("MYRM_DATA_DIR")
    if data_dir:
        return Path(data_dir).expanduser().resolve() / "workflow_events.db"

    return Path.cwd() / ".myrm" / "workflow_events.db"
