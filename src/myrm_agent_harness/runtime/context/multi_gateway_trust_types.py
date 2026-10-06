"""Strongly typed data contracts for Model-Harness orthogonal decoupling and multi-gateway trust.

Provides enums, rule matrix definitions, handoff cards, reality check receipts,
and cost routing structures with zero Any.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class GatewayTrustTier(StrEnum):
    """Trust tier of the client gateway accessing the agent."""

    CLI_TRUSTED = "cli_trusted"
    DESKTOP_TRUSTED = "desktop_trusted"
    WEBUI_STANDARD = "webui_standard"
    MOBILE_RESTRICTED = "mobile_restricted"
    VOICE_MINIMAL = "voice_minimal"


class HighRiskActionKind(StrEnum):
    """High risk action categories requiring elevated trust."""

    FILE_DELETION = "file_deletion"
    PROD_DEPLOYMENT = "prod_deployment"
    SECRET_ENV_ACCESS = "secret_env_access"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    EXTERNAL_WRITE = "external_write"


class HandoffCardStatus(StrEnum):
    """Lifecycle status of a handoff card."""

    PENDING_APPROVAL = "pending_approval"
    APPROVED_EXECUTED = "approved_executed"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class HandoffCard:
    """Tamper-evident handoff card for transferring degraded tasks across gateways."""

    handoff_id: str
    session_id: str
    source_gateway: GatewayTrustTier
    target_gateway: GatewayTrustTier
    action_kind: HighRiskActionKind
    action_payload: str
    explanation: str
    signature: str
    created_at_utc: str
    status: HandoffCardStatus = HandoffCardStatus.PENDING_APPROVAL


class RuleLayerKind(StrEnum):
    """Hierarchical layer of rule files with deterministic topological priority."""

    CORRECTIONS = "corrections"  # Priority 100: Specific corrections and bugfix lessons
    VOICE = "voice"  # Priority 80: Persona, tone, and communication style
    CONTEXT = "context"  # Priority 60: Workspace terminology, business facts
    AGENTS = "agents"  # Priority 40: Engineering constraints, architecture rules
    SOUL = "soul"  # Priority 20: Fundamental worldview and bedrock principles

    @property
    def priority_score(self) -> int:
        """Return the numerical priority for arbitration (higher wins)."""
        mapping: dict[str, int] = {
            "corrections": 100,
            "voice": 80,
            "context": 60,
            "agents": 40,
            "soul": 20,
        }
        return mapping[self.value]


@dataclass(frozen=True)
class RuleEntry:
    """Individual rule statement with metadata."""

    rule_id: str
    layer: RuleLayerKind
    category: str
    content: str
    is_ephemeral: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuleConflictResolution:
    """Outcome of resolving a conflict between overlapping rules."""

    winning_rule: RuleEntry
    suppressed_rules: tuple[RuleEntry, ...]
    rationale: str


@dataclass(frozen=True)
class FiveLayerRuleMatrix:
    """Matrix containing rules partitioned across all five hierarchical layers."""

    soul_rules: tuple[RuleEntry, ...] = field(default_factory=tuple)
    agents_rules: tuple[RuleEntry, ...] = field(default_factory=tuple)
    context_rules: tuple[RuleEntry, ...] = field(default_factory=tuple)
    voice_rules: tuple[RuleEntry, ...] = field(default_factory=tuple)
    corrections_rules: tuple[RuleEntry, ...] = field(default_factory=tuple)

    def all_rules(self) -> tuple[RuleEntry, ...]:
        """Aggregate all rule entries in topological order (highest priority first)."""
        return (
            self.corrections_rules
            + self.voice_rules
            + self.context_rules
            + self.agents_rules
            + self.soul_rules
        )


class TriStateTag(StrEnum):
    """Tri-state classification for structured task context handoff."""

    KEEP = "keep"  # Crucial facts, goals, code diffs, verification receipts
    COMPRESS = "compress"  # Intermediate thoughts, tool execution verbosity
    DISCARD = "discard"  # Temporary dead-ends, discarded theories, chit-chat


@dataclass(frozen=True)
class PrunedContextItem:
    """Single context item classified under the tri-state convention."""

    item_id: str
    tag: TriStateTag
    source_type: str
    original_content: str
    processed_content: str


@dataclass(frozen=True)
class RealityCheckReceipt:
    """Receipt resulting from cross-checking handoff claims against ground truth."""

    verified: bool
    checked_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    git_clean: bool
    discrepancies: tuple[str, ...]
    timestamp_utc: str


class TaskComplexity(StrEnum):
    """Categorization of task complexity for cost-to-outcome routing."""

    SIMPLE_LOOKUP = "simple_lookup"
    STANDARD_TASK = "standard_task"
    COMPLEX_REFACTOR = "complex_refactor"
    DEEP_EXPLORATION = "deep_exploration"



@dataclass(frozen=True)
class ModelCostProfile:
    """Token pricing and historical empirical reliability of an LLM."""

    model_id: str
    input_token_rate_per_k: float
    output_token_rate_per_k: float
    historical_success_rate: float
    avg_latency_ms: float
    complexity_success_rates: Mapping[TaskComplexity, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CostRoutingDecision:
    """Decision output detailing the cost-to-outcome model selection."""

    selected_model: str
    estimated_total_cost: float
    expected_attempts: float
    harness_responsibility: str
    rationale: str


@dataclass(frozen=True)
class WorktreeAllocation:
    """Subagent workspace isolation assignment."""

    subagent_id: str
    worktree_name: str
    isolated_path: str
    allocated_at: str


@dataclass(frozen=True)
class WorktreeReconcileResult:
    """Result of reconciling multiple subagents' workspace modifications."""

    has_conflict: bool
    conflicting_files: tuple[str, ...]
    merged_files: tuple[str, ...]
    summary: str
