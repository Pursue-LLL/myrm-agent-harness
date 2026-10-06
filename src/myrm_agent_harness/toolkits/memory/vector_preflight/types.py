# [POS] src/myrm_agent_harness/toolkits/memory/vector_preflight/types.py
# [INPUT] enum, dataclasses
# [OUTPUT] PreflightHealthStatus, SanitizedEndpointResult, DimensionIntegrityReport

from dataclasses import dataclass
from enum import StrEnum


class PreflightHealthStatus(StrEnum):
    """Health evaluation status for vector store preflight checks."""

    HEALTHY = "healthy"
    SANITIZED_WARNING = "sanitized_warning"
    MISMATCH_BLOCKED = "mismatch_blocked"
    INVALID_CONFIGURATION = "invalid_configuration"


@dataclass(frozen=True)
class SanitizedEndpointResult:
    """Result of endpoint and host loopback sanitization."""

    raw_endpoint: str
    sanitized_endpoint: str
    was_modified: bool
    modification_reason: str


@dataclass(frozen=True)
class DimensionIntegrityReport:
    """Rigid preflight dimension verification outcome."""

    is_valid: bool
    actual_dims: int
    expected_dims: int
    status: PreflightHealthStatus
    diagnosis: str
    suggested_action: str
