"""Fetcher protocol and data models.

Defines a unified fetch interface and intermediate result types,
allowing different fetch strategies to be plugged in interchangeably.

[INPUT]
- (none)

[OUTPUT]
- FetcherType: class — Fetcher type enum
- FetchResult: class — Unified fetch result
- Fetcher: class — Pluggable fetcher protocol

[POS]
Provides FetcherType, FetchResult, Fetcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol, runtime_checkable


class FetcherType(Enum):
    HTTP = auto()
    BROWSER = auto()
    STEALTH = auto()


@dataclass(slots=True)
class FetchResult:
    """Unified fetcher output, decoupled from concrete fetch strategy."""

    html: str
    url: str
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    fetcher_type: FetcherType = FetcherType.HTTP
    raw_body: bytes | None = None

    @property
    def has_content(self) -> bool:
        """Whether HTML contains substantial content (not an empty JS shell)."""
        if not self.html or len(self.html.strip()) < 200:
            return False
        body_markers = ("<p", "<article", "<main", "<section", "<div class")
        return any(m in self.html.lower() for m in body_markers)

    @property
    def etag(self) -> str | None:
        """Extract ETag from headers for HTTP conditional requests."""
        return self.headers.get("etag") or self.headers.get("ETag")

    @property
    def last_modified(self) -> str | None:
        """Extract Last-Modified from headers for HTTP conditional requests."""
        return self.headers.get("last-modified") or self.headers.get("Last-Modified")


@runtime_checkable
class Fetcher(Protocol):
    """Pluggable fetcher strategy interface."""

    fetcher_type: FetcherType

    async def fetch(self, url: str) -> FetchResult | None: ...

    async def shutdown(self) -> None: ...
