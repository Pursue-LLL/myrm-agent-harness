"""Skill Optimization Toolkit

LLM-Driven Skill Self-Optimization System.

**Status**:  Phase 1-3 Complete (10/10)
**Framework Independence**:  完全独立，可被任意项目引用

## Architecture Overview

### Framework Layer (myrm-agent-harness)  完全独立
Provides core optimization engine with Protocol-based design:
- **SkillOptimizer**: 5-dimensional quality evaluation + type detection + cross-process locking
- **ABTestEngine**: Adaptive sampling + early stopping + quick failure detection
- **SkillSecurityValidator**: Multi-layer security validation
- **OptimizationScheduler**: Real-time monitoring + batch optimization + async queue + metrics + config reload
- **InMemoryStorage**: Default storage implementation (LRU + TTL)  开箱即用
- **FileLockProvider**: Industrial-grade concurrency control (Standalone)  内置文件锁
- **EventLogAdapter**: EventLog adapter  内置适配器
- **MetricsCollector**: Observability (14 built-in metrics)  完整可观测性
- **EventEmitter**: Event system (observer pattern)  解耦通知机制
- **HealthCheckProtocol**: Unified health check interface  统一健康检查
- **InsightsAnalyzer**: Tool usage analytics + activity patterns  深度统计分析
- **RecommendationEngine**: Multi-dimensional skill recommendation  智能推荐引擎
- **SkillQualityDataSource Protocol**: Abstract data source interface  依赖倒置
- **UniversalAggregator**: Universal aggregator (depends on DataSource)  框架独立
- **InMemoryAggregator**: Default aggregator implementation  开箱即用
- **StreamingAggregator**: Real-time streaming aggregator  增量聚合

### Business Layer (myrm-agent-server)
Implements framework protocols:
- **SQLAlchemyStorage**: SQLite/PostgreSQL storage implementation  Protocol adapter
- **LLMOptimizer**: LLM invocation with retry logic
- **SkillUsageReporter**: Quality report generation
- **StandaloneLockProvider**: OS native file lock (Industrial-grade)  Standalone Standard
- **SQLSkillQualityDataSource**: SQL data source (implements Protocol)  数据适配器

### Frontend Layer (myrm-agent-frontend)
User interface for optimization management:
- **SkillOptimizationSection**: Dashboard UI component
- Real-time A/B test progress
- Skill quality ranking
- Manual intervention controls

## Key Features

1. **Automatic Skill Type Detection**
   - PREBUILT skills (global shared) → requires cross-process lock (FileLock)
   - USER skills (per-user isolated) → no lock needed
   - WORKSPACE skills (per-workspace) → no lock needed

2. **5-Dimensional Quality Assessment**
   - Success rate
   - Token efficiency
   - Execution time
   - User satisfaction
   - Call frequency

3. **Scientific A/B Testing**
   - Adaptive sampling for low-frequency skills
   - Quick failure detection
   - Early stopping for clear winners
   - Statistical significance testing

4. **Multi-Layer Security**
   - Static pattern scanning
   - YAML frontmatter validation
   - Markdown syntax validation
   - Optional sandbox execution

5. **Fault Tolerance**
   - Lock fallback & Jitter retry
   - LLM retry with exponential backoff
   - Version conflict detection (optimistic locking)

## Example Usage

```python
from myrm_agent_harness.agent.skills.optimization import (
    SkillOptimizer,
    ABTestEngine,
    SkillSecurityValidator,
    OptimizationConfig)

# 1. Create optimizer
config = OptimizationConfig.default()
security_validator = SkillSecurityValidator(config.security)
optimizer = SkillOptimizer(
    llm=your_llm,
    config=config,
    security_validator=security_validator,
    lock_provider=your_file_lock_provider,  # Optional
)

# 2. Optimize a skill
result = await optimizer.optimize_skill(skill, quality_score)

# 3. Run A/B test
ab_engine = ABTestEngine(config.ab_test)
ab_result = await ab_engine.start_ab_test(
    skill_id="my-skill",
    baseline_version=1,
    baseline_score=baseline_score,
    candidate_content=result.optimized_content)

# 4. Aggregate quality metrics (NEW: DataSource Protocol)
from myrm_agent_harness.agent.skills.optimization import (
    UniversalAggregator,
    InMemoryAggregator)

# Option A: Use UniversalAggregator with business DataSource
from your_app.aggregators import SQLSkillQualityDataSource

data_source = SQLSkillQualityDataSource(session_factory)
aggregator = UniversalAggregator(data_source)
metrics = await aggregator.get_global_metrics()

# Option B: Use InMemoryAggregator (out-of-the-box)
memory_agg = InMemoryAggregator(storage)
by_skill = await memory_agg.aggregate_by_skill()
```

## Exports
"""

