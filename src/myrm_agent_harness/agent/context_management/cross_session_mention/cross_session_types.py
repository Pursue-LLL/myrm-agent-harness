# [INPUT]: None
# [OUTPUT]: CrossSessionConfig, MentionInjectionResult, SessionMentionTag, SessionRecord, SessionSnapshot
# [POS]: agent/context_management/cross_session_mention/cross_session_types.py

"""Domain models and contracts for cross-session @ mention references and snapshot injection.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- CrossSessionConfig: Configuration parameters for mention parsing, token caps, and snapshot limits.
- SessionRecord: Descriptor of a stored historical session, including summary and recent history.
- SessionMentionTag: Parsed @Session mention reference found in user prompts.
- SessionSnapshot: Read-only distilled state snapshot of an archived session.
- MentionInjectionResult: Container holding enriched user prompt, attached snapshots, and proof badges.

[POS]
Domain layer establishing DeepSeek Harness inspired cross-session context referencing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CrossSessionConfig:
    """Thresholds and limits governing cross-session mention extraction."""

    max_referenced_sessions: int = 3
    max_snapshot_tokens_per_session: int = 1500
    fallback_recent_turns: int = 3
    mention_prefix: str = "@Session:"


@dataclass(frozen=True)
class SessionRecord:
    """Historical session entry containing metadata, summary, and recent turn logs."""

    session_id: str
    title: str
    created_at: float
    compacted_summary: str | None = None
    recent_messages: Sequence[Mapping[str, str]] = field(default_factory=list)
    artifacts: Sequence[str] = field(default_factory=list)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionMentionTag:
    """Parsed reference to a historical session detected within prompt text."""

    raw_match: str
    identifier: str
    start_pos: int
    end_pos: int
    matched_session_id: str | None = None
    is_resolved: bool = False


@dataclass(frozen=True)
class SessionSnapshot:
    """Immutable, read-only distilled representation of a referenced session."""

    session_id: str
    title: str
    summary_content: str
    key_artifacts: Sequence[str]
    is_read_only: bool = True
    token_estimate: int = 0
    reference_badge: str = ""


@dataclass(frozen=True)
class MentionInjectionResult:
    """Final outcome of parsing and injecting referenced session snapshots."""

    original_user_prompt: str
    expanded_prompt: str
    referenced_snapshots: Sequence[SessionSnapshot]
    proof_badges: Sequence[str]
    total_injected_tokens: int
