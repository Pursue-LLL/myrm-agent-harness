"""Skill Optimization Toolkit

Building blocks for shadow-testing candidate skill versions before they replace the active one.

## Framework Layer (myrm-agent-harness)

Protocol-based, no business dependencies:
- **ABTestEngine**: starts an A/B test for a candidate version (adaptive target sample size + optimistic version lock)
- **ResultComparator / StructuredComparator**: compares baseline and candidate execution results
- **SkillSecurityValidator**: multi-layer security validation of skill content
- **SkillOptimizer**: LLM-driven skill rewrite with type detection and cross-process locking
- **EventLogAdapter**: reads skill execution samples from the event log
- **EventEmitter**: observer-pattern event hub
- **MetricsCollector**: in-process metrics for the optimizer
- **SkillOptimizationStorage / SkillExecutionProvider**: protocols the business layer implements

## Business Layer (myrm-agent-server)

- **SQLAlchemyStorage**: SkillOptimizationStorage adapter (SQLite/PostgreSQL)
- **ServerSkillExecutionProvider**: SkillExecutionProvider adapter that replays skill versions for shadow runs

## Example

```python
from myrm_agent_harness.agent.skills.optimization import ABTestEngine, OptimizationConfig

config = OptimizationConfig()
ab_result = await ABTestEngine(config.ab_test).start_ab_test(
    skill_id="my-skill",
    baseline_version=1,
    baseline_score=baseline_score,
    candidate_content=candidate_content,
)
```

## Exports
"""

from .ab_test import ABTestEngine
from .config import (
    ABTestConfig,
    OptimizationConfig,
    PerformanceConfig,
    SecurityConfig,
)
from .event_adapter import EventLogAdapter
from .event_emitter import EventEmitter
from .observability import (
    MetricsCollector,
    Timer,
    get_metrics_collector,
    structured_log,
)
from .optimizer import SkillOptimizer
from .protocols import (
    SkillExecutionProvider,
    SkillExecutionSample,
    SkillOptimizationStorage,
    StorageError,
)
from .result_comparator import ComparisonDetail, ResultComparator, StructuredComparator
from .security import SkillSecurityValidator
from .types import (
    ABTestResult,
    ABTestStatus,
    LockAcquisitionError,
    LockProvider,
    OptimizationError,
    OptimizationResult,
    OptimizationStatus,
    SecurityError,
    SecurityValidationResult,
    SkillQualityScore,
    SkillType,
    SkillVersion,
    VersionConflictError,
)

__all__ = [
    "ABTestConfig",
    "ABTestEngine",
    "ABTestResult",
    "ABTestStatus",
    "ComparisonDetail",
    "EventEmitter",
    "EventLogAdapter",
    "LockAcquisitionError",
    "LockProvider",
    "MetricsCollector",
    "OptimizationConfig",
    "OptimizationError",
    "OptimizationResult",
    "OptimizationStatus",
    "PerformanceConfig",
    "ResultComparator",
    "SecurityConfig",
    "SecurityError",
    "SecurityValidationResult",
    "SkillExecutionProvider",
    "SkillExecutionSample",
    "SkillOptimizationStorage",
    "SkillOptimizer",
    "SkillQualityScore",
    "SkillSecurityValidator",
    "SkillType",
    "SkillVersion",
    "StorageError",
    "StructuredComparator",
    "Timer",
    "VersionConflictError",
    "get_metrics_collector",
    "structured_log",
]
