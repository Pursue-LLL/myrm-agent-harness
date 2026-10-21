"""Evidence tree data models and typed containers for ReTree working memory.

[INPUT]
- pydantic::BaseModel (POS: 数据验证与强类型 DTO 基础模型)
- enum::Enum (POS: 状态枚举类)

[OUTPUT]
- EvidenceNodeStatus: 证据节点生命周期状态枚举
- ConflictType: 语义冲突与时态演化分类枚举
- EvidenceSource: 溯源信息容器（URL、Snippet、SHA-256指纹）
- BoundedSummary: 严格有界摘要与核心实体指标容器
- RevisionRecord: 回溯修复与版本审计日志
- EvidenceNode: 强类型树状工作记忆原子节点
- ConflictVerdict: 矛盾初筛与仲裁裁决结果
- TreeRepairResult: 回溯修复与分支剪枝结果容器

[POS]
ReTree 树状工作记忆数据契约层。定义有界摘要、因果依赖、冲突裁决与版本审计模型，严禁 Any。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceNodeStatus(StrEnum):
    """Lifecycle status of an evidence node in the working tree."""

    ACTIVE = "active"
    PRUNED_INVALIDATED = "pruned_invalidated"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"


class ConflictType(StrEnum):
    """Classification of semantic difference between new and existing evidence."""

    NONE = "none"
    CONTRADICTION = "contradiction"
    TEMPORAL_UPDATE = "temporal_update"
    COMPLEMENTARY = "complementary"


class EvidenceSource(BaseModel):
    """Source provenance information for an evidence node."""

    url: str = Field(default="", description="Original source URL or document path")
    title: str = Field(default="", description="Title of the source page or document")
    snippet: str = Field(default="", description="Raw evidence excerpt")
    doc_id: str | None = Field(default=None, description="External document or Wiki ID")
    published_at: str | None = Field(default=None, description="Publication timestamp if available")
    content_hash: str = Field(default="", description="SHA-256 fingerprint of the raw excerpt")


class BoundedSummary(BaseModel):
    """Strictly bounded conclusion with essential attributes for low-bandwidth prompt injection."""

    summary: str = Field(..., description="Dense conclusion restricted to bounded token bandwidth")
    key_entities: list[str] = Field(default_factory=list, description="Core entities involved in the claim")
    key_metrics: dict[str, str] = Field(default_factory=dict, description="Numeric metrics, dates, or specs")
    estimated_tokens: int = Field(default=0, description="Estimated token count of the summary")


class RevisionRecord(BaseModel):
    """Immutable log of a node modification event during backtracking repair."""

    revision_id: str = Field(..., description="Unique revision transaction ID")
    previous_summary: str = Field(..., description="Summary text prior to revision")
    reason: str = Field(..., description="Trigger reason (contradiction, update, or user edit)")
    superseded_by_url: str | None = Field(default=None, description="URL of the newer overriding evidence")
    revised_at: str = Field(..., description="ISO 8601 timestamp of this revision")


class EvidenceNode(BaseModel):
    """Atomic tree-structured working memory unit with explicit provenance and dependencies."""

    node_id: str = Field(..., description="Unique node identifier (e.g., ev_node_01)")
    claim: str = Field(..., description="Core hypothesis or search query goal this node resolves")
    bounded_summary: BoundedSummary = Field(..., description="Bounded summary exposed to orchestrator")
    source: EvidenceSource = Field(default_factory=EvidenceSource, description="Source provenance details")
    dependencies: list[str] = Field(
        default_factory=list,
        description="IDs of prerequisite nodes this node's inference depends on (Dep(Node))",
    )
    dependents: list[str] = Field(
        default_factory=list,
        description="IDs of downstream nodes that depend on this node's conclusion",
    )
    revision_depth: int = Field(default=0, description="Number of revisions applied to this node")
    status: EvidenceNodeStatus = Field(default=EvidenceNodeStatus.ACTIVE, description="Current lifecycle state")
    revisions: list[RevisionRecord] = Field(default_factory=list, description="Audit trail of historical revisions")
    created_at: str = Field(..., description="Creation ISO 8601 timestamp")
    updated_at: str = Field(..., description="Last modification ISO 8601 timestamp")


class ConflictVerdict(BaseModel):
    """Evaluation verdict emitted by the contradiction detector."""

    conflict_type: ConflictType = Field(..., description="Identified semantic relation")
    conflicting_node_id: str | None = Field(default=None, description="Existing node ID in conflict")
    reason: str = Field(default="", description="Detailed explanation of the contradiction or update")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score of the verdict")


class TreeRepairResult(BaseModel):
    """Outcome report from a backtracking repair operation."""

    target_node_id: str = Field(..., description="Node where the overriding evidence was applied")
    pruned_node_ids: list[str] = Field(default_factory=list, description="Downstream nodes marked invalid")
    is_disputed: bool = Field(default=False, description="True if oscillation guard forced a disputed resolution")
    resolution_summary: str = Field(..., description="Human-readable summary of the repair outcome")
