"""Data types for local browser data search results.


[INPUT]

[OUTPUT]
- BookmarkResult: Bookmark search result
- HistoryResult: History search result
- BrowserProfile: Browser profile info
- ChromiumBrowser: Discovered Chromium browserinformation
- SearchSource: Search data source enum
- SortOrder: Sort order enum

[POS]
Data type definitions for local browser data search. Pure data structures, no business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SearchSource(Enum):
    """Search data source."""

    BOOKMARKS = "bookmarks"
    HISTORY = "history"
    BOTH = "both"


class SortOrder(Enum):
    """History search sort order."""

    RECENT = "recent"
    VISITS = "visits"


@dataclass(frozen=True, slots=True)
class ChromiumBrowser:
    """Discovered Chromium-based browser."""

    name: str
    data_dir: str


@dataclass(frozen=True, slots=True)
class BrowserProfile:
    """Browser profile metadata."""

    directory: str
    display_name: str
    browser_name: str


@dataclass(frozen=True, slots=True)
class BookmarkResult:
    """A single bookmark search result."""

    title: str
    url: str
    folder_path: str
    profile: str
    browser: str

    def format(self) -> str:
        """Format for Agent output."""
        parts = [self.title or "(untitled)", self.url]
        if self.folder_path:
            parts.append(f"folder: {self.folder_path}")
        if self.profile != "Default":
            parts.append(f"@{self.profile}")
        if self.browser != "Chrome":
            parts.append(f"[{self.browser}]")
        return " | ".join(parts)


@dataclass(frozen=True, slots=True)
class HistoryResult:
    """A single history search result."""

    title: str
    url: str
    last_visit: datetime
    visit_count: int
    profile: str
    browser: str

    def format(self) -> str:
        """Format for Agent output."""
        parts = [
            self.title or "(untitled)",
            self.url,
            self.last_visit.strftime("%Y-%m-%d %H:%M"),
        ]
        if self.visit_count > 1:
            parts.append(f"visits={self.visit_count}")
        if self.profile != "Default":
            parts.append(f"@{self.profile}")
        if self.browser != "Chrome":
            parts.append(f"[{self.browser}]")
        return " | ".join(parts)


@dataclass(slots=True)
class SearchResults:
    """Aggregated search results."""

    bookmarks: list[BookmarkResult] = field(default_factory=list)
    history: list[HistoryResult] = field(default_factory=list)

    def format(self) -> str:
        """Format all results for Agent output."""
        sections: list[str] = []
        if self.bookmarks:
            lines = [f"[Bookmarks] {len(self.bookmarks)} results"]
            lines.extend(f"  {b.format()}" for b in self.bookmarks)
            sections.append("\n".join(lines))
        if self.history:
            lines = [f"[History] {len(self.history)} results"]
            lines.extend(f"  {h.format()}" for h in self.history)
            sections.append("\n".join(lines))
        if not sections:
            return "No results found."
        return "\n\n".join(sections)
