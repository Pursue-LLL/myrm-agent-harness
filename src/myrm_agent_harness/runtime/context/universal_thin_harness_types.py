"""Universal agent thin harness adaptive contract and Token Tax governor types.

Defines operating modes (Pure, Lean, Audit), model capability tiers, thin
system prompt contracts, transient tool GC receipts, and Token Tax audit snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class OperatingDisciplineMode(StrEnum):
    """Execution discipline modes balancing agility, engineering rigor, and compliance."""

    PURE = "pure"  # Minimalist ~200-token prompt, unconstrained persona, daily tasks
    LEAN = "lean"  # Pragmatic engineering, minimal sufficient checks, standard coding
    AUDIT = "audit"  # Strict verification, complete audit trail, sensitive domains


class ModelCapabilityTier(StrEnum):
    """Capability tier of the underlying foundation model."""

    FRONTIER = "frontier"  # SOTA reasoning/general models (e.g. GPT-4o, Claude 3.5, DeepSeek-V3/R1)
    STANDARD = "standard"  # General mid-tier models (e.g. GPT-4o-mini, Qwen-2.5-32B)
    LEGACY = "legacy"  # Older or constrained models requiring explicit instruction scaffolding


@dataclass(frozen=True)
class ThinPromptContract:
    """Adaptive thin prompt bundle ensuring persona fidelity and zero harness bloat."""

    mode: OperatingDisciplineMode
    capability_tier: ModelCapabilityTier
    system_prompt_core: str
    custom_persona_prompt: str
    estimated_overhead_tokens: int
    is_native_cot_passthrough: bool
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TransientToolOutputGCReceipt:
    """Receipt tracking dehydration of intermediate diagnostic logs."""

    message_id: str
    tool_name: str
    original_char_count: int
    dehydrated_char_count: int
    saved_tokens: int
    is_dehydrated: bool
    reason: str


@dataclass(frozen=True)
class TokenTaxAuditSnapshot:
    """Transparency audit metrics exposing context composition and Token Tax ratio."""

    mode: OperatingDisciplineMode
    harness_overhead_tokens: int
    custom_persona_tokens: int
    tool_output_tokens: int
    conversation_history_tokens: int
    total_active_tokens: int
    cumulative_dehydrated_saved_tokens: int
    effective_tax_ratio: float  # (harness_overhead + tool_output) / total_active_tokens
