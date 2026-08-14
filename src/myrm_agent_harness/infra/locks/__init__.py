"""Unified locking mechanisms for concurrent operations.

Provides file-based locking primitives for coordinating asyncio tasks
within the same sandbox process.

[OUTPUT]
- FileLock: Unified file-based locking
- acquire_file_lock: Convenience function for common use cases
"""

from .file_lock import FileLock, acquire_file_lock

__all__ = [
    "FileLock",
    "acquire_file_lock",
]
