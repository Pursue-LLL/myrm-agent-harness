"""Transaction lifecycle and after-commit hook manager.

[INPUT]
- Hook callbacks registered during memory mutations and SQLite transaction states.

[OUTPUT]
- TransactionHookManager ensuring after-commit emission and rollback discard semantics.

[POS]
- Memory transaction hook dispatcher preventing premature or spurious invalidation events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import NamedTuple

logger = logging.getLogger(__name__)


class SavepointFrame(NamedTuple):
    """Savepoint boundary tracking nested pending hooks."""

    name: str
    hooks: list[Callable[[], None]]


class TransactionHookManager:
    """Manages transaction-scoped after-commit hooks with savepoint rollback support.

    Guarantees:
    1. Caller transaction uncommitted -> no invalidation events emitted.
    2. Explicit commit -> execute queued hooks in FIFO sequence.
    3. Transaction rollback -> discard all queued hooks immediately.
    4. Savepoint rollback -> discard hooks registered within that savepoint scope.
    5. Savepoint release -> merge hooks into enclosing transaction scope.
    """

    def __init__(self) -> None:
        self._root_hooks: list[Callable[[], None]] = []
        self._savepoint_stack: list[SavepointFrame] = []

    @property
    def pending_count(self) -> int:
        """Total count of pending after-commit hooks across root and savepoint frames."""
        total = len(self._root_hooks)
        for frame in self._savepoint_stack:
            total += len(frame.hooks)
        return total

    def queue_after_commit(self, hook: Callable[[], None]) -> None:
        """Register a hook to run only after the outer transaction commits."""
        if self._savepoint_stack:
            self._savepoint_stack[-1].hooks.append(hook)
        else:
            self._root_hooks.append(hook)

    def on_savepoint(self, name: str) -> None:
        """Mark entry into a nested savepoint boundary."""
        self._savepoint_stack.append(SavepointFrame(name=name, hooks=[]))

    def on_release_savepoint(self, name: str) -> None:
        """Release savepoint and merge its hooks into the parent scope."""
        target_idx = -1
        for idx in range(len(self._savepoint_stack) - 1, -1, -1):
            if self._savepoint_stack[idx].name == name:
                target_idx = idx
                break

        if target_idx == -1:
            return

        popped = self._savepoint_stack.pop(target_idx)
        if self._savepoint_stack:
            self._savepoint_stack[-1].hooks.extend(popped.hooks)
        else:
            self._root_hooks.extend(popped.hooks)

    def on_rollback_to_savepoint(self, name: str) -> None:
        """Roll back to a specific savepoint, discarding its hooks and any inner frames."""
        target_idx = -1
        for idx in range(len(self._savepoint_stack) - 1, -1, -1):
            if self._savepoint_stack[idx].name == name:
                target_idx = idx
                break

        if target_idx == -1:
            return

        # Discard this frame and all descendants
        del self._savepoint_stack[target_idx:]

    def on_commit(self) -> int:
        """Drain and execute all pending hooks after successful transaction commit."""
        all_hooks: list[Callable[[], None]] = list(self._root_hooks)
        for frame in self._savepoint_stack:
            all_hooks.extend(frame.hooks)

        self._root_hooks.clear()
        self._savepoint_stack.clear()

        executed = 0
        for hook in all_hooks:
            try:
                hook()
                executed += 1
            except Exception as exc:
                logger.error("Error executing after-commit hook: %s", exc, exc_info=True)

        return executed

    def on_rollback(self) -> int:
        """Discard all pending hooks upon transaction abort or error."""
        discarded = self.pending_count
        self._root_hooks.clear()
        self._savepoint_stack.clear()
        return discarded
