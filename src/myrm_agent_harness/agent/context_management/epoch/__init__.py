"""Package facade for epoch.

[INPUT]
- agent.context_management.epoch.epoch_request_compiler::DeterministicToolCompiler, EpochHeaderTracker,
  PrefixDigestTelemetricEngine, RuntimeContextProjection (POS: Compiles and orders tool definitions
  deterministically for Prompt Cache.)
- agent.context_management.epoch.epoch_tracking_types::CacheAttributionTelemetry, EpochHeaderRecord,
  EpochPhaseKind, FirstDiffAreaKind, OrderedToolSchema, ProjectedContextDelta, ProjectionChangeKind (POS:
  Types and models for epoch tracking.)

[OUTPUT]
- Re-exports: CacheAttributionTelemetry, DeterministicToolCompiler, EpochHeaderRecord, EpochHeaderTracker,
  EpochPhaseKind, FirstDiffAreaKind, OrderedToolSchema, PrefixDigestTelemetricEngine, ProjectedContextDelta,
  ProjectionChangeKind, RuntimeContextProjection

[POS]
Package facade for epoch.
"""

# ============================================================================
# Epoch Tracking & Request Compiler Package (Item 157)
# ============================================================================

from .epoch_request_compiler import (
    DeterministicToolCompiler,
    EpochHeaderTracker,
    PrefixDigestTelemetricEngine,
    RuntimeContextProjection,
)
from .epoch_tracking_types import (
    CacheAttributionTelemetry,
    EpochHeaderRecord,
    EpochPhaseKind,
    FirstDiffAreaKind,
    OrderedToolSchema,
    ProjectedContextDelta,
    ProjectionChangeKind,
)

__all__ = [
    "CacheAttributionTelemetry",
    "DeterministicToolCompiler",
    "EpochHeaderRecord",
    "EpochHeaderTracker",
    "EpochPhaseKind",
    "FirstDiffAreaKind",
    "OrderedToolSchema",
    "PrefixDigestTelemetricEngine",
    "ProjectedContextDelta",
    "ProjectionChangeKind",
    "RuntimeContextProjection",
]
