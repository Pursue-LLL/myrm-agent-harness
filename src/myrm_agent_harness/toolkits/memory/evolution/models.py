"""Data models for Order-Invariant Memory Evolution and Decay Engine."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class RuleStatus(StrEnum):
    """Lifecycle status of an evolving memory rule."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    DECAYED = "decayed"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class ArbitrationAction(StrEnum):
    """Outcome of conflict arbitration between competing rules."""

    UPHOLD_OLD = "uphold_old"
    REPLACE_WITH_NEW = "replace_with_new"
    QUARANTINE_BOTH = "quarantine_both"
    MERGE = "merge"


class EvidenceContext(BaseModel):
    """A contextual evidence unit supporting a candidate rule."""

    context_id: str = Field(description="Unique identifier for the evidence context")
    description: str = Field(description="Human-readable context narrative")
    facts: list[str] = Field(default_factory=list, description="Extracted factual premises")
    temporal_index: int = Field(default=0, description="Original sequential appearance index")


class EvolvingMemoryRule(BaseModel):
    """An evolving rule derived from agent interaction contexts."""

    rule_id: str = Field(description="Unique rule identifier")
    statement: str = Field(description="The core normative or factual memory rule statement")
    domain: str = Field(default="general", description="Domain classification (e.g., coding, identity)")
    evidence_contexts: list[EvidenceContext] = Field(
        default_factory=list,
        description="Evidence contexts validating this rule",
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Base confidence level")
    half_life_days: float = Field(default=14.0, gt=0.0, description="Time half-life in days")
    created_at: datetime = Field(description="Timestamp when rule was initially hypothesized")
    updated_at: datetime = Field(description="Timestamp when rule was last reinforced or edited")
    last_accessed_at: datetime = Field(description="Timestamp of last access or retrieval")
    access_count: int = Field(default=0, ge=0, description="Total retrieval hits")
    reinforcement_count: int = Field(default=0, ge=0, description="Count of positive cross-session re-confirmations")
    status: RuleStatus = Field(default=RuleStatus.CANDIDATE, description="Current lifecycle status")
    invariance_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Order invariance evaluation score")
    metadata: dict[str, str] = Field(default_factory=dict, description="Arbitrary string metadata attributes")


class PermutationEvaluationResult(BaseModel):
    """Evaluation result of order-invariance permutation testing."""

    rule_id: str = Field(description="Target candidate rule identifier")
    invariance_score: float = Field(ge=0.0, le=1.0, description="Permutation consistency score")
    permutations_tested: int = Field(ge=1, description="Number of permutation orderings tested")
    passed_gate: bool = Field(description="Whether the candidate passed the gate threshold")
    threshold: float = Field(description="Minimum invariance threshold required")
    divergence_reasons: list[str] = Field(default_factory=list, description="Reasons for order divergence failure")


class ConflictArbitrationReport(BaseModel):
    """Report detailing arbitration when two rules express incompatible facts."""

    conflict_detected: bool = Field(description="Whether semantic or logical conflict was identified")
    old_rule_id: str | None = Field(default=None, description="Identifier of the pre-existing rule")
    new_rule_id: str | None = Field(default=None, description="Identifier of the candidate competing rule")
    action: ArbitrationAction = Field(description="Action decided by arbitration governor")
    rationale: str = Field(description="Explanation for the arbitration verdict")
    resolved_rule: EvolvingMemoryRule | None = Field(default=None, description="Winning or merged rule if resolved")


class MemorySnapshot(BaseModel):
    """Point-in-time immutable snapshot of active and evolving memory rules."""

    snapshot_id: str = Field(description="Unique snapshot identifier")
    parent_snapshot_id: str | None = Field(default=None, description="Direct predecessor snapshot identifier")
    commit_message: str = Field(description="User or system rationale for snapshot creation")
    created_at: datetime = Field(description="Timestamp when snapshot was sealed")
    rules: list[EvolvingMemoryRule] = Field(default_factory=list, description="Captured rule catalog")
    rule_checksum: str = Field(default="", description="Cryptographic SHA-256 digest of catalog state")
