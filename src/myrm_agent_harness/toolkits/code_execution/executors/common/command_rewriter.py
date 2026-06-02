"""Command rewriting service.

Transforms commands for code execution (path rewriting, uv run wrapping).

[INPUT]
- (none)

[OUTPUT]
- CommandRewriter: Stateless command rewriter.

[POS]
Command rewriting service.
"""

import logging
import re
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class CommandRewriter:
    """Stateless command rewriter.

    Rewrites python commands to use ``uv run`` and resolves /workspace paths
    to actual working directories. Extensible for additional rewrite rules.
    """

    def rewrite_python_command(self, command: str) -> str:
        """Rewrite python commands to use ``uv run``.

        Transforms:
        - ``python script.py`` -> ``uv run python script.py``
        - ``python3 script.py`` -> ``uv run python3 script.py``

        Args:
            command: Original command.

        Returns:
            Rewritten command.
        """
        stripped = command.strip()

        if not re.match(r"^python3?(\s+|$)", stripped):
            return command

        uv_path = shutil.which("uv")
        if uv_path:
            new_command = f"uv run {stripped}"
            logger.warning(f" [CommandRewriter] Using uv run: {new_command[:100]}...")
            return new_command

        logger.warning(" [CommandRewriter] uv not available, using original command")
        return command

    def rewrite_workspace_paths(self, command: str, workspace_path: Path | None) -> str:
        """Rewrite /workspace paths in commands to the actual working directory.

        AI agents may use the container-convention path /workspace.
        This method resolves those to the actual workspace path.

        Handled patterns: ``cd /workspace``, ``/workspace/file.txt``, etc.

        Args:
            command: Original command.
            workspace_path: Actual working directory path.

        Returns:
            Rewritten command.
        """
        if not workspace_path:
            return command

        workspace_str = str(workspace_path)

        new_command = re.sub(
            r"/workspace(?=/|$|\s|;|&|\|)",
            workspace_str.replace("\\", "\\\\"),
            command,
        )

        if new_command != command:
            logger.warning(f" [CommandRewriter] Rewrote /workspace paths: {new_command[:100]}...")

        return new_command
