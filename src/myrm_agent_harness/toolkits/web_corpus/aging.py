"""Web corpus aging — LRU eviction and disk quota enforcement.

[INPUT]
- .store::WebCorpusStore (POS: corpus store for eviction operations)

[OUTPUT]
- CorpusAgingPolicy: Configurable aging policy with time-based and disk-based eviction.
- run_aging: Execute a single aging pass on a WebCorpusStore.

[POS]
Prevents unbounded disk growth. Evicts entries by LRU (least recently accessed)
when total disk exceeds quota or entries exceed max age.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .store import WebCorpusStore

logger = logging.getLogger(__name__)

_DEFAULT_MAX_AGE_DAYS = 30
_DEFAULT_MAX_DISK_MB = 500


@dataclass(frozen=True, slots=True)
class CorpusAgingPolicy:
    """Configurable aging policy for the web corpus."""

    max_age_days: int = _DEFAULT_MAX_AGE_DAYS
    max_disk_mb: int = _DEFAULT_MAX_DISK_MB


def run_aging(store: WebCorpusStore, policy: CorpusAgingPolicy | None = None) -> int:
    """Execute a single aging pass. Returns number of evicted entries."""
    if policy is None:
        policy = CorpusAgingPolicy()

    evicted = 0
    cutoff = datetime.now(UTC) - timedelta(days=policy.max_age_days)
    cutoff_iso = cutoff.isoformat()

    for norm_url in store.list_stale(cutoff_iso):
        if store.delete_by_normalized_url(norm_url):
            evicted += 1

    stats = store.get_stats()
    max_bytes = policy.max_disk_mb * 1024 * 1024
    if stats.disk_bytes > max_bytes:
        overflow = stats.disk_bytes - max_bytes
        freed = 0
        for norm_url in store.list_lru():
            if freed >= overflow:
                break
            content = store.get_content(norm_url)
            entry_size = len(content.encode("utf-8")) if content else 0
            if store.delete_by_normalized_url(norm_url):
                freed += entry_size
                evicted += 1

    if evicted > 0:
        logger.info("Web corpus aging: evicted %d entries", evicted)

    return evicted
