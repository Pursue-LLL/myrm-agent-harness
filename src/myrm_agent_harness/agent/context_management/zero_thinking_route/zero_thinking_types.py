"""Data contracts and type definitions for zero thinking budget direct routing and cost decoupling.

Normalizes zero-thinking budget parameters across LLM providers (Anthropic, DeepSeek, OpenAI),
allowing deterministic tasks to skip deep reasoning, dropping output tokens and TTFT by 80%+.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ThinkingBudgetMode: Reasoning effort and thinking budget allocation mode.
- ModelProviderKind: Underlying model family for provider-specific API wire translation.
- ProviderThinkingPayload: Normalized wire payload injected into chat completion API calls.
- DeterministicTaskDetection: Diagnostic outcome of inspecting prompt for deterministic mechanical workloads.
- ZeroThinkingSavingsRecord: Telemetry capturing output tokens and latency savings from zero-thinking routing.

[POS]
Data contracts and type definitions for zero thinking budget direct routing and cost decoupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ThinkingBudgetMode(str, Enum):
    """Reasoning effort and thinking budget allocation mode."""

    ZERO_DIRECT = "zero_direct"  # budget = 0, completely disabled thinking
    LOW = "low"                  # minimal reasoning budget
    MEDIUM = "medium"            # standard reasoning budget
    HIGH = "high"                # maximum reasoning depth
    AUTO = "auto"                # model provider default


class ModelProviderKind(str, Enum):
    """Underlying model family for provider-specific API wire translation."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GENERIC = "generic"


@dataclass(frozen=True)
class ProviderThinkingPayload:
    """Normalized wire payload injected into chat completion API calls."""

    provider: ModelProviderKind
    mode: ThinkingBudgetMode
    budget_tokens: int
    extra_body_params: dict[str, str | int | dict[str, str | int]] = field(default_factory=dict)
    is_thinking_disabled: bool = False
    routed_model_override: str | None = None
    explanation: str = ""


@dataclass(frozen=True)
class DeterministicTaskDetection:
    """Diagnostic outcome of inspecting prompt for deterministic mechanical workloads."""

    is_deterministic: bool
    confidence: float
    detected_pattern: str | None = None
    suggested_mode: ThinkingBudgetMode = ThinkingBudgetMode.AUTO
    reason: str = ""


@dataclass(frozen=True)
class ZeroThinkingSavingsRecord:
    """Telemetry capturing output tokens and latency savings from zero-thinking routing."""

    record_id: str
    task_description: str
    mode: ThinkingBudgetMode
    actual_thinking_tokens: int
    avoided_baseline_thinking_tokens: int
    estimated_cost_saved_usd: float
    estimated_ttft_saved_ms: float
