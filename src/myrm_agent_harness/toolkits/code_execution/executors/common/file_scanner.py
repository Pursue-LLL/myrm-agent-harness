"""Generated files scanner.

Scans files created during code execution for artifact collection.

[INPUT]
- (none)

[OUTPUT]
- GeneratedFilesScanner: Abstract base class for generated file scanning.
- LocalFilesScanner: Local filesystem generated file scanner.

[POS]
Generated files scanner.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.executors.common.executor_utils import (
    should_filter_skill_resource,
    should_ignore_artifact,
)

logger = logging.getLogger(__name__)


class GeneratedFilesScanner(ABC):
    """Abstract base class for generated file scanning.

    Scans file paths created during execution. Filters system files and
    skill resources using mtime-based detection (O(n) time complexity).

    Note: This is the framework-layer scanner (path discovery only).
    Business-layer ArtifactProcessor handles persistence and URL generation.
    """

    @abstractmethod
    async def scan(
        self,
        start_time: float,
        workspace: Path | None,
    ) -> list[str]:
        """Scan for files generated during execution.

        Args:
            start_time: Execution start timestamp (time.time()).
            workspace: Workspace path.

        Returns:
            List of absolute paths to generated files.
        """
        pass


class LocalFilesScanner(GeneratedFilesScanner):
    """Local filesystem generated file scanner.

    Filters by file modification time (mtime) against the execution start time.
    """

    async def scan(
        self,
        start_time: float,
        workspace: Path | None,
    ) -> list[str]:
        """Scan the local workspace for generated files.

        Strategy:
        1. Walk workspace files, check mtime >= start_time
        2. Filter system files and skill resources
        3. Fallback: check /tmp for user-generated files

        Args:
            start_time: Execution start timestamp.
            workspace: Workspace path.

        Returns:
            List of absolute paths to generated files.
        """
        generated: list[str] = []

        # Small tolerance for filesystem timestamp precision
        threshold = start_time - 0.01

        if workspace and workspace.exists():
            for file_path in workspace.rglob("*"):
                if not file_path.is_file() or file_path.name.startswith("."):
                    continue

                if should_ignore_artifact(file_path.name):
                    continue

                try:
                    relative_path = file_path.relative_to(workspace)
                    if should_filter_skill_resource(relative_path):
                        logger.debug(f" Skipping skill resource: {relative_path}")
                        continue
                except ValueError:
                    pass

                try:
                    mtime = file_path.stat().st_mtime
                    if mtime >= threshold:
                        generated.append(str(file_path.absolute()))
                except Exception:
                    pass

        # Fallback: check /tmp for user-generated files
        tmp_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".xlsx", ".docx", ".html"}
        tmp_path = Path("/tmp")
        if tmp_path.exists():
            for file_path in tmp_path.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in tmp_extensions:
                    try:
                        if file_path.stat().st_mtime >= threshold:
                            generated.append(str(file_path))
                            logger.info(f" [fallback] Found user file in /tmp: {file_path}")
                    except Exception:
                        pass

        if generated:
            logger.info(f" Files generated in this execution: {generated}")

        return generated
