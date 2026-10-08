# [INPUT]: None
# [OUTPUT]: ContextTierKind, TriggerDomainKind, TriggeredRule, JitHandle, SynthesisInput, SynthesizedDirective, FourTierContextConfig, AssembledContextPayload
# [POS]: agent/context_management/four_tier_routing/four_tier_types.py

"""Domain types and contracts for the Four-Tier Context Engineering Architecture.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- ContextTierKind: The four distinct layers (Deterministic, Triggered, JIT, Synthesis).
- TriggerDomainKind: Specialized operation domains (DB, API, Billing, Security, UI, Perf).
- TriggeredRule: Domain rule dynamically routed based on target paths and query intent.
- JitHandle: Lightweight placeholder handle for just-in-time on-demand retrieval.
- SynthesisInput: Multi-source fragments, ADRs, and bug records for pre-prompt synthesis.
- SynthesizedDirective: High-value concrete engineering judgment synthesized from fragments.
- FourTierContextConfig: Thresholds and configuration governing context tiers.
- AssembledContextPayload: Final layered context assembly with token accounting.

[POS]
Domain layer establishing Anthropic Context Engineering inspired four-tier context assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class ContextTierKind(str, Enum):
    """The four distinct architectural context tiers."""

    DETERMINISTIC = "DETERMINISTIC"  # Tier 1: Fixed project baseline, specs, core safety
    TRIGGERED = "TRIGGERED"  # Tier 2: Dynamically routed domain rules (DB, API, Security)
    JIT_RETRIEVAL = "JIT_RETRIEVAL"  # Tier 3: Lightweight handles, hydrated on demand
    SYNTHESIS = "SYNTHESIS"  # Tier 4: High-value pre-synthesized engineering directives


class TriggerDomainKind(str, Enum):
    """Domains targeted by triggered context routing."""

    DATABASE = "DATABASE"
    API_CONTRACT = "API_CONTRACT"
    PAYMENT_BILLING = "PAYMENT_BILLING"
    AUTH_SECURITY = "AUTH_SECURITY"
    FRONTEND_UI = "FRONTEND_UI"
    SYSTEM_PERF = "SYSTEM_PERF"


@dataclass(frozen=True)
class TriggeredRule:
    """Domain rule dynamically matched and injected upon relevant path/intent triggers."""

    rule_id: str
    domain: TriggerDomainKind
    path_patterns: Sequence[str]
    keyword_patterns: Sequence[str]
    content: str
    priority: int = 100


@dataclass(frozen=True)
class JitHandle:
    """Lightweight pointer referencing detailed docs or schemas, hydrated only on demand."""

    handle_id: str
    title: str
    summary: str
    full_reference_pointer: str
    is_hydrated: bool = False
    hydrated_content: str | None = None


@dataclass(frozen=True)
class SynthesisInput:
    """Bundle of heterogeneous knowledge fragments awaiting synthesis."""

    query: str
    fragments: Sequence[str] = field(default_factory=list)
    adrs: Sequence[str] = field(default_factory=list)
    bug_histories: Sequence[str] = field(default_factory=list)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SynthesizedDirective:
    """Actionable engineering judgment distilled from fragmented knowledge sources."""

    directive_id: str
    summary_assertion: str
    actionable_guidelines: Sequence[str]
    conflict_warnings: Sequence[str] = field(default_factory=list)


@dataclass(frozen=True)
class FourTierContextConfig:
    """Configuration governing four-tier context limits and formatting."""

    max_triggered_rules: int = 4
    max_jit_handles: int = 8
    max_synthesis_directives: int = 3
    include_section_headers: bool = True


@dataclass(frozen=True)
class AssembledContextPayload:
    """Structured container holding assembled context across all four tiers."""

    assembled_text: str
    tier_counts: Mapping[ContextTierKind, int]
    total_characters: int
    estimated_tokens: int
    active_domains: Sequence[TriggerDomainKind]
