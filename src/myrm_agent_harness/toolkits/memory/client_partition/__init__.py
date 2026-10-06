"""Client-isolated workspace and memory namespace partitioning suite.

[INPUT]
- .types::{
      ClientPartitionConfig,
      ClientWorkspaceDescriptor,
      CrossClientLeakViolation,
      PartitionInspectionReport,
  }
- .workspace_resolver::{ClientWorkspaceResolver}
- .guard::{CrossClientLeakGuard}

[OUTPUT]
- Public exports for client partition, workspace isolation, and cross-client leakage defense

[POS]
Entry point of the client partition subsystem in memory toolkit.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.client_partition.guard import CrossClientLeakGuard
from myrm_agent_harness.toolkits.memory.client_partition.types import (
    ClientPartitionConfig,
    ClientWorkspaceDescriptor,
    CrossClientLeakViolation,
    PartitionInspectionReport,
)
from myrm_agent_harness.toolkits.memory.client_partition.workspace_resolver import (
    ClientWorkspaceResolver,
)

__all__ = [
    "ClientPartitionConfig",
    "ClientWorkspaceDescriptor",
    "ClientWorkspaceResolver",
    "CrossClientLeakGuard",
    "CrossClientLeakViolation",
    "PartitionInspectionReport",
]
