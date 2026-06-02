"""Artifact observer for registering generated files and pushing realtime content.

[INPUT]
- (none)

[OUTPUT]
- ArtifactObserver: Registers generated files to ArtifactRegistry and pushes ...

[POS]
Artifact observer for registering generated files and pushing realtime content.
"""

from __future__ import annotations

import logging
import os

from .base import FileOperationObserver

logger = logging.getLogger(__name__)


class ArtifactObserver(FileOperationObserver):
    """Registers generated files to ArtifactRegistry and pushes realtime content updates."""

    async def on_file_created(self, path: str, content: str) -> None:
        try:
            from myrm_agent_harness.agent.artifacts.registry import register_generated_files
            from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor

            actual_path = path
            executor = get_executor()
            logger.warning(f" [ArtifactObserver] on_file_created: path={path}, executor={executor}")
            if executor:
                from pathlib import Path as _Path
                wp = _Path(executor.workspace_path).resolve()
                clean = path
                if clean.startswith("/workspace"):
                    clean = clean[len("/workspace") :].lstrip("/") or "."
                if not _Path(clean).is_absolute():
                    actual_path = str((wp / clean).resolve())

            logger.warning(f" [ArtifactObserver] on_file_created: actual_path={actual_path}")
            register_generated_files([actual_path])
            self._push_realtime_content(path, content)
            logger.info(f"Registered artifact: {actual_path}")
        except Exception as e:
            logger.debug(f"Failed to register artifact: {e}")

    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        try:
            from myrm_agent_harness.agent.artifacts.registry import register_generated_files
            from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor

            actual_path = path
            executor = get_executor()
            if executor:
                from pathlib import Path as _Path
                wp = _Path(executor.workspace_path).resolve()
                clean = path
                if clean.startswith("/workspace"):
                    clean = clean[len("/workspace") :].lstrip("/") or "."
                if not _Path(clean).is_absolute():
                    actual_path = str((wp / clean).resolve())

            register_generated_files([actual_path])
            logger.info(f"Updated artifact: {actual_path}")
        except Exception as e:
            logger.debug(f"Failed to update artifact: {e}")

    async def on_file_viewed(self, path: str) -> None:
        pass

    def _push_realtime_content(self, path: str, content: str) -> None:
        try:
            from myrm_agent_harness.agent.artifacts.constants import (
                infer_artifact_type_from_extension,
                infer_language_from_extension,
            )
            from myrm_agent_harness.agent.artifacts.registry import push_realtime_content

            filename = os.path.basename(path)
            push_realtime_content(
                filename=filename,
                content=content,
                is_complete=True,
                artifact_type=infer_artifact_type_from_extension(filename),
                language=infer_language_from_extension(filename),
            )
        except Exception as e:
            logger.debug(f"Failed to push realtime content: {e}")
