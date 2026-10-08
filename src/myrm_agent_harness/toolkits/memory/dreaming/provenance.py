"""Auditable memory provenance anchors, sensitive redlines, and scope isolation.

[POS]
记忆溯源与安全治理核心组件。为认知事实提供不可篡改的消息级双向溯源锚点、
阻断敏感凭据进入长期记忆的红线拦截器，以及杜绝跨项目上下文污染的作用域隔离门禁。

[INPUT]
- session_id: 会话唯一标识符
- message_id: 消息唯一标识符
- verbatim_quote: 原始行级原话引用
- project_id: 项目作用域标识符

[OUTPUT]
- MemoryProvenanceAnchor: 强类型双向溯源锚点实体
- SensitiveProvenanceGuard: 敏感凭据与隐私数据红线拦截器
- ProjectScopeIsolationGuard: 项目技术事实与个人偏好物理隔离门禁
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

# 正则匹配常见的 API Key、Bearer Token、私钥与敏感模式
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(?:api[_-]?key|apikey|secret[_-]?key)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?"),
    re.compile(r"(?i)(?:bearer\s+[a-zA-Z0-9_\-\.]{20,})"),
    re.compile(r"(?i)(?:password|passwd|pwd)\s*(?:[:=]|\bis\b)\s*['\"]?([^\s'\"]{6,})['\"]?"),
    re.compile(r"(?i)[a-z0-9_]+://[^:\s]+:[^@\s]+@"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36}"),
    re.compile(r"(?i)sk-[a-zA-Z0-9]{20,48}"),
)


@dataclass(frozen=True)
class MemoryProvenanceAnchor:
    """Immutable two-way citation anchor linking memory insight to raw source message."""

    session_id: str
    message_id: str
    speaker: str
    timestamp: datetime
    verbatim_quote: str
    char_span: tuple[int, int] = (0, 0)
    project_id: str | None = None
    is_personal_profile: bool = False
    hash_digest: str = field(default="")

    def __post_init__(self) -> None:
        """Compute SHA256 digest over provenance tuple to ensure immutability."""
        if not self.hash_digest:
            content_repr = f"{self.session_id}:{self.message_id}:{self.verbatim_quote}:{self.timestamp.isoformat()}"
            computed = hashlib.sha256(content_repr.encode("utf-8")).hexdigest()[:16]
            object.__setattr__(self, "hash_digest", computed)

    def to_dict(self) -> dict[str, object]:
        """Convert anchor to dictionary representation."""
        return {
            "session_id": self.session_id,
            "message_id": self.message_id,
            "speaker": self.speaker,
            "timestamp": self.timestamp.isoformat(),
            "verbatim_quote": self.verbatim_quote,
            "char_span": list(self.char_span),
            "project_id": self.project_id,
            "is_personal_profile": self.is_personal_profile,
            "hash_digest": self.hash_digest,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MemoryProvenanceAnchor:
        """Construct anchor from dictionary representation."""
        ts_val = data.get("timestamp")
        ts_dt = datetime.fromisoformat(str(ts_val)) if ts_val else datetime.now(UTC)

        raw_span = data.get("char_span")
        span_tuple: tuple[int, int] = (0, 0)
        if isinstance(raw_span, list | tuple) and len(raw_span) >= 2:
            span_tuple = (int(raw_span[0]), int(raw_span[1]))

        raw_proj = data.get("project_id")
        proj_str = str(raw_proj) if raw_proj is not None else None

        return cls(
            session_id=str(data.get("session_id", "")),
            message_id=str(data.get("message_id", "")),
            speaker=str(data.get("speaker", "user")),
            timestamp=ts_dt,
            verbatim_quote=str(data.get("verbatim_quote", "")),
            char_span=span_tuple,
            project_id=proj_str,
            is_personal_profile=bool(data.get("is_personal_profile", False)),
            hash_digest=str(data.get("hash_digest", "")),
        )


class SensitiveProvenanceGuard:
    """Scans and blocks sensitive credentials or private secrets from long-term memory."""

    @classmethod
    def contains_sensitive_content(cls, text: str) -> bool:
        """Return True if text matches any sensitive credential pattern."""
        if not text:
            return False
        return any(pattern.search(text) for pattern in _SENSITIVE_PATTERNS)

    @classmethod
    def sanitize_or_reject(cls, text: str) -> str | None:
        """Reject content entirely if critical secret is present; return cleaned text otherwise."""
        if cls.contains_sensitive_content(text):
            return None
        return text.strip()


class ProjectScopeIsolationGuard:
    """Enforces strict isolation between global user profile and project-specific facts."""

    @classmethod
    def validate_scope(
        cls,
        candidate_project_id: str | None,
        target_project_id: str | None,
        is_personal_profile: bool = False,
    ) -> bool:
        """Determine whether candidate memory is permitted into target project context.

        Personal profile items are globally visible across projects.
        Project-specific facts are strictly constrained to matching target_project_id.
        """
        if is_personal_profile:
            return True
        if target_project_id is None:
            return True
        return candidate_project_id == target_project_id

    @classmethod
    def filter_cross_project_fragments(
        cls,
        anchors: list[MemoryProvenanceAnchor],
        target_project_id: str | None,
    ) -> list[MemoryProvenanceAnchor]:
        """Filter out provenance anchors belonging to foreign projects."""
        return [
            a for a in anchors
            if cls.validate_scope(a.project_id, target_project_id, a.is_personal_profile)
        ]
