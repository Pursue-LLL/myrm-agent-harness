from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ArmKind(StrEnum):
    """Categorical kind of retrieval arm."""

    VECTOR = "vector"
    BM25 = "bm25"
    GRAPH = "graph"
    CODE_AST = "code_ast"
    VOLUNTEER = "volunteer"


@dataclass(frozen=True, slots=True)
class ArmCandidate[T]:
    """Candidate item retrieved from a single retrieval arm."""

    item: T
    key: str
    score: float
    rank: int = 1


@dataclass(frozen=True, slots=True)
class RetrievalArm[T]:
    """A single retrieval source arm containing ranked candidate items."""

    name: str
    arm_kind: ArmKind
    candidates: list[ArmCandidate[T]]
    base_weight: float = 1.0
    is_volunteer: bool = False


@dataclass(frozen=True, slots=True)
class ArmTelemetryProfile:
    """Detailed signal-to-noise ratio and demotion telemetry per arm."""

    arm_name: str
    arm_kind: ArmKind
    raw_count: int
    peak_score: float
    mean_score: float
    sharpness_gap: float
    variance: float
    is_demoted: bool
    effective_weight: float
    contributed_items_count: int


@dataclass(frozen=True, slots=True)
class AdaptiveReturnConfig:
    """Control plane configuration for adaptive relaxed-arm fusion."""

    target_top_k: int = 5
    min_core_items: int = 3
    min_sharpness_gap: float = 0.15
    max_noise_variance: float = 0.05
    demotion_factor: float = 0.25
    volunteer_boost: float = 1.0
    rrf_k: int = 60
    normalize_target: float = 0.98


@dataclass(frozen=True, slots=True)
class FusedArmHit[T]:
    """Result hit produced by adaptive relaxed-arm fusion."""

    item: T
    key: str
    score: float
    raw_rrf_score: float
    contributing_arms: list[str] = field(default_factory=list)
    is_volunteer_fallback: bool = False


@dataclass(frozen=True, slots=True)
class AdaptiveFusionResult[T]:
    """Full fusion outcome containing hits and observability telemetry."""

    hits: list[FusedArmHit[T]]
    arm_telemetry: list[ArmTelemetryProfile]
    volunteer_activated: bool
    demoted_arms: list[str]
