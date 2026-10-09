"""Bitemporal truth maintenance and justification reasoning package.

[POS]
Clean public interface exposing interval algebra, truth maintenance graphs,
multi-criteria bitemporal filters, and facade conveniences.

[INPUT]
- .facade
- .interval_algebra
- .models
- .support_graph
- .temporal_filter

[OUTPUT]
Exported public API symbols.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.facade import (
    BitemporalTruthMaintenanceFacade,
    get_bitemporal_truth_maintenance_facade,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.interval_algebra import (
    create_interval,
    intersect_intervals,
    is_bitemporal_point_active,
    shift_interval,
    span_intervals,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.models import (
    BitemporalCoordinates,
    BitemporalEvidenceRecord,
    EvidenceRecord,
    EvidenceType,
    SupportDependency,
    TemporalQueryCriteria,
    TimeInterval,
    TruthMaintenanceSnapshot,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.support_graph import (
    TruthMaintenanceGraph,
)
from myrm_agent_harness.toolkits.memory.bitemporal_truth_maintenance.temporal_filter import (
    BitemporalFilterEngine,
)

__all__ = [
    "BitemporalCoordinates",
    "BitemporalEvidenceRecord",
    "BitemporalFilterEngine",
    "BitemporalTruthMaintenanceFacade",
    "EvidenceRecord",
    "EvidenceType",
    "SupportDependency",
    "TemporalQueryCriteria",
    "TimeInterval",
    "TruthMaintenanceGraph",
    "TruthMaintenanceSnapshot",
    "create_interval",
    "get_bitemporal_truth_maintenance_facade",
    "intersect_intervals",
    "is_bitemporal_point_active",
    "shift_interval",
    "span_intervals",
]
