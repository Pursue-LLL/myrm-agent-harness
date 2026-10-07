# ============================================================================
# Shared Cloud Session & Collaborative Workspace Types (Item 153)
# Strict typed contracts for shareable session snapshots, access tokens,
# collaborative inline annotations, and mid-flight steering directives.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ShareAccessLevel(StrEnum):
    """Permission levels for shared cloud session links."""

    READ_ONLY = "read_only"
    COMMENT_ONLY = "comment_only"
    INTERACTIVE_STEERING = "interactive_steering"


@dataclass(slots=True, frozen=True)
class SharedSessionToken:
    """Cryptographically signed share token governing external participant access."""

    token_id: str
    session_id: str
    access_level: ShareAccessLevel
    expires_at: float
    created_by: str
    secret_hash: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self, current_time: float | None = None) -> bool:
        """Evaluates whether the token has expired."""
        now = current_time if current_time is not None else time.time()
        return now >= self.expires_at

    def to_dict(self) -> dict[str, str | float]:
        """Serializes token contract to dictionary."""
        return {
            "token_id": self.token_id,
            "session_id": self.session_id,
            "access_level": str(self.access_level),
            "expires_at": self.expires_at,
            "created_by": self.created_by,
            "secret_hash": self.secret_hash,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SanitizedMessage:
    """Safe, sanitized transcript message free of credentials and private host paths."""

    message_id: str
    role: str  # "user", "assistant", "system", "tool"
    content: str
    thought_trace: str = ""
    timestamp: float = field(default_factory=time.time)
    was_redacted: bool = False

    def to_dict(self) -> dict[str, str | float | bool]:
        """Serializes message to dictionary."""
        return {
            "message_id": self.message_id,
            "role": self.role,
            "content": self.content,
            "thought_trace": self.thought_trace,
            "timestamp": self.timestamp,
            "was_redacted": self.was_redacted,
        }


@dataclass(slots=True)
class ArtifactInlineAnnotation:
    """Collaborative annotation pinned to specific artifact lines by team reviewers."""

    annotation_id: str
    artifact_id: str
    line_start: int
    line_end: int
    author: str
    comment_text: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float]:
        """Serializes annotation to dictionary."""
        return {
            "annotation_id": self.annotation_id,
            "artifact_id": self.artifact_id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "author": self.author,
            "comment_text": self.comment_text,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SteeringDirective:
    """Mid-flight steering input injected by authorized collaborative team members."""

    directive_id: str
    session_id: str
    author: str
    directive_text: str
    applied_to_context: bool = False
    injected_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | bool | float]:
        """Serializes steering directive to dictionary."""
        return {
            "directive_id": self.directive_id,
            "session_id": self.session_id,
            "author": self.author,
            "directive_text": self.directive_text,
            "applied_to_context": self.applied_to_context,
            "injected_at": self.injected_at,
        }


@dataclass(slots=True)
class SharedSessionSnapshot:
    """Publicly viewable or steerable sanitized session representation."""

    share_id: str
    session_id: str
    title: str
    access_level: ShareAccessLevel
    messages: list[SanitizedMessage] = field(default_factory=list)
    annotations: list[ArtifactInlineAnnotation] = field(default_factory=list)
    public_artifact_ids: list[str] = field(default_factory=list)
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float | list[str] | list[dict[str, object]]]:
        """Serializes snapshot to dictionary."""
        return {
            "share_id": self.share_id,
            "session_id": self.session_id,
            "title": self.title,
            "access_level": str(self.access_level),
            "messages": [m.to_dict() for m in self.messages],
            "annotations": [a.to_dict() for a in self.annotations],
            "public_artifact_ids": list(self.public_artifact_ids),
            "expires_at": self.expires_at,
            "created_at": self.created_at,
        }
