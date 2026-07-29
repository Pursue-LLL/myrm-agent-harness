"""Web corpus data types.

[INPUT]
- (none)

[OUTPUT]
- WebCorpusEntry: A single indexed web page entry.
- CorpusStats: Aggregate statistics for the web corpus store.

[POS]
Shared data models for the web corpus persistent index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class WebCorpusEntry:
    """A single indexed web page in the persistent corpus."""

    url: str
    normalized_url: str
    title: str
    snippet: str
    fetched_content_path: str | None = None
    date: str | None = None
    source: str = "fetch"
    agent_id: str | None = None
    access_count: int = 1
    content_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class CorpusStats:
    """Aggregate statistics for the web corpus store."""

    total_entries: int = 0
    disk_bytes: int = 0
    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None
    hit_count: int = 0
    miss_count: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0
