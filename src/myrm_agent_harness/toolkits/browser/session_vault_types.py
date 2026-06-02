"""Data types for SessionVault module.

[INPUT]
- (none)

[OUTPUT]
- SessionEntry: Immutable record of a saved browser session.
- VaultMetrics: Runtime metrics for SessionVault operations.

[POS]
Data types for SessionVault module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SessionEntry:
    """Immutable record of a saved browser session."""

    domain: str
    storage_state: Any
    created_at: float
    expires_at: float | None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at


@dataclass
class VaultMetrics:
    """Runtime metrics for SessionVault operations."""

    cache_hits: int = 0
    cache_misses: int = 0
    cache_evictions: int = 0
    cache_memory_bytes: int = 0
    encryption_count: int = 0
    decryption_count: int = 0
    encryption_total_ms: float = 0.0
    decryption_total_ms: float = 0.0

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate (0.0 - 1.0)."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    @property
    def avg_encryption_ms(self) -> float:
        """Calculate average encryption time."""
        return self.encryption_total_ms / self.encryption_count if self.encryption_count > 0 else 0.0

    @property
    def avg_decryption_ms(self) -> float:
        """Calculate average decryption time."""
        return self.decryption_total_ms / self.decryption_count if self.decryption_count > 0 else 0.0
