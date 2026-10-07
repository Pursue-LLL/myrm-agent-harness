"""Types and schemas for top-section canonical alignment and cross-agent prefix cache sharing.

[INPUT]
Canonical system prompt section definitions, agent specialization blocks, and volatile context fragments.

[OUTPUT]
Type-safe hierarchical section specifications, prefix pollution inspection outcomes,
and cross-agent prompt assembly artifacts.

[POS]
Item 120 in topic_06 roadmap: enforces stable top-section ordering for 99% KV cache hit rate.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SectionTier(StrEnum):
    """Hierarchical tier assignment for system prompt sections."""
    PLATFORM_CORE = "section_00_09_platform_core"
    TOOLING_DISCIPLINE = "section_10_19_tooling_discipline"
    SHARED_COLLABORATION = "section_20_29_shared_collaboration"
    AGENT_ROLE_SPECIALIZATION = "section_30_39_agent_specialization"
    DYNAMIC_EPHEMERAL = "section_40_49_dynamic_ephemeral"


@dataclass(frozen=True)
class CanonicalSectionSpec:
    """Specification of an ordered prompt section."""
    section_id: str
    tier: SectionTier
    order_index: int
    title: str
    content: str
    is_immutable: bool = True


class VolatilePollutionError(ValueError):
    """Raised when volatile patterns (dates, branches, dynamic lists) pollute static prefixes."""


@dataclass(frozen=True)
class VolatileContentDetectionResult:
    """Result of static mechanical inspection for volatile cache-busting tokens."""
    has_volatile_content: bool
    detected_patterns: tuple[str, ...] = ()
    recommendation: str = ""


@dataclass(frozen=True)
class CanonicalPromptAssemblyResult:
    """Outcome of canonical layered system prompt compilation."""
    full_prompt: str
    shared_prefix_prompt: str
    shared_prefix_fingerprint: str
    total_token_count_approx: int
    prefix_token_count_approx: int
    sections_ordered: tuple[CanonicalSectionSpec, ...]
    compiled_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class CrossAgentPrefixComparisonResult:
    """Validation report comparing prefix byte-level identity across multiple agents."""
    is_identical: bool
    common_prefix_bytes: int
    shared_prefix_fingerprint: str
    discrepancy_details: str | None = None
