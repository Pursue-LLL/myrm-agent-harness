"""Per-path asyncio lock manager for file write operations.

[INPUT]
- (none)

[OUTPUT]
- acquire_file_path_lock: async context manager that serializes writes per normalized path

[POS]
In-process file write lock manager. Ensures same-path write operations are serialized
while allowing parallel writes to different paths.
"""

from __future__ import annotations

import asyncio
import os
import weakref
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

_FILE_PATH_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_FILE_PATH_LOCKS_GUARD = asyncio.Lock()


def _normalize_lock_path(path: str) -> str:
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return os.path.abspath(str(expanded))
    return os.path.abspath(str(Path.cwd() / expanded))


async def _get_file_path_lock(normalized_path: str) -> asyncio.Lock:
    async with _FILE_PATH_LOCKS_GUARD:
        lock = _FILE_PATH_LOCKS.get(normalized_path)
        if lock is None:
            lock = asyncio.Lock()
            _FILE_PATH_LOCKS[normalized_path] = lock
        return lock


@asynccontextmanager
async def acquire_file_path_lock(path: str) -> AsyncGenerator[str, None]:
    """Acquire an in-process lock keyed by normalized absolute file path."""
    normalized_path = _normalize_lock_path(path)
    lock = await _get_file_path_lock(normalized_path)
    async with lock:
        yield normalized_path

