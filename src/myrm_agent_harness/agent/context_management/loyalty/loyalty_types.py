# ============================================================================
# # In-Context Loyalty Stack & Test-Time RL Types (Item 150)
# # Strict typed contracts for user-centric alignment, vendor bias neutralization,
# # and test-time in-context reinforcement learning exemplars.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ModelVendorFamily(StrEnum):
    """Categorization of underlying foundation model families."""

    ANTHROPIC_CLAUDE = "anthropic_claude"
    OPENAI_GPT = "openai_gpt"
    DEEPSEEK = "deepseek"
    QWEN_LOCAL = "qwen_local"
    GENERIC_LLM = "generic_llm"


@dataclass(slots=True)
class UserLoyaltyPreference:
    """Explicit user alignment preferences overriding arbitrary vendor agendas."""

    coding_style_rules: list[str] = field(default_factory=list)
    negative_avoidance_list: list[str] = field(default_factory=list)
    architectural_principles: list[str] = field(default_factory=list)
    preferred_tone: str = "direct_concise_architectural"
    custom_signature: str = ""

    def to_dict(self) -> dict[str, str | list[str]]:
        """Serializes loyalty preferences to dictionary."""
        return {
            "coding_style_rules": list(self.coding_style_rules),
            "negative_avoidance_list": list(self.negative_avoidance_list),
            "architectural_principles": list(self.architectural_principles),
            "preferred_tone": self.preferred_tone,
            "custom_signature": self.custom_signature,
        }


@dataclass(slots=True)
class InContextRLExemplar:
    """Test-time reinforcement learning exemplar capturing rewarded behavior."""

    exemplar_id: str
    task_type: str  # "refactor", "bugfix", "system_design", "testing"
    input_context_summary: str
    preferred_output_sample: str
    reward_rationale: str
    success_score: float = 1.0  # Normalized positive reward scalar
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float]:
        """Serializes exemplar to dictionary."""
        return {
            "exemplar_id": self.exemplar_id,
            "task_type": self.task_type,
            "input_context_summary": self.input_context_summary,
            "preferred_output_sample": self.preferred_output_sample,
            "reward_rationale": self.reward_rationale,
            "success_score": self.success_score,
        }


@dataclass(slots=True)
class UserLoyaltyStackConfig:
    """Configuration governing loyalty injection and cross-model neutralization."""

    max_exemplars: int = 3
    enable_in_context_rl: bool = True
    neutralize_vendor_bias: bool = True
    loyalty_priority_rank: int = 95


@dataclass(slots=True)
class ModelNeutralizedPrompt:
    """Model-agnostic neutralized prompt ready for cross-model inference."""

    vendor_family: ModelVendorFamily
    neutralized_system_prompt: str
    injected_loyalty_block: str
    exemplars_count: int
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float]:
        """Serializes neutralized prompt details to dictionary."""
        return {
            "vendor_family": str(self.vendor_family),
            "neutralized_system_prompt_length": len(self.neutralized_system_prompt),
            "injected_loyalty_block_length": len(self.injected_loyalty_block),
            "exemplars_count": self.exemplars_count,
            "generated_at": self.generated_at,
        }
