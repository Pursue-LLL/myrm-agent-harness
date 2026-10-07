"""Types and schemas for 4-layer progressive disclosure and evidence traceability suite.

Defines the 5-stage cognitive state machine, evidence attribution citations,
milestone facts, and verification validation results.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class DisclosureStage(str, Enum):
    """Five-stage state machine for progressive disclosure cognitive path."""

    BUSINESS_META = "business_meta"  # Stage 1: Domain scenario & disambiguation
    ARCHITECTURE_TOPOLOGY = "architecture_topology"  # Stage 2: Upstream/downstream service links
    SERVICE_SCHEMA = "service_schema"  # Stage 3: Dense YAML/OpenAPI contracts
    INFRASTRUCTURE_GUARD = "infrastructure_guard"  # Stage 4: Timeouts, idempotency, safety gates
    CODE_EVIDENCE_GROUNDING = "code_evidence_grounding"  # Stage 5: Exact AST code slice verification
    COMPLETED = "completed"  # All stages verified and delivered


class EvidenceAttributionType(str, Enum):
    """Source classification for factual citations."""

    CODE_SLICE = "code_slice"  # [代码] path/to/file.py:line
    SERVICE_CONTRACT = "service_contract"  # [契约] path/to/service.yaml:line
    INFRA_PRINCIPLE = "infra_principle"  # [原则] path/to/policy.md:line
    BUSINESS_RULE = "business_rule"  # [规则] domain/meta/rule.json:line


@dataclass
class EvidenceCitation:
    """Rigorous factual attribution attached to an architectural claim."""

    attribution_type: EvidenceAttributionType
    source_file: str
    line_number: int
    snippet: str
    verified: bool = True
    verified_at: float = field(default_factory=time.time)

    def format_tag(self) -> str:
        """Format as standardized markdown citation tag."""
        type_prefix = {
            EvidenceAttributionType.CODE_SLICE: "代码",
            EvidenceAttributionType.SERVICE_CONTRACT: "契约",
            EvidenceAttributionType.INFRA_PRINCIPLE: "原则",
            EvidenceAttributionType.BUSINESS_RULE: "规则",
        }.get(self.attribution_type, "凭证")
        return f"[{type_prefix}] {self.source_file}:{self.line_number}"


@dataclass
class CognitiveMilestoneFact:
    """Distilled fact established during a completed disclosure stage."""

    stage: DisclosureStage
    key_finding: str
    citations: list[EvidenceCitation] = field(default_factory=list)
    recorded_at: float = field(default_factory=time.time)


@dataclass
class AttributionValidationResult:
    """Outcome of verifying whether an architectural proposal contains required citations."""

    is_valid: bool
    total_claims: int
    verified_claims: int
    unverified_claims: int
    violations: list[str]
    citations_found: list[str]
    checked_at: float = field(default_factory=time.time)


@dataclass
class ProgressiveDisclosureConfig:
    """Configuration governing disclosure stages and evidence attribution rules."""

    strict_evidence_enforcement: bool = True
    max_context_budget_per_stage: int = 16000
    allow_stage_skipping: bool = False
    required_stages_for_delivery: list[DisclosureStage] = field(
        default_factory=lambda: [
            DisclosureStage.BUSINESS_META,
            DisclosureStage.ARCHITECTURE_TOPOLOGY,
            DisclosureStage.SERVICE_SCHEMA,
            DisclosureStage.INFRASTRUCTURE_GUARD,
            DisclosureStage.CODE_EVIDENCE_GROUNDING,
        ]
    )
