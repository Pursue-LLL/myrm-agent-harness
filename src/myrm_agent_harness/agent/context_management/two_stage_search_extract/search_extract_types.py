# [INPUT] None (Foundational domain types for two-stage search triage and selective deep extract)
# [OUTPUT] RankedSnippetItem, SnippetTriageResult, DeepExtractResult, FetchBudgetStatus, TwoStageSearchConfig, SearchExtractError, FetchBudgetExceededError
# [POS] Domain data structures, config parameters, and error taxonomy for 2-stage search and context protection

"""Domain types and configuration for two-stage ranked snippet and selective deep extract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

_DEFAULT_GUIDANCE_DIRECTIVE = (
    "METAGUIDANCE: The above snippets provide ranked high-level evidence. "
    "If these snippets are sufficient to answer the query accurately, synthesize your response directly. "
    "Only invoke 'web_fetch' on at most 1-2 critical URLs if deep technical code or exhaustive facts are required."
)


class SearchExtractError(Exception):
    """Base error for two-stage search and selective deep extract subsystem."""


class FetchBudgetExceededError(SearchExtractError):
    """Raised when deep web fetching exceeds per-turn concurrency or accumulated budget ceiling."""


@dataclass(frozen=True)
class RankedSnippetItem:
    """A lightweight search result entry strictly capped in character and token budget."""

    index: int
    title: str
    url: str
    domain: str
    snippet: str
    relevance_score: float = 0.0
    estimated_tokens: int = 0


@dataclass(frozen=True)
class SnippetTriageResult:
    """Outcome of Stage 1 ranked snippet triage within strict token boundaries."""

    query: str
    items: list[RankedSnippetItem]
    total_estimated_tokens: int
    guidance_directive: str = _DEFAULT_GUIDANCE_DIRECTIVE
    cached: bool = False
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class DeepExtractResult:
    """Outcome of Stage 2 selective deep web extraction and noise reduction."""

    url: str
    title: str
    cleaned_markdown: str
    original_char_len: int
    cleaned_char_len: int
    compression_ratio: float
    fetch_turn: int = 1
    cached: bool = False
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class FetchBudgetStatus:
    """Per-session governor status preventing runaway crawling and enforcing interim synthesis."""

    session_id: str
    current_turn_fetches: int
    max_fetches_per_turn: int
    accumulated_fetches: int
    max_accumulated_fetches: int
    budget_exceeded: bool
    requires_interim_synthesis: bool


@dataclass(frozen=True)
class TwoStageSearchConfig:
    """Configuration parameters for two-stage snippet triage and deep fetch governor."""

    max_snippet_tokens_budget: int = 500
    snippet_char_limit: int = 120
    max_concurrent_fetches_per_turn: int = 2
    max_accumulated_fetches_per_session: int = 6
    interim_synthesis_threshold: int = 3
    cache_ttl_seconds: int = 1800
    default_guidance_directive: str = _DEFAULT_GUIDANCE_DIRECTIVE
