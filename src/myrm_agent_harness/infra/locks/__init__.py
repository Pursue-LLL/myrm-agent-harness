"""Unified locking mechanisms for concurrent operations.

Provides file-based and memory-based locking primitives with built-in metrics.

[OUTPUT]
- FileLock: Unified file-based locking with metrics
- LockMetrics: Lock performance metrics
"""

from .file_lock import FileLock, LockMetrics, acquire_file_lock

__all__ = [
    "FileLock",
    "LockMetrics",
    "acquire_file_lock",
]
