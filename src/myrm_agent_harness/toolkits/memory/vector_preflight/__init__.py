"""Public facade of the vector preflight subsystem.

[INPUT]
- toolkits.memory.vector_preflight.probe::DimensionIntegrityProbe (POS: Rigidly evaluates and asserts vector
  dimension consistency before store operations.)
- toolkits.memory.vector_preflight.sanitizer::IPv4LoopbackSanitizer (POS: Sanitizes connection endpoints to
  eliminate IPv6 ::1 localhost resolution traps in container environments.)
- toolkits.memory.vector_preflight.types::DimensionIntegrityReport, PreflightHealthStatus,
  SanitizedEndpointResult (POS: Typed data contracts for the vector preflight subsystem.)

[OUTPUT]
- Package facade re-exporting 5 public names: DimensionIntegrityProbe, DimensionIntegrityReport,
  IPv4LoopbackSanitizer, PreflightHealthStatus, SanitizedEndpointResult

[POS]
Public facade of the vector preflight subsystem.
"""

from .probe import DimensionIntegrityProbe
from .sanitizer import IPv4LoopbackSanitizer
from .types import (
    DimensionIntegrityReport,
    PreflightHealthStatus,
    SanitizedEndpointResult,
)

__all__ = [
    "DimensionIntegrityProbe",
    "DimensionIntegrityReport",
    "IPv4LoopbackSanitizer",
    "PreflightHealthStatus",
    "SanitizedEndpointResult",
]
