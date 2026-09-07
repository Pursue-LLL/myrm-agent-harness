"""Provider Balance Probe Protocol and Data Contracts.

[INPUT]
- None (Standard library dataclasses, enum, typing)

[OUTPUT]
- ProviderBalanceStatus: Status enum ('healthy', 'warning', 'critical', 'unsupported')
- ProviderBalanceResult: Standard normalized result dataclass for provider balance probe
- ProviderBalanceProbeProtocol: Generic protocol for LLM provider balance query engines

[POS]
Harness framework layer contracts for multi-provider live balance probing and soft quota HUD telemetry.
Zero prompt contamination, zero LLM token overhead, fail-open design.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ProviderBalanceStatus(StrEnum):
    """Normalized health status of a provider account balance."""

    HEALTHY = "healthy"  # Balance is sufficient (> 20% or > $2.00 / ¥10.00)
    WARNING = "warning"  # Balance approaching threshold (<= 20% or <= $2.00 / ¥10.00)
    CRITICAL = (
        "critical"  # Balance severely low or depleted (<= 10% or <= $0.50 / ¥2.00)
    )
    UNSUPPORTED = "unsupported"  # Provider lacks direct balance query endpoint (falls back to local estimate)


@dataclass(frozen=True, slots=True)
class ProviderBalanceResult:
    """Normalized balance probe observation for a single LLM provider."""

    provider_id: str
    balance: float | None
    currency: str  # "USD", "CNY", "TOKENS", "UNLIMITED", "UNKNOWN"
    status: ProviderBalanceStatus
    is_estimated: bool = False
    details: str | None = None
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            object.__setattr__(
                self,
                "updated_at",
                datetime.now(UTC).isoformat(),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "balance": self.balance,
            "currency": self.currency,
            "status": self.status.value,
            "is_estimated": self.is_estimated,
            "details": self.details,
            "updated_at": self.updated_at,
        }


@runtime_checkable
class ProviderBalanceProbeProtocol(Protocol):
    """Protocol for provider-specific balance probe implementations."""

    @property
    def supported_provider_ids(self) -> frozenset[str]:
        """Set of canonical provider IDs supported by this probe."""
        ...

    async def probe(
        self,
        provider_id: str,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> ProviderBalanceResult:
        """Perform a single read-only probe for provider balance with fail-open guarantee."""
        ...
