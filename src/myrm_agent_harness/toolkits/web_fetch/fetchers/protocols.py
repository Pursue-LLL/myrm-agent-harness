"""Fetcher Protocol and Data模型

定义统一 抓取Interface and  in 间产物，使 not 同抓取Strategy可插拔。

[INPUT]
- (none)

[OUTPUT]
- FetcherType: class — Fetcher Type
- FetchResult: class — Fetch Result
- Fetcher: class — Fetcher

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
    """Fetcher 层 统一output， and Concrete抓取方式解耦"""

    html: str
    url: str
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    fetcher_type: FetcherType = FetcherType.HTTP
    raw_body: bytes | None = None

    @property
    def has_content(self) -> bool:
        """HTML WhetherContains实质Content（非 JS Empty壳）"""
        if not self.html or len(self.html.strip()) < 200:
            return False
        body_markers = ("<p", "<article", "<main", "<section", "<div class")
        return any(m in self.html.lower() for m in body_markers)

    @property
    def etag(self) -> str | None:
        """from  headers  in Extract ETag（ for  HTTP 条件Request）"""
        return self.headers.get("etag") or self.headers.get("ETag")

    @property
    def last_modified(self) -> str | None:
        """from  headers  in Extract Last-Modified（ for  HTTP 条件Request）"""
        return self.headers.get("last-modified") or self.headers.get("Last-Modified")


@runtime_checkable
class Fetcher(Protocol):
    """可插拔 抓取StrategyInterface"""

    fetcher_type: FetcherType

    async def fetch(self, url: str) -> FetchResult | None: ...

    async def shutdown(self) -> None: ...
