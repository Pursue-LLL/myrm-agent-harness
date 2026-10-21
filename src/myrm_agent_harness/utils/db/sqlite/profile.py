"""Declarative SQLite hardening profiles.

A ``SQLiteProfile`` fully describes the durability / privacy / performance PRAGMA
set for one connection. Stores pick a preset (or ``replace`` it for store-specific
tuning) instead of hand-writing scattered, divergent PRAGMA blocks.

[INPUT]
- (none — leaf module)

[OUTPUT]
- SQLiteProfile: frozen PRAGMA specification
- DEFAULT / DURABLE / SENSITIVE / CACHE / READONLY: shared presets

[POS]
Leaf configuration module for the unified SQLite hardening factory.
"""

from __future__ import annotations

from dataclasses import dataclass

_VALID_SYNC = frozenset({"OFF", "NORMAL", "FULL", "EXTRA"})
_VALID_SECURE_DELETE = frozenset({"ON", "OFF", "FAST"})


@dataclass(frozen=True, slots=True)
class SQLiteProfile:
    """PRAGMA specification for one hardened SQLite connection.

    Defaults encode the safe, general-purpose contract: WAL journaling, crash-safe
    ``synchronous=NORMAL``, B-tree torn-write detection, privacy-preserving deletes,
    and referential integrity.
    """

    use_wal: bool = True
    synchronous: str = "NORMAL"
    busy_timeout_ms: int = 5000
    secure_delete: str = "FAST"
    cell_size_check: bool = True
    foreign_keys: bool = True
    cache_size: int | None = None
    temp_store_memory: bool = False
    mmap_size_bytes: int | None = None
    page_size_bytes: int | None = None
    wal_autocheckpoint_pages: int | None = None
    read_only: bool = False

    def __post_init__(self) -> None:
        if self.synchronous.upper() not in _VALID_SYNC:
            raise ValueError(f"invalid synchronous mode: {self.synchronous}")
        if self.secure_delete.upper() not in _VALID_SECURE_DELETE:
            raise ValueError(f"invalid secure_delete mode: {self.secure_delete}")
        if self.busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")


# General-purpose hardened default (WAL + NORMAL + FAST secure delete).
DEFAULT = SQLiteProfile()

# Durability-critical, larger working set: memory graph / relational stores.
DURABLE = SQLiteProfile(
    cache_size=-64000,
    temp_store_memory=True,
    mmap_size_bytes=268_435_456,
)

# Sensitive content (PII pseudonyms): zero deleted bytes immediately.
SENSITIVE = SQLiteProfile(secure_delete="ON")

# Rebuildable caches: drop the privacy cost, keep crash-safety + concurrency.
CACHE = SQLiteProfile(secure_delete="OFF")

# Read-only probes / reader connections: no journal/secure-delete writes.
READONLY = SQLiteProfile(read_only=True, use_wal=False, secure_delete="OFF")
