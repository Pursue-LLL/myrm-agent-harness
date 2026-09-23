"""Session debug bundle types.

[INPUT]
- Standard library dataclasses, enum, typing

[OUTPUT]
- BundleSection: named redacted evidence section
- DebugBundle: assembled session dossier with integrity fingerprint
- RerunComparison: single-variable rerun verdict
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BundleCompleteness(StrEnum):
    """Whether the bundle carries every required section."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class RerunVerdict(StrEnum):
    """Single-variable rerun outcome."""

    UNCHANGED = "unchanged"
    ALTERED = "altered"


@dataclass(slots=True)
class BundleSection:
    """One named evidence section (already redacted)."""

    name: str
    payload: dict[str, Any]
    truncated: bool = False


@dataclass(slots=True)
class DebugBundle:
    """Assembled session debug dossier."""

    session_id: str
    agent_id: str
    created_at: str
    completeness: BundleCompleteness
    missing_sections: list[str] = field(default_factory=list)
    sections: list[BundleSection] = field(default_factory=list)
    fingerprint: str = ""


@dataclass(slots=True)
class RerunComparison:
    """Baseline vs single-variable rerun verdict."""

    session_id: str
    varied_key: str
    baseline_digest: str
    rerun_digest: str
    verdict: RerunVerdict
    detail: str = ""


def utc_now_iso() -> str:
    """Current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()
