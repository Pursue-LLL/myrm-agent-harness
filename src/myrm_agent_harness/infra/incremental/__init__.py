"""Incremental state tracking for monitoring data changes.

Provides generic mechanisms for detecting and reporting only the delta
between successive runs of monitoring tasks (RSS feeds, website changes, etc.).

Core abstractions:
- ``IncrementalMonitor`` — protocol for computing deltas
- ``SetMonitor`` — built-in implementation for line-delimited item sets
- ``IncrementalMonitorManager`` — lifecycle management with TTL
"""

from myrm_agent_harness.infra.incremental.manager import IncrementalMonitorManager
from myrm_agent_harness.infra.incremental.protocols import IncrementalMonitor
from myrm_agent_harness.infra.incremental.set_monitor import SetMonitor
from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState, MonitorType, ResetReason

__all__ = [
    "IncrementalMonitor",
    "IncrementalMonitorManager",
    "MonitorConfig",
    "MonitorState",
    "MonitorType",
    "ResetReason",
    "SetMonitor",
]
