"""Type definitions for Air-Gapped Sovereign Intelligence and Zero-Egress Compliance.

[INPUT]
None.

[OUTPUT]
- EgressControlTier, EgressAttemptRecord, ZeroEgressAssertionResult, OfflineModelMetadata
- AirGappedViolationError, ExternalEgressBlockedError

[POS]
Harness core security subsystem for strict zero-egress enforcement and air-gapped sovereign execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class EgressControlTier(StrEnum):
    """Network egress governance tiers."""

    STANDARD = "standard"  # Default allowlist and credential injection
    CONSERVATIVE = "conservative"  # Fail-closed approval for untrusted external destinations
    AIR_GAPPED_SOVEREIGN = "air_gapped_sovereign"  # Absolute zero external egress, loopback only


@dataclass(frozen=True, slots=True)
class EgressAttemptRecord:
    """Telemetry record of a network egress inspection."""

    attempt_id: str
    destination_host: str
    destination_port: int
    protocol: str
    allowed: bool
    reason: str
    tier: EgressControlTier
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class ZeroEgressAssertionResult:
    """Formal audit proof verifying 0 external bytes or connections transpired."""

    total_attempts: int
    blocked_attempts: int
    external_egress_count: int
    is_zero_egress_compliant: bool
    assertion_hash: str
    verified_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class OfflineModelMetadata:
    """Pre-packaged model runtime specification requiring zero network metadata discovery."""

    model_id: str
    context_window: int
    max_output_tokens: int
    tokenizer_type: str
    is_offline_ready: bool = True


class AirGappedViolationError(Exception):
    """Base exception for air-gapped compliance violations."""


class ExternalEgressBlockedError(AirGappedViolationError):
    """Raised when an outbound network connection is blocked in sovereign air-gapped mode."""

    def __init__(self, host: str, port: int, reason: str) -> None:
        super().__init__(f"Zero-Egress Guard BLOCKED connection to '{host}:{port}': {reason}")
        self.host = host
        self.port = port
        self.reason = reason
