"""CrawlEngine shared types and constants.

[POS]
Dataclasses and result aliases shared by CrawlEngine and its internal mixins.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document

SuccessResult = list[tuple[str, Document]]
FailedResult = list[tuple[str, None]]

# 403 anti-crawl / 429 rate-limit can be bypassed via browser layer, allow degradation
DEGRADABLE_4XX = frozenset({403, 429})


@dataclass(slots=True)
class CachedDocument:
    """Cached Document with HTTP validation metadata."""

    doc: Document
    etag: str | None = None
    last_modified: str | None = None
    cached_at: float = 0.0


@dataclass(slots=True)
class AccessStats:
    """URL access statistics (for priority calculation)."""

    count: int
    last_access: float


@dataclass(slots=True, order=True)
class BackgroundTask:
    """Background refresh task (supports priority sorting)."""

    priority: int
    url: str = ""
    cache_key: str = ""
    cached_item: CachedDocument | None = None
