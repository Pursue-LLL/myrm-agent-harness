"""Package facade for prompt cache break prevention shield and smart session branching.

[INPUT]
- agent.context_management.cache_shield.cache_break_evaluator::evaluate_parameter_mutation (POS: Detects
  mid-flight parameter mutations that break provider cache keys, calculating cost penalties and advice.)
- agent.context_management.cache_shield.cache_shield_engine::CacheBreakPreventionShieldEngine (POS: Main
  coordinator protecting prompt cache keys from accidental destruction and supporting lossless rewinds.)
- agent.context_management.cache_shield.cache_shield_types::CacheBreakEvaluation, CacheParameterKind,
  CachePreservingForkResult, CacheRewindResult, CacheRiskLevel (POS: Data contracts for cache break
  interception, cost impact evaluation, and smart cache branching.)

[OUTPUT]
- Re-exports: CacheBreakEvaluation, CacheBreakPreventionShieldEngine, CacheParameterKind,
  CachePreservingForkResult, CacheRewindResult, CacheRiskLevel, evaluate_parameter_mutation

[POS]
Prompt cache break prevention shield and smart session branching facade.
"""

from __future__ import annotations

from .cache_break_evaluator import evaluate_parameter_mutation
from .cache_shield_engine import CacheBreakPreventionShieldEngine
from .cache_shield_types import (
    CacheBreakEvaluation,
    CacheParameterKind,
    CachePreservingForkResult,
    CacheRewindResult,
    CacheRiskLevel,
)

__all__ = [
    "CacheBreakEvaluation",
    "CacheBreakPreventionShieldEngine",
    "CacheParameterKind",
    "CachePreservingForkResult",
    "CacheRewindResult",
    "CacheRiskLevel",
    "evaluate_parameter_mutation",
]
