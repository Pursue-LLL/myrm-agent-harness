"""Fine-grained key lock manager with full jitter exponential backoff."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager


class LockContentionTimeoutError(Exception):
    """Raised when acquiring a fine-grained key write lock exceeds max retries or timeout."""

    def __init__(self, key: str, attempts: int, elapsed_sec: float) -> None:
        super().__init__(
            f"Failed to acquire write lock for key '{key}' after {attempts} attempts ({elapsed_sec:.3f}s)"
        )
        self.key = key
        self.attempts = attempts
        self.elapsed_sec = elapsed_sec


def compute_jitter_backoff(
    retry: int,
    base_sec: float = 0.015,
    max_sec: float = 0.200,
) -> float:
    """Calculate exponential backoff duration with full randomized jitter to avoid thundering herd."""
    factor = min(max_sec, base_sec * (2**retry))
    # Full jitter uniform between 50% and 150% of nominal factor
    jitter = random.uniform(0.5, 1.5)
    return float(min(max_sec, factor * jitter))


class KeyLockManager:
    """Thread-safe fine-grained key-level write lock coordinator."""

    def __init__(
        self,
        base_backoff_sec: float = 0.015,
        max_backoff_sec: float = 0.200,
    ) -> None:
        self._global_lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._base_backoff_sec = base_backoff_sec
        self._max_backoff_sec = max_backoff_sec

    def _get_or_create_lock(self, key: str) -> threading.Lock:
        with self._global_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    @contextmanager
    def acquire_lock(
        self,
        key: str,
        max_retries: int = 5,
        timeout_sec: float = 1.0,
    ) -> Generator[bool]:
        """Attempt to acquire a key-level write lock with jittered retries."""
        target_lock = self._get_or_create_lock(key)
        start_time = time.time()
        acquired = False

        for attempt in range(max_retries):
            elapsed = time.time() - start_time
            if elapsed >= timeout_sec:
                break

            remaining_time = max(0.001, timeout_sec - elapsed)
            acquired = target_lock.acquire(blocking=True, timeout=min(remaining_time, 0.05))
            if acquired:
                break

            # Sleep with full jitter exponential backoff
            sleep_time = compute_jitter_backoff(
                attempt,
                base_sec=self._base_backoff_sec,
                max_sec=self._max_backoff_sec,
            )
            time.sleep(sleep_time)

        if not acquired:
            total_elapsed = time.time() - start_time
            raise LockContentionTimeoutError(
                key=key,
                attempts=max_retries,
                elapsed_sec=total_elapsed,
            )

        try:
            yield True
        finally:
            target_lock.release()

    def get_active_lock_count(self) -> int:
        """Return the number of tracked key locks."""
        with self._global_lock:
            return len(self._locks)
