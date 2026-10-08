"""Type contracts and definitions for Sandbox Tool Output Interception and Local FTS5 Retrieval Suite.

Defines tool interception stubs, SQLite FTS5 snippet models, five-stage lifecycle hooks,
and interceptor configuration.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ContextHookStage: Five-stage lifecycle hooks for lossless context continuity (Context Mode aligned).
- InterceptedToolOutput: Archived raw tool execution output stored safely outside LLM context window.
- ToolOutputStub: Ultra-compact context stub injected into LLM context instead of raw multi-kilobyte bloat.
- SearchResultSnippet: Exact, uncompressed textual slice retrieved from local FTS5 database.
- LifecycleHookRecord: Immutable log entry recorded by the five-stage context lifecycle pipeline.
- SandboxInterceptorConfig: Configuration governing tool output interception, FTS5 storage, and retrieval
  limits.

[POS]
Type contracts and definitions for Sandbox Tool Output Interception and Local FTS5 Retrieval Suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import time


class ContextHookStage(StrEnum):
    """Five-stage lifecycle hooks for lossless context continuity (Context Mode aligned)."""

    PRE_TOOL_USE = "pre_tool_use"  # Parameters and pre-call context snapshot
    POST_TOOL_USE = "post_tool_use"  # Result interception and archiving
    USER_PROMPT_SUBMIT = "user_prompt_submit"  # Anchor new user intent and decisions
    PRE_COMPACT = "pre_compact"  # Freeze execution history before compaction
    SESSION_RESUME = "session_resume"  # Rehydrate working state upon restart/resume


@dataclass(frozen=True)
class InterceptedToolOutput:
    """Archived raw tool execution output stored safely outside LLM context window."""

    content_id: str
    tool_name: str
    session_id: str
    raw_size_bytes: int
    raw_text: str
    summary_digest: str
    line_count: int
    intercepted_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ToolOutputStub:
    """Ultra-compact context stub injected into LLM context instead of raw multi-kilobyte bloat."""

    content_id: str
    tool_name: str
    stub_text: str
    raw_size_bytes: int
    tokens_saved: int
    line_count: int


@dataclass(frozen=True)
class SearchResultSnippet:
    """Exact, uncompressed textual slice retrieved from local FTS5 database."""

    content_id: str
    line_number: int
    snippet: str
    match_score: float


@dataclass(frozen=True)
class LifecycleHookRecord:
    """Immutable log entry recorded by the five-stage context lifecycle pipeline."""

    stage: ContextHookStage
    session_id: str
    payload_digest: str
    metadata: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SandboxInterceptorConfig:
    """Configuration governing tool output interception, FTS5 storage, and retrieval limits."""

    interception_threshold_bytes: int = 1500  # Outputs larger than 1.5KB get intercepted
    sqlite_db_path: str = ":memory:"  # In-memory default for speed or disk path
    max_search_results: int = 5
    snippet_window_chars: int = 240
    bytes_per_token_estimate: float = 4.0
