"""Data Models for Unified Seven-Layer Memory Governance Engine.

[INPUT]
(none — leaf domain models, no internal module dependencies)

[OUTPUT]
FactStatus: 动态事实生命周期枚举 (ACTIVE, DEPRECATED, EXPIRED)
ReconciliationAction: 事实对账动作枚举 (ADD, UPDATE, DELETE, NOOP)
DynamicFactItem: 具有有效生命周期与置信度的事实模型
EventTimelineItem: 时序事件记录模型
ProfileSlots: 四象限画像槽位模型（支持原位覆写与确定性字典序序列化）
ReconciliationDecision: 对账裁决结果模型
AssembledMemoryContext: 四维组装记忆上下文容器

[POS]
记忆治理领域数据模型层。定义用户画像槽位、事件时间线、动态事实生命周期与上下文装配数据契约。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FactStatus(str, Enum):
    """Lifecycle status of dynamic facts."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPIRED = "expired"


class ReconciliationAction(str, Enum):
    """Four-state action for fact reconciliation."""

    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"


class DynamicFactItem(BaseModel):
    """Dynamic fact with validity lifecycle, confidence, and source tracking."""

    fact_id: str
    content: str
    status: FactStatus = FactStatus.ACTIVE
    category: str = "general"
    valid_until: datetime | None = None
    confidence: float = 1.0
    source_turn: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Check if the fact is expired based on valid_until."""
        if self.valid_until is None:
            return False
        now = current_time or datetime.now(timezone.utc)
        return now > self.valid_until


class EventTimelineItem(BaseModel):
    """Chronological event with timestamp, summary, and participant context."""

    event_id: str
    timestamp: datetime
    summary: str
    details: str = ""
    participants: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ProfileSlots(BaseModel):
    """Four-quadrant user profile slots with in-place mutation and deterministic serialization."""

    persona: dict[str, str] = Field(default_factory=dict)
    preferences: dict[str, str] = Field(default_factory=dict)
    constraints: dict[str, str] = Field(default_factory=dict)
    custom: dict[str, str] = Field(default_factory=dict)

    def update_slot(
        self,
        category: Literal["persona", "preferences", "constraints", "custom"],
        key: str,
        value: str,
    ) -> None:
        """In-place update or add a profile slot key-value pair."""
        target_dict: dict[str, str] = getattr(self, category)
        target_dict[key] = value

    def delete_slot(
        self,
        category: Literal["persona", "preferences", "constraints", "custom"],
        key: str,
    ) -> bool:
        """In-place remove a key from target profile category."""
        target_dict: dict[str, str] = getattr(self, category)
        if key in target_dict:
            del target_dict[key]
            return True
        return False

    def to_cached_prefix_text(self) -> str:
        """Serialize profile slots with strict lexicographical ordering.

        Ensures deterministic representation to maximize LLM Prompt Cache hits.
        """
        lines: list[str] = ["[User Profile & Constraints]"]
        categories: list[tuple[str, dict[str, str]]] = [
            ("Persona", self.persona),
            ("Preferences", self.preferences),
            ("Constraints", self.constraints),
            ("Custom", self.custom),
        ]

        for cat_title, mapping in categories:
            if not mapping:
                continue
            lines.append(f"- {cat_title}:")
            for key in sorted(mapping.keys()):
                lines.append(f"  * {key}: {mapping[key]}")

        if len(lines) == 1:
            return "[User Profile & Constraints]\n(Empty)"

        return "\n".join(lines)


class ReconciliationDecision(BaseModel):
    """Decision produced by the Fact Reconciliation Engine."""

    action: ReconciliationAction
    target_fact_id: str | None = None
    new_content: str | None = None
    reason: str = ""
    confidence: float = 1.0


class AssembledMemoryContext(BaseModel):
    """Combined context containing all 4 dimensions of memory."""

    cached_profile_prefix: str
    timeline_section: str
    dynamic_facts_section: str
    entity_graph_section: str
    total_estimated_tokens: int

    def full_context_text(self) -> str:
        """Combine all sections into a single coherent system memory prompt."""
        sections: list[str] = [self.cached_profile_prefix]
        if self.timeline_section.strip():
            sections.append(f"[Event Timeline]\n{self.timeline_section}")
        if self.dynamic_facts_section.strip():
            sections.append(f"[Dynamic Facts]\n{self.dynamic_facts_section}")
        if self.entity_graph_section.strip():
            sections.append(f"[Entity Relationships]\n{self.entity_graph_section}")
        return "\n\n".join(sections)
