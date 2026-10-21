"""Types and data structures for Graph Engineering Diamond Topology & Blinded Adversarial Auditor.

[INPUT]
- dataclasses
- enum
- time

[OUTPUT]
- DiamondStage
- AuditorPerspective
- RealityAnchorType
- RealityAnchorSpec
- AdversarialReviewItem
- AdversarialVerdict
- DiamondNode
- CensusStatus

[POS]
Types and data structures for Graph Engineering Diamond Topology & Blinded Adversarial Auditor.

"""

from dataclasses import dataclass, field
from enum import Enum
import time


class DiamondStage(str, Enum):
    """3 stages of standard Diamond pattern."""

    FAN_OUT = "fan_out"
    REDUCE = "reduce"
    SYNTHESIZE = "synthesize"


class AuditorPerspective(str, Enum):
    """Three independent review perspectives for blinded adversarial cross-validation."""

    FACT_ACCURACY = "fact_accuracy"
    TIMELINESS = "timeliness"
    CITATION_AUTHORITY = "citation_authority"


class RealityAnchorType(str, Enum):
    """External objective reality signals that cannot be hallucinated or soft-degraded."""

    EXIT_CODE_ZERO = "exit_code_zero"
    HASH_MATCH = "hash_match"
    ROW_COUNT_MATCH = "row_count_match"


@dataclass
class RealityAnchorSpec:
    """Binding specification for objective external verification."""

    anchor_type: RealityAnchorType
    target_id: str
    expected_value: str
    actual_value: str | None = None
    verified: bool = False


@dataclass
class AdversarialReviewItem:
    """Individual review perspective output without CoT contamination."""

    perspective: AuditorPerspective
    auditor_id: str
    passed: bool
    score: float
    critique: str
    isolated_context_verified: bool = True
    timestamp: float = field(default_factory=time.time)


@dataclass
class AdversarialVerdict:
    """Consensus verdict from the blinded adversarial panel."""

    passed: bool
    total_reviews: int
    pass_count: int
    reviews: list[AdversarialReviewItem] = field(default_factory=list)
    anchor_checks: list[RealityAnchorSpec] = field(default_factory=list)
    consensus_summary: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class DiamondNode:
    """Node in the Diamond Topology DAG."""

    node_id: str
    title: str
    stage: DiamondStage
    depends_on: list[str] = field(default_factory=list)
    payload: dict[str, str] = field(default_factory=dict)
    output_artifact: str | None = None
    cot_reasoning_internal: str | None = None  # Strictly isolated, stripped for auditor
    is_pruned: bool = False
    status: str = "pending"  # pending, running, completed, failed
    created_at: float = field(default_factory=time.time)


@dataclass
class CensusStatus:
    """Census tracking for parallel fan-out dispatch to eliminate dead nodes."""

    dispatched_count: int
    received_count: int
    missing_nodes: list[str] = field(default_factory=list)
    is_healthy: bool = True
    retried_nodes: list[str] = field(default_factory=list)
