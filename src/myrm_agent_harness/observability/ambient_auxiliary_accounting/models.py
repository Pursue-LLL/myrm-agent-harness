"""[INPUT] Auxiliary task invocation telemetry (task labels, models, tokens, latency).
[OUTPUT] Immutable data structures for ambient auxiliary usage accounting and task-dimension attribution.
[POS] myrm_agent_harness.observability.ambient_auxiliary_accounting.models

Defines the core data models for orthogonal auxiliary usage accounting:
1. AuxiliaryTaskType: Standardized task taxonomy (main_dialogue, vision_prep, context_compression, title_generation, shadow_eval, reflection)
2. AuxiliaryUsageSnapshot: Record of individual auxiliary LLM invocation
3. TaskCostSummary: Aggregated cost, tokens, and share percentage per task dimension
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class AuxiliaryTaskType(str, Enum):
    """Standardized taxonomy of agent operations distinguishing core conversation from auxiliary sub-tasks."""

    MAIN_DIALOGUE = "main_dialogue"                 # Primary user-facing conversation
    VISION_PREP = "vision_prep"                     # Screenshot / image crop & multimodal preprocessing
    CONTEXT_COMPRESSION = "context_compression"     # Memory & long-context summarization
    TITLE_GENERATION = "title_generation"           # Ephemeral session title labeling
    SHADOW_EVAL = "shadow_eval"                     # Background safety guardrail & policy inspection
    BACKGROUND_REFLECTION = "background_reflection" # Internal tree-of-thought & plan review
    CUSTOM = "custom"                               # User-defined auxiliary operation


@dataclass(frozen=True)
class AuxiliaryUsageSnapshot:
    """Individual invocation record captured within ambient auxiliary context."""

    session_id: str
    task_type: AuxiliaryTaskType
    custom_task_name: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: float
    cost_usd: float
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    @property
    def effective_task_name(self) -> str:
        if self.task_type == AuxiliaryTaskType.CUSTOM and self.custom_task_name:
            return self.custom_task_name
        return self.task_type.value

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "session_id": self.session_id,
            "task_type": self.task_type.value,
            "custom_task_name": self.custom_task_name,
            "effective_task_name": self.effective_task_name,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "duration_ms": self.duration_ms,
            "cost_usd": round(self.cost_usd, 6),
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(frozen=True)
class TaskCostSummary:
    """Aggregated operational footprint for a specific task dimension."""

    task_name: str
    call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
    avg_duration_ms: float
    share_pct: float

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "task_name": self.task_name,
            "call_count": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "share_pct": round(self.share_pct, 1),
        }


@dataclass(frozen=True)
class AmbientAccountingReport:
    """Overall breakdown comparing core dialogue footprint against auxiliary backstage derivations."""

    total_invocations: int
    total_cost_usd: float
    core_dialogue_cost_usd: float
    auxiliary_cost_usd: float
    auxiliary_cost_share_pct: float
    task_summaries: tuple[TaskCostSummary, ...]
    prompt_cache_purity_preserved: bool = True
    generated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict[str, int | float | bool | list[dict[str, str | int | float]]]:
        return {
            "total_invocations": self.total_invocations,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "core_dialogue_cost_usd": round(self.core_dialogue_cost_usd, 6),
            "auxiliary_cost_usd": round(self.auxiliary_cost_usd, 6),
            "auxiliary_cost_share_pct": round(self.auxiliary_cost_share_pct, 1),
            "task_summaries": [t.to_dict() for t in self.task_summaries],
            "prompt_cache_purity_preserved": self.prompt_cache_purity_preserved,
            "generated_at_ms": self.generated_at_ms,
        }
