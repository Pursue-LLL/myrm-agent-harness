"""
[POS] src/myrm_agent_harness/core/security/keychain_rest_encryption/cold_boot_guard.py
[INPUT] gc, logging, threading, time, uuid
[OUTPUT] ColdBootDefenseGuard

Cold-boot defense guard providing in-memory key buffer zeroization and emergency instant purge.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import gc
import logging
import threading
import time
import uuid

from .types import KeychainBackendType, KeyPurgeScope, PurgeReport

logger = logging.getLogger(__name__)


class ColdBootDefenseGuard:
    """Guards in-memory cryptographic keys against cold-boot extraction and implements emergency zeroization."""

    def __init__(self) -> None:
        self._lock: threading.RLock = threading.RLock()
        self._key_buffers: dict[str, bytearray] = {}

    def retain_key(self, key_id: str, raw_key: bytes) -> None:
        """Store key in a mutable bytearray buffer for controllable zeroization."""
        with self._lock:
            # Overwrite existing buffer if present
            if key_id in self._key_buffers:
                self._zeroize_buffer(self._key_buffers[key_id])
            self._key_buffers[key_id] = bytearray(raw_key)

    def get_key(self, key_id: str) -> bytes | None:
        """Fetch immutable bytes copy of the retained key."""
        with self._lock:
            buf = self._key_buffers.get(key_id)
            if buf is not None:
                return bytes(buf)
            return None

    def has_key(self, key_id: str) -> bool:
        """Check if a specific key is currently held in volatile memory."""
        with self._lock:
            return key_id in self._key_buffers

    def purge_memory(self) -> int:
        """Zeroize all held in-memory key buffers and force memory release."""
        with self._lock:
            count = len(self._key_buffers)
            for buf in self._key_buffers.values():
                self._zeroize_buffer(buf)
            self._key_buffers.clear()
            gc.collect()
            return count

    def execute_instant_purge(
        self,
        scope: KeyPurgeScope,
        backend_type: KeychainBackendType,
        keychain_delete_callback: bool,
    ) -> PurgeReport:
        """Execute instant purge according to designated scope and return formal audit report."""
        with self._lock:
            zeroized_count: int = self.purge_memory()
            report = PurgeReport(
                purge_id=f"purge-{uuid.uuid4().hex[:12]}",
                scope=scope,
                backend_type=backend_type,
                keys_zeroized=zeroized_count,
                keychain_deleted=keychain_delete_callback,
                timestamp=time.time(),
            )
            logger.warning("Executed instant cryptographic purge: %s", report)
            return report

    @staticmethod
    def _zeroize_buffer(buf: bytearray) -> None:
        """Explicitly overwrite every byte of mutable memory buffer with zero."""
        for i in range(len(buf)):
            buf[i] = 0
