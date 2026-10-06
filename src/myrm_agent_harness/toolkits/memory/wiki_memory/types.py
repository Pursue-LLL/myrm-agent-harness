# [POS] toolkits/memory/wiki_memory/types.py
# [INPUT] None
# [OUTPUT] WikiScopeLevel, WikiMemoryPage, WikiLinkRef, WikiAuditCommit, WikiIndexRebuildResult, WikiSearchMatch

"""Type definitions and contracts for Markdown-as-SSOT Wiki Memory Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class WikiScopeLevel(StrEnum):
    """Scope tier governing memory wiki page visibility and physical storage layout."""

    GLOBAL = "global"  # Cross-agent shared memory, stored under memory_wiki/global/
    AGENT = "agent"  # Profile-scoped private memory, stored under memory_wiki/agents/{profile_id}/


@dataclass(frozen=True)
class WikiLinkRef:
    """An Obsidian-style bidirectional link reference parsed from Markdown [[Page]]."""

    source_page_id: str
    target_page_title: str
    link_text: str = ""
    section: str | None = None


@dataclass(frozen=True)
class WikiMemoryPage:
    """A standard Markdown memory page serving as the single source of truth."""

    page_id: str
    title: str
    content: str
    scope: WikiScopeLevel = WikiScopeLevel.GLOBAL
    profile_id: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[WikiLinkRef] = field(default_factory=list)
    frontmatter: dict[str, str | int | float | bool] = field(default_factory=dict)
    updated_at: float = 0.0


@dataclass(frozen=True)
class WikiAuditCommit:
    """A version control audit record produced by Git for memory modifications."""

    commit_hash: str
    message: str
    timestamp: float
    author: str
    files_changed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WikiIndexRebuildResult:
    """Audit payload detailing derived SQLite FTS5 index reconstruction."""

    rebuilt_pages: int
    rebuilt_links: int
    duration_ms: float
    status: str = "success"


@dataclass(frozen=True)
class WikiSearchMatch:
    """A search match result returned by derived SQLite FTS5 full-text queries."""

    page_id: str
    title: str
    snippet: str
    scope: WikiScopeLevel
    profile_id: str | None
    score: float
    tags: list[str] = field(default_factory=list)
