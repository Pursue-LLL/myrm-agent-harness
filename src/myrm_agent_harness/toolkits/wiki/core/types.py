"""Type definitions for Wiki toolkit.

[INPUT]
dataclasses::dataclass, field (POS: standard library dataclass definition)
datetime::datetime, UTC (POS: standard library datetime handling)
pathlib::Path (POS: standard library file path operations)

[OUTPUT]
ConceptInfo: concept information dataclass
WikiArticle: Wiki article dataclass
CompileResult: compilation result dataclass
QueryResult: query result dataclass
LintIssue: lint issue dataclass
LintResult: lint result dataclass
WikiMetadata: Wiki metadata class

[POS]
Wiki toolkit type definition center. Defines all core data models (concepts, articles,
compile results, query results, lint results, metadata), supporting type-safe data passing and serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ConceptInfo:
    """Extracted concept information."""

    name: str
    definition: str
    mentions: int = 1
    source_files: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WikiArticle:
    """Compiled wiki article."""

    concept_name: str
    content: str
    source_docs: list[str]
    related_concepts: list[str]
    backlinks: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Result of wiki compilation."""

    concepts_count: int
    articles_generated: int
    backlinks_created: int
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Result of wiki query."""

    question: str
    answer: str
    related_articles: list[str]
    should_archive: bool = False
    confidence_score: float = 0.0


@dataclass(frozen=True, slots=True)
class LintIssue:
    """Wiki quality issue."""

    issue_type: str  # "inconsistency" | "incomplete" | "broken_link"
    severity: str  # "low" | "medium" | "high"
    location: str  # File path or concept name
    description: str
    can_auto_fix: bool = False
    suggested_fix: str | None = None


@dataclass(frozen=True, slots=True)
class LintResult:
    """Result of wiki maintenance."""

    issues_found: int
    issues_fixed: int
    connections_discovered: int
    duration_ms: int = 0
    issues: list[LintIssue] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WikiMetadata:
    """Wiki metadata stored in .metadata.json."""

    last_compile_time: datetime
    total_concepts: int
    total_articles: int
    total_raw_files: int
    version: str = "1.0.0"
