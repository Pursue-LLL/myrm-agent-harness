"""Sandbox resource affinity and adaptive CPU/memory throttling watchdog suite.

[OUTPUT]
- ProcessPriorityLevel: OS-level scheduling priority enum.
- ThrottleAction: Watchdog mitigation action enum.
- SystemLoadSnapshot: Host resource consumption snapshot.
- WatchdogVerdict: Watchdog pacing and concurrency directive.
- ProcessPriorityGuard: Utility for process priority degradation.
- AdaptiveThrottlingWatchdog: Real-time resource watchdog and regulator.

[INPUT]
- __future__

[OUTPUT]
- (模块级副作用与注册)

[POS]
Sandbox resource affinity and adaptive CPU/memory throttling watchdog suite.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.throttling_watchdog.adaptive_throttling_watchdog import (
    AdaptiveThrottlingWatchdog,
)
from myrm_agent_harness.runtime.throttling_watchdog.process_priority_guard import (
    ProcessPriorityGuard,
)
from myrm_agent_harness.runtime.throttling_watchdog.throttling_types import (
    ProcessPriorityLevel,
    SystemLoadSnapshot,
    ThrottleAction,
    WatchdogVerdict,
)

__all__ = [
    "AdaptiveThrottlingWatchdog",
    "ProcessPriorityGuard",
    "ProcessPriorityLevel",
    "SystemLoadSnapshot",
    "ThrottleAction",
    "WatchdogVerdict",
]
