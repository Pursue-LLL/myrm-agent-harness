"""Data models for Grounded Dreaming, Provenance Anchors, and Surgical Memory Unlearning.

[POS]
做梦认知日记与溯源数据契约核心。定义跨会话认知洞察实体、审核与锁定状态枚举、
不可篡改的双向溯源锚点集，以及外科手术式遗忘审计报告。

[INPUT]
- cognitive_statement: 提炼出的长程认知事实
- source_session_ids: 关联来源会话列表
- provenance_anchors: 双向溯源锚点集合
- project_id: 可选的项目隔离范围

[OUTPUT]
- DreamDiaryStatus: 认知日记审核与治理状态枚举
- DreamDiaryEntry: 具备消息级溯源与可撤回锁定的梦境日记条目实体
- DreamSessionFragment: 单会话提取碎片契约
- SurgicalUnlearnReport: 外科手术式拔除审计报告
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    MemoryProvenanceAnchor,
)


class DreamDiaryStatus(StrEnum):
    """Lifecycle status of an AI cognitive insight in the dream diary."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    LOCKED = "locked"
    REVOKED = "revoked"


@dataclass(frozen=True)
class DreamSessionFragment:
    """A fragment of memories and context extracted from a single chat session."""

    session_id: str
    memories: list[dict[str, object]] = field(default_factory=list)
    topic_keywords: list[str] = field(default_factory=list)
    chat_turn_count: int = 0
    extracted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    project_id: str | None = None


@dataclass
class DreamDiaryEntry:
    """An evolved cognitive insight distilled from across multiple sessions."""

    entry_id: str
    cognitive_statement: str
    source_session_ids: list[str]
    evidence_snippets: list[str]
    confidence_delta: float
    status: DreamDiaryStatus = DreamDiaryStatus.PENDING
    rejection_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    provenance_anchors: list[MemoryProvenanceAnchor] = field(default_factory=list)
    project_id: str | None = None
    is_locked: bool = False
    amended_statement: str | None = None

    @classmethod
    def create(
        cls,
        cognitive_statement: str,
        source_session_ids: list[str],
        evidence_snippets: list[str],
        confidence_delta: float = 0.2,
        provenance_anchors: list[MemoryProvenanceAnchor] | None = None,
        project_id: str | None = None,
    ) -> DreamDiaryEntry:
        """Factory method generating a unique entry identifier."""
        return cls(
            entry_id=f"dream_{uuid.uuid4().hex[:12]}",
            cognitive_statement=cognitive_statement,
            source_session_ids=list(source_session_ids),
            evidence_snippets=list(evidence_snippets),
            confidence_delta=confidence_delta,
            status=DreamDiaryStatus.PENDING,
            provenance_anchors=list(provenance_anchors) if provenance_anchors else [],
            project_id=project_id,
            is_locked=False,
            amended_statement=None,
        )

    def to_dict(self) -> dict[str, object]:
        """Convert entry into serializable dictionary representation."""
        return {
            "entry_id": self.entry_id,
            "cognitive_statement": self.cognitive_statement,
            "source_session_ids": self.source_session_ids,
            "evidence_snippets": self.evidence_snippets,
            "confidence_delta": self.confidence_delta,
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat(),
            "provenance_anchors": [a.to_dict() for a in self.provenance_anchors],
            "project_id": self.project_id,
            "is_locked": self.is_locked,
            "amended_statement": self.amended_statement,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DreamDiaryEntry:
        """Construct entry from dictionary representation."""
        created_val = data.get("created_at")
        created_dt = (
            datetime.fromisoformat(str(created_val))
            if created_val
            else datetime.now(UTC)
        )
        status_val = str(data.get("status", "pending"))
        status_enum = (
            DreamDiaryStatus(status_val)
            if status_val in DreamDiaryStatus._value2member_map_
            else DreamDiaryStatus.PENDING
        )

        raw_sessions = data.get("source_session_ids")
        sessions = [str(s) for s in raw_sessions] if isinstance(raw_sessions, list) else []

        raw_evidences = data.get("evidence_snippets")
        evidences = [str(e) for e in raw_evidences] if isinstance(raw_evidences, list) else []

        rejection = data.get("rejection_reason")
        rejection_str = str(rejection) if rejection is not None else None

        raw_anchors = data.get("provenance_anchors")
        anchors: list[MemoryProvenanceAnchor] = []
        if isinstance(raw_anchors, list):
            for item in raw_anchors:
                if isinstance(item, dict):
                    anchors.append(MemoryProvenanceAnchor.from_dict(item))

        raw_proj = data.get("project_id")
        proj_str = str(raw_proj) if raw_proj is not None else None

        raw_amended = data.get("amended_statement")
        amended_str = str(raw_amended) if raw_amended is not None else None

        return cls(
            entry_id=str(data.get("entry_id", f"dream_{uuid.uuid4().hex[:12]}")),
            cognitive_statement=str(data.get("cognitive_statement", "")),
            source_session_ids=sessions,
            evidence_snippets=evidences,
            confidence_delta=float(data.get("confidence_delta", 0.2)),  # type: ignore[arg-type]
            status=status_enum,
            rejection_reason=rejection_str,
            created_at=created_dt,
            provenance_anchors=anchors,
            project_id=proj_str,
            is_locked=bool(data.get("is_locked", False)),
            amended_statement=amended_str,
        )


@dataclass(frozen=True)
class SurgicalUnlearnReport:
    """Audit report for surgical session memory erasure."""

    session_id: str
    unlearned_memory_ids: list[str]
    purged_vector_count: int
    status: str
    preserved_chat_turns: int
    execution_time_ms: float

    def to_dict(self) -> dict[str, object]:
        """Convert report to serializable dictionary representation."""
        return {
            "session_id": self.session_id,
            "unlearned_memory_ids": self.unlearned_memory_ids,
            "purged_vector_count": self.purged_vector_count,
            "status": self.status,
            "preserved_chat_turns": self.preserved_chat_turns,
            "execution_time_ms": self.execution_time_ms,
        }


class PruningDecisionKind(StrEnum):
    """Classification of memory pruning actions during dreaming consolidation."""

    REDUNDANT_ABSORBED = "redundant_absorbed"
    CONTRADICTION_SUPERSEDED = "contradiction_superseded"
    STALE_DECAYED = "stale_decayed"
    PRESERVED = "preserved"


@dataclass(frozen=True)
class PrunedMemoryRecord:
    """Detailed record of a memory pruned or superseded during autonomous dreaming."""

    memory_id: str
    decision: PruningDecisionKind
    reason: str
    superseded_by_statement: str | None = None
    pruned_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "decision": self.decision.value,
            "reason": self.reason,
            "superseded_by_statement": self.superseded_by_statement,
            "pruned_at": self.pruned_at.isoformat(),
        }


@dataclass(frozen=True)
class DreamingSynthesisReport:
    """Consolidated report produced by an autonomous Dreaming & Pruning execution."""

    run_id: str
    timestamp: datetime
    duration_ms: float
    candidate_count: int
    synthesized_insights: list[DreamDiaryEntry]
    pruned_records: list[PrunedMemoryRecord]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "synthesized_count": len(self.synthesized_insights),
            "pruned_count": len(self.pruned_records),
            "synthesized_insights": [e.to_dict() for e in self.synthesized_insights],
            "pruned_records": [p.to_dict() for p in self.pruned_records],
        }
