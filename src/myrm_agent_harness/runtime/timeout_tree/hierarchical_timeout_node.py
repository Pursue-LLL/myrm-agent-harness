"""Hierarchical timeout tree node with recursive neural-like cancel propagation.

Enforces strict deadline containment (child timeout <= parent remaining time)
and delivers millisecond-level cancel signals down the tree to abort orphan tasks.

[INPUT]
- __future__
- asyncio
- time
- types
- timeout_tree_types

[OUTPUT]
- TimeoutTreeNode

[POS]
Hierarchical timeout tree node with recursive neural-like cancel propagation.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType

from .timeout_tree_types import (
    CancelHookCallback,
    CancelReason,
    CascadeCancelSignal,
    TimeoutLevel,
)


class TimeoutTreeNode:
    """A node in the hierarchical timeout tree governing deadlines and cancellation signals."""

    def __init__(
        self,
        node_id: str,
        level: TimeoutLevel,
        timeout_s: float,
        parent: TimeoutTreeNode | None = None,
    ) -> None:
        self.node_id = node_id
        self.level = level
        self.timeout_s = timeout_s
        self.parent = parent
        self.children: list[TimeoutTreeNode] = []
        self._start_time = time.time()
        self._is_cancelled = False
        self._cancel_signal: CascadeCancelSignal | None = None
        self._cancel_hooks: list[CancelHookCallback] = []
        self._associated_tasks: list[asyncio.Task[object]] = []
        self._timer_task: asyncio.Task[None] | None = None

        if self.parent:
            self.parent.children.append(self)

    @property
    def is_cancelled(self) -> bool:
        """True if this node or any ancestor has received a cancellation signal."""
        if self._is_cancelled:
            return True
        return bool(self.parent and self.parent.is_cancelled)

    @property
    def remaining_time_s(self) -> float:
        """Calculate remaining time before this node's deadline expires."""
        elapsed = time.time() - self._start_time
        own_remaining = max(0.0, self.timeout_s - elapsed)
        if self.parent:
            parent_remaining = self.parent.remaining_time_s
            return min(own_remaining, parent_remaining)
        return own_remaining

    def create_child(
        self,
        node_id: str,
        level: TimeoutLevel,
        requested_timeout_s: float,
        safety_buffer_s: float = 0.0,
    ) -> TimeoutTreeNode:
        """Create a child timeout node constrained strictly by the parent's remaining deadline.

        Child deadline is automatically clamped so it never exceeds parent remaining time.
        """
        available = self.remaining_time_s - safety_buffer_s
        clamped_timeout = min(requested_timeout_s, max(0.01, available))
        return TimeoutTreeNode(
            node_id=node_id,
            level=level,
            timeout_s=clamped_timeout,
            parent=self,
        )

    def attach_task(self, task: asyncio.Task[object]) -> None:
        """Bind an asyncio Task to this node so it is cancelled automatically when signal arrives."""
        self._associated_tasks.append(task)

    def add_cancel_hook(self, hook: CancelHookCallback) -> None:
        """Attach a resource cleanup callback invoked immediately during cancellation."""
        self._cancel_hooks.append(hook)

    async def propagate_cancel(self, signal: CascadeCancelSignal) -> None:
        """Propagate cancellation signal recursively down the tree to all children and hooks.

        Acts like a neural signal, terminating downstream operations in milliseconds.
        """
        if self._is_cancelled:
            return

        self._is_cancelled = True
        self._cancel_signal = signal

        # 1. Cancel all directly attached asyncio tasks
        for task in self._associated_tasks:
            if not task.done():
                task.cancel()

        # 2. Invoke attached cancel hooks (e.g. killing sub-processes, closing sockets)
        for hook in self._cancel_hooks:
            try:
                res = hook()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                # Hook execution errors must not interrupt cascade propagation
                pass

        # 3. Recursively propagate down to all child nodes
        for child in list(self.children):
            child_signal = CascadeCancelSignal(
                source_level=signal.source_level,
                reason=signal.reason,
                details=f"Cascade from parent '{self.node_id}': {signal.details}",
                triggered_at=signal.triggered_at,
            )
            await child.propagate_cancel(child_signal)

    async def __aenter__(self) -> TimeoutTreeNode:
        """Start the node's watchdog timer on enter."""
        self._start_time = time.time()
        self._timer_task = asyncio.create_task(self._watchdog_loop())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Cancel watchdog timer and detach from parent on scope exit."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        if self.parent and self in self.parent.children:
            self.parent.children.remove(self)

    async def _watchdog_loop(self) -> None:
        """Background watchdog triggering upstream timeout propagation upon expiration."""
        try:
            await asyncio.sleep(self.remaining_time_s)
            signal = CascadeCancelSignal(
                source_level=self.level,
                reason=CancelReason.UPSTREAM_TIMEOUT,
                details=f"Node '{self.node_id}' ({self.level.value}) deadline of {self.timeout_s}s expired.",
            )
            await self.propagate_cancel(signal)
        except asyncio.CancelledError:
            # Watchdog cancelled cleanly on scope exit
            pass
