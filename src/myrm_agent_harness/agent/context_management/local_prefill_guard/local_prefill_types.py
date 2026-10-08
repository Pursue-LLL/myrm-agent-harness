"""Strongly-typed contracts for local LLM prefill latency guard and adaptive pruning.

[INPUT]
- None (pure domain models)

[OUTPUT]
- LocalEndpointKind: Enum of recognized inference endpoint varieties.
- LatencyWarningLevel: Severity tier for estimated TTFT latency.
- PruningPolicyTier: Aggressiveness tier for tool result pruning.
- LocalEndpointProfile: Introspected profile of the target inference endpoint.
- PrefillLatencyEstimate: Fitted TTFT calculation, latency category, and advisory.
- AdaptivePruningDecision: Computed thresholds and parameters for tool result pruning.
- PrefillProgressCapsule: Lightweight payload for WebUI/SSE streaming indicators.
- PrunedResultSummary: Metadata for an individual pruned tool invocation.
- LocalPrefillGuardResult: End-to-end execution audit report.

[POS]
Data definitions and contracts for local LLM long-context TTFT latency guard,
predictive TTFT estimation, and adaptive tool-result aggressive pruning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LocalEndpointKind(str, Enum):
    """Categorized varieties of model inference backends."""

    OLLAMA = "ollama"
    VLLM = "vllm"
    MLX = "mlx"
    LLAMA_CPP = "llama_cpp"
    LM_STUDIO = "lm_studio"
    LOCAL_CUSTOM = "local_custom"
    CLOUD_API = "cloud_api"


class LatencyWarningLevel(str, Enum):
    """Severity tier for estimated prefill time-to-first-token (TTFT)."""

    NORMAL = "normal"              # TTFT < 5.0s
    ELEVATED = "elevated"          # 5.0s <= TTFT < 15.0s
    CRITICAL_SLOW = "critical_slow"# 15.0s <= TTFT < 60.0s
    FREEZE_RISK = "freeze_risk"    # TTFT >= 60.0s (severe stall warning, e.g. 118s Mac M5 64k)


class PruningPolicyTier(str, Enum):
    """Policy aggressiveness for pruning prior tool results."""

    CONSERVATIVE_CLOUD = "conservative_cloud"    # Threshold 2048, keep 5
    BALANCED_LOCAL = "balanced_local"            # Threshold 1024, keep 3
    AGGRESSIVE_LOCAL_32K = "aggressive_local_32k"# Threshold 512, keep 2
    EMERGENCY_SHEDDING = "emergency_shedding"    # Threshold 256, keep 1


@dataclass(frozen=True)
class LocalEndpointProfile:
    """Introspected inference profile and hardware/runtime assumptions."""

    endpoint_kind: LocalEndpointKind
    model_name: str
    is_local: bool
    context_window_limit: int = 65536
    estimated_param_size_b: float = 14.0   # 7B, 14B, 32B, 70B
    quantization: str = "q4_k_m"            # fp16, q8_0, q4_k_m
    memory_bandwidth_gb_s: float = 400.0   # e.g., Mac Studio M5 Ultra / M2 Max ~400-800 GB/s
    is_unified_memory: bool = True


@dataclass(frozen=True)
class PrefillLatencyEstimate:
    """Fitted calculation of Time-To-First-Token (TTFT) for a given prompt size."""

    prompt_tokens: int
    estimated_ttft_seconds: float
    warning_level: LatencyWarningLevel
    warning_message: str
    suggests_aggressive_pruning: bool
    quadratic_overhead_fraction: float


@dataclass(frozen=True)
class AdaptivePruningDecision:
    """Computed tuning parameters based on context size and endpoint profile."""

    policy_tier: PruningPolicyTier
    threshold_tokens: int
    keep_recent_calls: int
    min_reclaim_tokens: int
    head_chars: int
    tail_chars: int
    reason: str


@dataclass(frozen=True)
class PrunedResultSummary:
    """Metadata recorded when an individual tool result is compacted."""

    tool_name: str
    tool_call_id: str
    original_tokens: int
    pruned_tokens: int
    saved_tokens: int
    snippet_preview: str


@dataclass(frozen=True)
class PrefillProgressCapsule:
    """WebUI and streaming-friendly status capsule for user transparency."""

    capsule_id: str
    estimated_ttft_seconds: float
    status_label: str
    human_status_text: str
    show_fast_trim_action: bool
    tokens_before_prune: int
    tokens_after_prune: int
    estimated_latency_saved_seconds: float


@dataclass(frozen=True)
class LocalPrefillGuardResult:
    """Complete summary of latency guard inspection and pruning actions."""

    endpoint_profile: LocalEndpointProfile
    original_tokens: int
    projected_original_ttft_s: float
    final_tokens: int
    projected_final_ttft_s: float
    decision: AdaptivePruningDecision
    pruned_summaries: list[PrunedResultSummary] = field(default_factory=list)
    tokens_saved: int = 0
    latency_reduced_seconds: float = 0.0
    capsule: PrefillProgressCapsule | None = None
