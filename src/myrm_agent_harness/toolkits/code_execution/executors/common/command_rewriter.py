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

        The resolved workspace path itself is protected before rewriting, so a
        command that already contains the real workspace (e.g. eval graders
        addressing ``{workspace}`` where the cache layout ends in ``/workspace``)
        is never re-expanded into a duplicated path.
        """
        if not workspace_path:
            return command

        workspace_str = str(workspace_path)

        placeholders: list[str] = []

        def _protect(match: re.Match[str]) -> str:
            token = f"\x00wbws{len(placeholders)}\x00"
            placeholders.append(match.group(0))
            return token

        protected = re.sub(re.escape(workspace_str), _protect, command)

        new_command = re.sub(
            r"/workspace(?=/|$|\s|;|&|\|)",
            workspace_str.replace("\\", "\\\\"),
            protected,
        )

        for index, real in enumerate(placeholders):
            new_command = new_command.replace(f"\x00wbws{index}\x00", real)

        if new_command != command:
            logger.warning(f" [CommandRewriter] Rewrote /workspace paths: {new_command[:100]}...")

        return new_command

    def rewrite_search_commands(self, command: str) -> str:
        """Transparently route grep to ripgrep (rg) if available.

        Converts grep invocations to ripgrep (rg --no-ignore) while preserving
        semantic flags and safely removing incompatible/redundant recursive
        flags (-r, -R) because ripgrep is recursive by default (in rg, -r is --replace).
        Quoted strings are protected to avoid corrupting grep inside arguments.

        Args:
            command: Original shell command.

        Returns:
            Transparently rewritten command using rg, or original if rg is unavailable.
        """
        rg_path = shutil.which("rg")
        if not rg_path:
            return command

        grep_cmd_re = re.compile(r"(?<![-\w])grep(?=\s|$)")

        # Protect quoted strings so words inside arguments are never rewritten
        placeholders: list[str] = []

        def _protect(match: re.Match[str]) -> str:
            token = f"\x00wbgrep{len(placeholders)}\x00"
            placeholders.append(match.group(0))
            return token

        protected = re.sub(r"(\x27[^\x27]*\x27|\"[^\"]*\")", _protect, command)

        if not grep_cmd_re.search(protected):
            return command

        def _clean_grep_args(segment: str) -> str:
            def _flag_replacer(m: re.Match[str]) -> str:
                flag = m.group(0)
                if flag in ("-r", "-R", "--recursive", "--dereference-recursive"):
                    return ""
                if flag.startswith("-") and not flag.startswith("--"):
                    cleaned = re.sub(r"[rR]", "", flag)
                    return "" if cleaned == "-" else cleaned
                return flag

            cleaned = re.sub(
                r"(?:--recursive|--dereference-recursive|-[a-zA-Z]+)",
                _flag_replacer,
                segment,
            )
            return grep_cmd_re.sub("rg --no-ignore", cleaned, count=1)

        segments = re.split(r"([;|&]+)", protected)
        rewritten_parts: list[str] = []
        for part in segments:
            if grep_cmd_re.search(part):
                rewritten_parts.append(_clean_grep_args(part))
            else:
                rewritten_parts.append(part)

        result = "".join(rewritten_parts)
        for idx, orig in enumerate(placeholders):
            result = result.replace(f"\x00wbgrep{idx}\x00", orig)

        if result != command:
            logger.debug(f" [CommandRewriter] Routed grep to rg: {result[:100]}...")

        return result