from .ab_test import ABTestEngine
from .aggregation_in_memory import InMemoryAggregator
from .aggregation_stream import AggregationStream
from .aggregation_streaming import StreamingAggregator
from .aggregation_universal import UniversalAggregator
from .alert_integration import AlertChannel, AlertIntegration
from .anomaly_detector import AnomalyDetector
from .auto_optimization_engine import AutoOptimizationEngine, AutoOptimizationPolicy
from .comparison_analyzer import ComparisonAnalyzer
from .config import (
    ABTestConfig,
    MonitoringConfig,
    OptimizationConfig,
    PerformanceConfig,
    SecurityConfig,
)
from .cost_calculator import CostCalculator, LLMPricingConfig
from .event_adapter import EventLogAdapter
from .event_emitter import EventEmitter
from .health_check import (
    HealthCheckProtocol,
    aggregate_health_checks,
    validate_health_check_result,
)
from .in_memory_storage import InMemoryStorage
from .insights import ActivityPattern, InsightsAnalyzer, ToolUsageInsight, TopSession
from .observability import (
    MetricsCollector,
    Timer,
    get_metrics_collector,
    structured_log,
)
from .optimizer import SkillOptimizer
from .predictive_analyzer import PredictiveAnalyzer
from .protocols import (
    SkillExecutionProvider,
    SkillExecutionSample,
    SkillOptimizationStorage,
    SkillQualityAggregator,
    SkillQualityDataSource,
    StorageConnectionError,
    StorageError,
    StorageTimeoutError,
)
from .rate_limiter import RateLimitExceeded, UserRateLimiter, get_rate_limiter
from .recommender import (
    OptimizationRecommendation,
    RecommendationEngine,
    RecommendationReason,
)
from .result_comparator import ComparisonDetail, ResultComparator, StructuredComparator
from .scheduler import OptimizationScheduler
from .security import SkillSecurityValidator
from .types import (
    ABTestResult,
    ABTestStatus,
    AggregateDimension,
    AnomalyReport,
    ComparisonResult,
    GlobalQualityMetrics,
    LockAcquisitionError,
    LockProvider,
    OptimizationError,
    OptimizationResult,
    OptimizationStatus,
    PredictionResult,
    RootCause,
    SecurityError,
    SecurityValidationResult,
    SkillQualityAggregate,
    SkillQualityScore,
    SkillQualitySnapshot,
    SkillType,
    SkillVersion,
    UserQualityAggregate,
    VersionConflictError,
)

__all__ = [
    "ABTestConfig",
    "ABTestEngine",
    "ABTestResult",
    "ABTestStatus",
    "ActivityPattern",
    "AggregateDimension",
    "AggregationStream",
    "AlertChannel",
    # Alert Integration
    "AlertIntegration",
    "AnomalyDetector",
    "AnomalyReport",
    "AutoOptimizationEngine",
    "AutoOptimizationPolicy",
    # Intelligent Analysis (Phase P2)
    "ComparisonAnalyzer",
    "ComparisonDetail",
    "ComparisonResult",
    # Cost tracking (P0-1)
    "CostCalculator",
    # Event system (Phase 1.1)
    "EventEmitter",
    "EventLogAdapter",
    "GlobalQualityMetrics",
    # Health check (Phase 1.1)
    "HealthCheckProtocol",
    # Aggregation (Phase P1) - Framework Layer Only
    "InMemoryAggregator",
    "InMemoryStorage",
    # Insights & Analytics (Phase 2.3)
    "InsightsAnalyzer",
    "LLMPricingConfig",
    # Exceptions
    "LockAcquisitionError",
    # Protocols
    "LockProvider",
    # Observability
    "MetricsCollector",
    "MonitoringConfig",
    # Config
    "OptimizationConfig",
    "OptimizationError",
    "OptimizationRecommendation",
    "OptimizationResult",
    "OptimizationScheduler",
    "OptimizationStatus",
    "PerformanceConfig",
    "PredictionResult",
    "PredictiveAnalyzer",
    "RateLimitExceeded",
    # Recommendation (Phase 2.4)
    "RecommendationEngine",
    "RecommendationReason",
    # Result Comparator (Shadow Testing)
    "ResultComparator",
    "RootCause",
    "SecurityConfig",
    "SecurityError",
    "SecurityValidationResult",
    "SkillExecutionProvider",
    "SkillExecutionSample",
    "SkillOptimizationStorage",
    # Main classes
    "SkillOptimizer",
    "SkillQualityAggregate",
    "SkillQualityAggregator",
    "SkillQualityDataSource",
    "SkillQualityScore",
    "SkillQualitySnapshot",
    "SkillSecurityValidator",
    # Types
    "SkillType",
    "SkillVersion",
    "StorageConnectionError",
    "StorageError",
    "StorageTimeoutError",
    "StreamingAggregator",
    "StructuredComparator",
    "Timer",
    "ToolUsageInsight",
    "TopSession",
    "UniversalAggregator",
    "UserQualityAggregate",
    "UserRateLimiter",
    "VersionConflictError",
    "aggregate_health_checks",
    "get_metrics_collector",
    "get_rate_limiter",
    "structured_log",
    "validate_health_check_result",
]
