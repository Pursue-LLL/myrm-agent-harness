"""Health checking infrastructure.

[INPUT]
None

[OUTPUT]
- HealthChecker: Abstract base class for health checkers
- HealthCheckResult: Health check result model
- RecoveryResult: Recovery operation result model
- run_health_checks: Run all registered health checkers

[POS]
通用健康检查框架层。提供抽象接口和协调器，不依赖具体的存储技术。
"""

from myrm_agent_harness.infra.health.coordinator import run_health_checks
from myrm_agent_harness.infra.health.health_checker import (
    HealthChecker,
    HealthCheckResult,
    RecoveryResult,
)

__all__ = [
    "HealthCheckResult",
    "HealthChecker",
    "RecoveryResult",
    "run_health_checks",
]
