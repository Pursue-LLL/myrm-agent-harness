"""Health checker abstract base class and result models.

[INPUT]
None

[OUTPUT]
- HealthChecker: Abstract base class for all health checkers
- HealthCheckResult: Immutable health check result
- RecoveryResult: Immutable recovery operation result

[POS]
健康检查抽象层。定义check()和recover()两个核心方法，所有具体的health checker必须实现这两个方法。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class HealthStatus(StrEnum):
    """Health status enumeration."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class RecoveryStatus(StrEnum):
    """Recovery status enumeration."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class HealthCheckResult:
    """Immutable health check result.

    Attributes:
        status: Health status
        message: Human-readable message
        details: Additional details (e.g., error message, process info)
        checked_at: Timestamp of check
    """

    status: HealthStatus
    message: str
    details: dict[str, object] | None = None
    checked_at: datetime = None

    def __post_init__(self) -> None:
        if self.checked_at is None:
            object.__setattr__(self, "checked_at", datetime.utcnow())

    def is_healthy(self) -> bool:
        """Check if status is healthy."""
        return self.status == HealthStatus.HEALTHY


@dataclass(frozen=True)
class RecoveryResult:
    """Immutable recovery operation result.

    Attributes:
        status: Recovery status
        message: Human-readable message
        actions_taken: List of recovery actions performed
        details: Additional details
        recovered_at: Timestamp of recovery
    """

    status: RecoveryStatus
    message: str
    actions_taken: list[str] | None = None
    details: dict[str, object] | None = None
    recovered_at: datetime = None

    def __post_init__(self) -> None:
        if self.recovered_at is None:
            object.__setattr__(self, "recovered_at", datetime.utcnow())

    def is_success(self) -> bool:
        """Check if recovery was successful."""
        return self.status == RecoveryStatus.SUCCESS


class HealthChecker(ABC):
    """Abstract base class for health checkers.

    All concrete health checkers must implement check() and recover().
    """

    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """Check resource health status.

        Returns:
            HealthCheckResult with current status
        """
        pass

    @abstractmethod
    async def recover(self) -> RecoveryResult:
        """Attempt to recover from unhealthy state.

        Returns:
            RecoveryResult with recovery status and actions taken
        """
        pass

    def get_name(self) -> str:
        """Get checker name (default to class name)."""
        return self.__class__.__name__
