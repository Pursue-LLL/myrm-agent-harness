"""Raw publication gate request/result types.

[POS]
See module docstring.
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
