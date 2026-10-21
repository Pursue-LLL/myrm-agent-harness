"""Data types and schemas for Hierarchical Concurrency and Fan-Out Throttle Isolation Suite.

Defines multi-tier resource categories, quota descriptors, lease tickets,
and fan-out braking verdicts for mission-critical agent reliability.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ResourceTier
- BrakeSeverity
- TierQuotaConfig
- ResourceLeaseTicket
- FanOutBrakeVerdict
- FanOutLimitExceededError

[POS]
Data types and schemas for Hierarchical Concurrency and Fan-Out Throttle Isolation Suite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ResourceTier(StrEnum):
    """Resource hierarchy layer subject to independent quota governance."""

    GATEWAY_INGRESS = "gateway_ingress"  # Layer 1: Inbound HTTP client connections
    AGENT_INSTANCE = "agent_instance"  # Layer 2: Actively reasoning agent loops
    LLM_PROVIDER = "llm_provider"  # Layer 3: Outbound calls to upstream model API
    TOOL_IO = "tool_io"  # Layer 4a: Network-bound I/O tools (Web search, fetch)
    TOOL_SANDBOX_CPU = "tool_sandbox_cpu"  # Layer 4b: CPU/Memory intensive sandbox execution


class BrakeSeverity(StrEnum):
    """Severity level of the fan-out braking policy."""

    NORMAL = "normal"  # Healthy task derivation rate
    WARNING = "warning"  # Elevated fan-out detected; logging and telemetry enabled
    SOFT_BRAKE = "soft_brake"  # High fan-out; enforce backpressure delays
    HARD_BRAKE_FUSED = "hard_brake_fused"  # Runaway fan-out tripped; abort derivation to prevent crash


@dataclass(frozen=True)
class TierQuotaConfig:
    """Configuration descriptor for a specific resource tier quota."""

    tier: ResourceTier
    max_concurrency: int
    high_watermark_ratio: float = 0.8  # Ratio at which backpressure is declared (80%)


@dataclass(frozen=True)
class ResourceLeaseTicket:
    """Proof of acquired concurrency lease, guaranteed to be released upon scope exit."""

    lease_id: str
    tier: ResourceTier
    session_id: str
    acquired_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FanOutBrakeVerdict:
    """Evaluation result assessing current session-level task fan-out."""

    severity: BrakeSeverity
    session_id: str
    current_derived_tasks: int
    soft_limit: int
    hard_limit: int
    should_throttle: bool
    should_fuse: bool
    rationale: str
    evaluated_at: float = field(default_factory=time.time)


class FanOutLimitExceededError(RuntimeError):
    """Raised when a single session exceeds the hard fan-out safety budget."""

    def __init__(self, session_id: str, count: int, limit: int) -> None:
        super().__init__(
            f"Session '{session_id}' exceeded hard fan-out safety budget "
            f"({count} > {limit} derived tasks). Execution halted to prevent cascading server failure."
        )
        self.session_id = session_id
        self.count = count
        self.limit = limit
