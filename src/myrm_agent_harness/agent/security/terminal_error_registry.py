"""Turn-scoped terminal error storage with persistence.

Maintains a set of terminal error categories (e.g., 'network_blocked') that
should block subsequent tool calls in the same turn. Persists to a hidden
JSON file in the workspace root to survive server restarts.

[INPUT]
- (none)

[OUTPUT]
- TerminalErrorRegistry: Persistent registry for terminal failure states.

[POS]
Turn-scoped terminal error storage with persistence.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILENAME = ".myrm_terminal_errors.json"


class TerminalErrorRegistry:
    """Persistent registry for terminal failure states."""

    def __init__(self, workspace_path: str | Path | None = None):
        self.workspace_path = Path(workspace_path) if workspace_path else None
        self._errors: set[str] = set()
        self._load()

    def _get_storage_path(self) -> Path | None:
        from myrm_agent_harness.agent.middlewares._session_context import get_workspace_root

        # 0. Myrm-God-Mode: Explicit environment override (Highest Priority for testing/sync)
        if env_path := os.environ.get("MYRM_TERMINAL_ERRORS_PATH"):
            return Path(env_path)

        # 1. Try explicit path injection
        ws = self.workspace_path or get_workspace_root()
        if ws:
            return Path(ws) / _STATE_FILENAME

        # 2. Heuristic: Search upwards for the file (Crucial for integration tests)
        curr = Path.cwd().resolve()
        for parent in [curr, *list(curr.parents)]:
            p = parent / _STATE_FILENAME
            if p.exists():
                return p

        # 3. Default to CWD for new creations
        return Path.cwd() / _STATE_FILENAME

    def _load(self) -> None:
        path = self._get_storage_path()
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._errors = set(data)
            except Exception as e:
                logger.debug(f"Failed to load terminal errors from {path}: {e}")

    def _save(self) -> None:
        path = self._get_storage_path()
        if not path:
            return
        try:
            path.write_text(json.dumps(list(self._errors)), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Failed to save terminal errors to {path}: {e}")

    def add(self, category: str) -> None:
        """Add a terminal error category."""
        if category not in self._errors:
            self._errors.add(category)
            self._save()

    def clear(self) -> None:
        """Clear all terminal errors."""
        if self._errors:
            self._errors.clear()
            path = self._get_storage_path()
            if path and path.exists():
                with contextlib.suppress(Exception):
                    path.unlink()

    def get_all(self) -> set[str]:
        """Get all registered terminal errors."""
        return self._errors.copy()
