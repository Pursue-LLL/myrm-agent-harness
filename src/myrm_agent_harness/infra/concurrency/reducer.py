"""State reducer for parallel execution.

[INPUT]
- collections.abc::Callable (POS: Callable protocol)

[OUTPUT]
- StateReducer: Thread-safe/Async-safe state reducer for merging parallel execution results.

[POS]
State reducer for parallel execution. Serializes async patch application for shared state.
"""

import asyncio
from collections.abc import Callable


class StateReducer[StateT, PatchT]:
    """Thread-safe/Async-safe state reducer for merging parallel execution results."""

    def __init__(self, initial_state: StateT, reducer_fn: Callable[[StateT, PatchT], StateT]) -> None:
        self._state = initial_state
        self._reducer_fn = reducer_fn
        self._lock = asyncio.Lock()

    async def apply_patch(self, patch: PatchT) -> None:
        """Apply a patch to the state safely."""
        async with self._lock:
            self._state = self._reducer_fn(self._state, patch)

    async def get_state(self) -> StateT:
        """Get the current state safely."""
        async with self._lock:
            return self._state
