"""Enhanced model fallback with cooldown and candidate pool.

Provides sophisticated model fallback management with:
- Cooldown period: Temporarily skip failed models
- Candidate pool: Support multiple fallback models
- Decision logging: Track fallback decisions for observability

[INPUT]
- llms.errors.classifier (POS: error classification)

[OUTPUT]
- ModelFallbackManager: model fallback manager
- ModelCandidate: model candidate dataclass
- ManagedLLM: LLM wrapper integrating ModelFallbackManager

[POS]
Enhanced model fallback management. Supports cooldown periods, candidate pools, and decision logging.
"""

from .circuit_breaker import CircuitBreaker, CircuitState
from .config import PRESET_CONFIGS, ProbeConfig, get_preset_config
from .context import (
    FailoverEmitter,
    failover_emitter_ctx,
    get_active_failover_emitter,
    with_failover_emitter,
)
from .events import FailoverCallback, FailoverEvent, RecoveryCallback, RecoveryEvent
from .health_check import lightweight_health_check, lightweight_health_check_with_retry
from .logger import log_fallback_attempt, log_fallback_decision
from .managed_llm import FallbackModel, ManagedLLM
from .manager import ModelCandidate, ModelFallbackManager
from .presets import (
    PRESET_STRATEGIES,
    FallbackStrategy,
    create_managed_llm_from_preset,
    get_preset_strategy,
)
from .probe_throttle import GlobalProbeThrottle, get_global_probe_throttle
from .recommendations import (
    FallbackRecommendation,
    generate_quantified_reason,
    get_primary_recommendation,
    recommend_fallback,
)
from .scenario import ModelMetrics, ScenarioType, select_by_scenario, select_by_scenario_with_quality

__all__ = [
    "PRESET_CONFIGS",
    "PRESET_STRATEGIES",
    "CircuitBreaker",
    "CircuitState",
    "FailoverCallback",
    "FailoverEmitter",
    "FailoverEvent",
    "FallbackModel",
    "FallbackRecommendation",
    "FallbackStrategy",
    "GlobalProbeThrottle",
    "ManagedLLM",
    "ModelCandidate",
    "ModelFallbackManager",
    "ModelMetrics",
    "ProbeConfig",
    "RecoveryCallback",
    "RecoveryEvent",
    "ScenarioType",
    "create_managed_llm_from_preset",
    "failover_emitter_ctx",
    "generate_quantified_reason",
    "get_active_failover_emitter",
    "get_global_probe_throttle",
    "get_preset_config",
    "get_preset_strategy",
    "get_primary_recommendation",
    "lightweight_health_check",
    "lightweight_health_check_with_retry",
    "log_fallback_attempt",
    "log_fallback_decision",
    "recommend_fallback",
    "select_by_scenario",
    "select_by_scenario_with_quality",
    "with_failover_emitter",
]
