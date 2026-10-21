"""Strongly typed contracts for subagent execution heartbeat watchdog and zombie cleanup.

Benchmarked against Nous community multi-agent runtime reliability invariants:
- Continuous millisecond-level heartbeat tracking for derived subagents.
- Progressive tiered timeout ladder (Warning -> Soft Cancel -> Hard Terminate).
- Zombie worker detection and forced process reaping to prevent runaway cloud/CPU costs.
- Graceful degradation receipt for the parent agent to proceed without freezing.

[OUTPUT]
- SubagentHealthState: Lifecycle health classification of a subagent task.
- TimeoutLadderConfig: Tiered threshold intervals for warning, soft cancel, and termination.
- HeartbeatPulse: Timestamped heartbeat signal emitted by an active subagent.
- SubagentExecutionReceipt: Audit receipt recording watchdog interventions and final status.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- SubagentHealthState
- TimeoutLadderConfig
- HeartbeatPulse
- SubagentExecutionReceipt

[POS]
Strongly typed contracts for subagent execution heartbeat watchdog and zombie cleanup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SubagentHealthState(StrEnum):
    """Health and lifecycle state of a monitored subagent."""

    HEALTHY = "healthy"
    """Subagent is actively emitting regular heartbeat pulses."""

    WARNING = "warning"
    """Heartbeat interval exceeded; subagent suspected of blocking."""

    SOFT_CANCELING = "soft_canceling"
    """Graceful cancellation dispatched, awaiting checkpoint cleanup."""

    TERMINATED = "terminated"
    """Hard-terminated by watchdog due to unresponsive zombie state."""

    RECOVERED = "recovered"
    """Subagent succeeded or gracefully completed after intervention."""


@dataclass(frozen=True)
class TimeoutLadderConfig:
    """Configures the progressive timeout ladder thresholds in seconds."""

    warning_threshold_s: float = 2.0
    soft_cancel_threshold_s: float = 4.0
    hard_terminate_threshold_s: float = 6.0


@dataclass(frozen=True)
class HeartbeatPulse:
    """Instantaneous heartbeat pulse payload."""

    subagent_id: str
    timestamp: float = field(default_factory=time.time)
    progress_note: str = ""


@dataclass(frozen=True)
class SubagentExecutionReceipt:
    """Audit report generated upon subagent completion or watchdog termination."""

    subagent_id: str
    parent_session_id: str
    final_state: SubagentHealthState
    total_pulses: int
    elapsed_seconds: float
    zombie_killed: bool
    degraded_error_summary: str = ""
    timestamp: float = field(default_factory=time.time)
