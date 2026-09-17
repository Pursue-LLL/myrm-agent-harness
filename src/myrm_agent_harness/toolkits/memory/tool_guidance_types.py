"""Data models and contracts for Tool Guidance Evolution.

Provides structured types for tool-level procedural experience,
including confidence rating, platform/environment isolation, and
pinned status for user-in-the-loop governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ToolGuidanceItem:
    """A distilled behavioral or avoidance guideline for a specific tool.

    Zero-LLM distillation or self-healing traps produce these records.
    They are scoped by tool_name and optionally by env_fingerprint.
    """

    id: str
    tool_name: str
    rule_text: str
    trigger_pattern: str
    confidence: float = 1.0
    is_pinned: bool = False
    env_fingerprint: str | None = None
    agent_id: str | None = None
    source: Literal["self_healing", "edict", "manual"] = "self_healing"
    hit_count: int = 1
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, str | float | bool | int | None]:
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "rule_text": self.rule_text,
            "trigger_pattern": self.trigger_pattern,
            "confidence": self.confidence,
            "is_pinned": self.is_pinned,
            "env_fingerprint": self.env_fingerprint,
            "agent_id": self.agent_id,
            "source": self.source,
            "hit_count": self.hit_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ToolGuidanceSummary:
    """Aggregated golden guidance set for a single tool."""

    tool_name: str
    guidelines: list[str]
    has_pinned: bool = False
    total_active_rules: int = 0
