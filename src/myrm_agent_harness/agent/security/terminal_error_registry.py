"""Turn-scoped terminal error storage with a durable God-Mode injection channel.

Two channels, cleanly separated:

1. **Turn-scoped runtime state** (``self._errors``, in-memory): ``add()`` from
   ``handle_execution_error`` records non-recoverable failures (e.g.
   ``config_or_auth:search``). This set lives in the per-run ContextVar and is
   cleared by ``reset_terminal_errors()`` at the start of every agent run, so a
   broken configuration never leaks into a later turn.

2. **Durable God-Mode injection** (the state file): external operators write
   terminal categories (e.g. ``network_blocked``) to a JSON file pointed at by
   ``MYRM_TERMINAL_ERRORS_PATH`` (or the workspace-root default). The file is
   *merged* into the in-memory set at every ``_load()``, survives resets, and is
   never written by ``add()`` — only read. This lets an operator force a global
   terminal state (network blocked / read-only sandbox / full stop) that must
   take effect even after a server restart, independently of turn scoping.

[INPUT]
- (none)

[OUTPUT]
- TerminalErrorRegistry: Turn-scoped runtime state + durable God-Mode injection.

[POS]
Turn-scoped terminal error storage with a durable operator injection channel.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILENAME = ".myrm_terminal_errors.json"


class TerminalErrorRegistry:
    """Turn-scoped terminal failure state with a durable God-Mode file channel."""

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
        # Merge the God-Mode injection channel into the in-memory set. Merge
        # (not replace) so runtime categories registered this turn are never
        # clobbered by a re-read during circuit-breaker checks.
        path = self._get_storage_path()
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._errors.update(str(item) for item in data)
            except Exception as e:
                logger.debug(f"Failed to load terminal errors from {path}: {e}")

    def add(self, category: str) -> None:
        """Register a turn-scoped terminal error category (in-memory only).

        Runtime failures must never leak into a later turn, so ``add`` does not
        write the durable God-Mode file. Operators who want a category to survive
        restarts write the file directly (or point ``MYRM_TERMINAL_ERRORS_PATH``
        at it).
        """
        self._errors.add(category)

    def clear(self) -> None:
        """Clear turn-scoped runtime state. The God-Mode file is left untouched."""
        self._errors.clear()

    def get_all(self) -> set[str]:
        """Get all active terminal categories (runtime state merged with the
        God-Mode injection channel)."""
        self._load()
        return self._errors.copy()
