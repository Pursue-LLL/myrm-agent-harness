"""Raw publication gate request/result types.

[INPUT]
- dataclasses::dataclass, field (POS: standard library dataclass definition)
- enum::StrEnum (POS: standard library string enum)
- typing::Literal (POS: standard library literal type)

[OUTPUT]
- RawConflictPolicy, RawGateCaller, RawPublishRequest, RawPublishResult

[POS]
Raw Gate 原始材料发布门禁的数据契约与冲突策略枚举定义。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal


class RawConflictPolicy(StrEnum):
    """How to handle an existing raw file with different content."""

    FAIL = "fail"
    SKIP = "skip"
    PUT_IF_ABSENT = "put_if_absent"
    SUPERSEDE = "supersede"


RawGateCaller = Literal["agent", "settings", "chat", "extension"]


@dataclass(frozen=True, slots=True)
class RawPublishRequest:
    relative_path: str
    content: str
    conflict_policy: RawConflictPolicy = RawConflictPolicy.FAIL
    supersede_reason: str = ""
    replace_source_url: str | None = None
    # Structured provenance merged into the raw file frontmatter on write
    # (e.g. source_chat for turn archives). Never used as free-text body content.
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawPublishResult:
    relative_path: str
    absolute_path: Path
    content_hash: str
    written: bool
    skipped: bool
    superseded: bool
    created: bool
    conflict_skipped: bool = False
    security_verdict: str = ""
    security_redacted: bool = False
    security_blocked: bool = False
