"""Type definitions for Raw Model Direct Passthrough and Pristine Testing Sandbox.

Defines schemas for zero-injection passthrough execution, pristine payload isolation,
and side-by-side dual-track experiment telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PristinePassthroughMode(StrEnum):
    """Operational mode determining whether agent scaffolding is injected."""

    AGENT_AUGMENTED = "agent_augmented"
    RAW_PASSTHROUGH = "raw_passthrough"


@dataclass(frozen=True)
class PristineExecutionConfig:
    """Configuration governing framework prompt and tool stripping."""

    mode: PristinePassthroughMode
    strip_agent_system_prompt: bool = True
    strip_tools: bool = True
    custom_system_prompt: str | None = None


@dataclass(frozen=True)
class PristinePayload:
    """Prepared payload delivered directly to the underlying model provider."""

    messages: tuple[dict[str, str], ...]
    tools_provided: bool
    system_prompt_used: str | None
    is_pristine: bool


@dataclass(frozen=True)
class DualRunExperimentReport:
    """Side-by-side comparative telemetry comparing raw baseline vs agent-augmented output."""

    experiment_id: str
    prompt: str
    raw_response: str
    augmented_response: str
    raw_tokens: int
    augmented_tokens: int
    tools_invoked_count: int
    raw_latency_ms: float
    augmented_latency_ms: float
    token_overhead_ratio: float
    metadata: dict[str, str] = field(default_factory=dict)
