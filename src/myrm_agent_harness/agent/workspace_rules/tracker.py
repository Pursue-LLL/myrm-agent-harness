"""Subdirectory context tracker for progressive rule discovery.

Monitors tool call arguments for file/directory paths. When a new
directory is accessed, checks for rule files (AGENTS.md, CLAUDE.md,
.cursorrules, .windsurfrules, .claude/CLAUDE.md,
.github/copilot-instructions.md, etc.) and appends their content
to the tool result.

Integration point: tool_interceptor_middleware POST-CALL stage.
The tracker appends discovered rules to tool results as supplementary
context, without modifying the system prompt (preserving KV Cache).

[INPUT]
- agent.workspace_rules.scanner::_CLAUDE_SUBDIR_FILE, _COPILOT_INSTRUCTIONS_FILE, _RULE_FILENAMES, _load_rule_file (POS: Rule file discovery and loading)

[OUTPUT]
- SubdirectoryContextTracker: stateful tracker, one per session
- get_subdirectory_tracker(): get or create session-scoped tracker
- check_and_append_rules(): check tool result for new directory rules

[POS]
Progressive subdirectory rule discovery. Monitors tool calls for
new directory access, discovers rule files, and appends content
to tool results without modifying the system prompt prefix.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_APPEND_CHARS = 16000
_MAX_ANCESTOR_WALK = 5

_PATH_ARG_KEYS: frozenset[str] = frozenset(
    {
        "path",
        "file_path",
        "filepath",
        "filename",
        "directory",
        "dir",
        "working_directory",
        "workdir",
        "cwd",
        "target",
        "source",
        "destination",
        "command",
    }
)


class SubdirectoryContextTracker:
    """Track accessed directories and discover rule files progressively."""

    __slots__ = ("_checked_dirs", "_workspace_root")

    def __init__(self, workspace_root: str) -> None:
        self._workspace_root = workspace_root
        self._checked_dirs: set[str] = set()
        if workspace_root:
            self._checked_dirs.add(str(Path(workspace_root).resolve()))

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, object],
        result_text: str,
    ) -> str | None:
        """Check tool call for new directories and return rule content to append.

        Returns rule content string if new rules discovered, None otherwise.
        """
        if not self._workspace_root:
            return None

        candidates = self._extract_directories(tool_name, tool_args)
        if not candidates:
            return None

        from myrm_agent_harness.agent.workspace_rules.scanner import (
            _scan_directory,
        )

        discovered_rules: list[str] = []
        total_chars = 0

        for directory in candidates:
            resolved = str(directory.resolve())
            if resolved in self._checked_dirs:
                continue
            self._checked_dirs.add(resolved)

            if not self._is_within_workspace(directory):
                continue

            rules = _scan_directory(directory)
            for rule in rules:
                if total_chars >= _MAX_APPEND_CHARS:
                    break

                content = rule.content
                remaining = _MAX_APPEND_CHARS - total_chars

                if len(content) > remaining:
                    # Truncate to fit remaining budget
                    content = content[:remaining] + f"\n\n[...truncated {Path(rule.path).name}: exceeded total append budget]"

                discovered_rules.append(f"[Discovered {Path(rule.path).name} in {directory}]\n{content}")
                total_chars += len(content)

        if not discovered_rules:
            return None

        logger.info(
            "Subdirectory rules discovered: %d file(s) in new directories",
            len(discovered_rules),
        )

        return "\n\n--- Workspace Rules (discovered in accessed directory) ---\n" + "\n\n".join(discovered_rules)

    def _extract_directories(self, tool_name: str, args: dict[str, object]) -> list[Path]:
        """Extract directory candidates from tool call arguments."""
        candidates: set[Path] = set()

        for key in _PATH_ARG_KEYS:
            raw_val = args.get(key)
            if not isinstance(raw_val, str) or not raw_val:
                continue
            self._add_path_candidate(raw_val, candidates)

        if tool_name in ("bash_code_execute_tool", "shell_exec"):
            raw_cmd = args.get("command")
            if isinstance(raw_cmd, str):
                self._extract_from_command(raw_cmd, candidates)

        return list(candidates)

    def _add_path_candidate(self, raw_path: str, candidates: set[Path]) -> None:
        """Resolve a path string and walk ancestors toward workspace root.

        Walks up from the resolved directory, stopping at the first
        already-checked directory or after _MAX_ANCESTOR_WALK levels.
        This ensures reading e.g. ``project/src/lib/main.py`` discovers
        ``project/AGENTS.md`` even when ``src/lib/`` has no rules.
        """
        try:
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = Path(self._workspace_root) / p

            target = p if p.is_dir() else p.parent
            if not target.is_dir():
                return

            for _ in range(_MAX_ANCESTOR_WALK):
                resolved = str(target.resolve())
                if resolved in self._checked_dirs:
                    break
                if self._is_within_workspace(target):
                    candidates.add(target)
                parent = target.parent
                if parent == target:
                    break
                target = parent
        except (OSError, ValueError):
            pass

    def _extract_from_command(self, command: str, candidates: set[Path]) -> None:
        """Extract directory references from shell commands (cd, ls, etc.)."""
        import shlex

        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()

        for i, token in enumerate(tokens):
            if token in ("cd", "ls", "cat", "head", "tail", "find", "grep") and i + 1 < len(tokens):
                next_token = tokens[i + 1]
                if not next_token.startswith("-"):
                    self._add_path_candidate(next_token, candidates)

    def _is_within_workspace(self, directory: Path) -> bool:
        """Check that directory is within the workspace boundary."""
        try:
            workspace = Path(self._workspace_root).resolve()
            resolved = directory.resolve()
            return resolved.is_relative_to(workspace)
        except (OSError, ValueError):
            return False


_tracker_var: ContextVar[SubdirectoryContextTracker] = ContextVar("subdirectory_tracker")


def get_subdirectory_tracker() -> SubdirectoryContextTracker | None:
    """Get the session-scoped subdirectory tracker, if initialized."""
    try:
        return _tracker_var.get()
    except LookupError:
        return None


def init_subdirectory_tracker(workspace_root: str) -> SubdirectoryContextTracker:
    """Initialize the session-scoped subdirectory tracker."""
    tracker = SubdirectoryContextTracker(workspace_root)
    _tracker_var.set(tracker)
    return tracker


def reset_subdirectory_tracker() -> None:
    """Reset the subdirectory tracker for the current session."""
    try:
        _tracker_var.get()
        _tracker_var.set(SubdirectoryContextTracker(""))
    except LookupError:
        pass


def check_and_append_rules(
    tool_name: str,
    tool_args: dict[str, object],
    result_text: str,
) -> str | None:
    """Convenience function: check tool call and return rules to append.

    Called from tool_interceptor_middleware POST-CALL stage.
    """
    tracker = get_subdirectory_tracker()
    if tracker is None:
        return None
    return tracker.check_tool_call(tool_name, tool_args, result_text)
