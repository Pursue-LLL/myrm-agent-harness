"""Domain models for memory skill triad and physical scope isolation.

[POS]
Data structures representing scope coordinates, namespace hashes, physical
partition layout, provider degraded state reports, machine CLI envelopes,
and integration pipeline survey findings.

[INPUT]
- None (pure domain models)

[OUTPUT]
- ScopeCoordinates
- ScopePartitionInfo
- ProviderDegradedInfo
- DegradedStateReport
- MachineCliEnvelope
- SurveyFinding
- IntegrationSeams
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DegradedSeverity(StrEnum):
    """Severity levels for memory provider degradation."""

    HEALTHY = "healthy"
    DEGRADED_LEXICAL_FALLBACK = "degraded_lexical_fallback"
    OFFLINE_BLOCKED = "offline_blocked"


@dataclass(frozen=True)
class ScopeCoordinates:
    """Canonical multi-dimensional coordinates defining a memory scope."""

    tenant_id: str = "default_tenant"
    workspace_id: str = "default_workspace"
    agent_id: str = "default_agent"
    session_id: str = "default_session"

    def as_dict(self) -> dict[str, str]:
        """Convert coordinates to plain key-value dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
        }

    def has_non_empty_identity(self) -> bool:
        """Verify at least one dimension is populated."""
        return any(
            val.strip()
            for val in (self.tenant_id, self.workspace_id, self.agent_id, self.session_id)
        )


@dataclass(frozen=True)
class ScopePartitionInfo:
    """Physical filesystem layout and SQLite location for an isolated scope."""

    coordinates: ScopeCoordinates
    namespace_hash: str
    partition_dir: str
    sqlite_path: str
    is_isolated: bool = True


@dataclass(frozen=True)
class ProviderDegradedInfo:
    """Individual provider operational status and degradation metadata."""

    provider_type: str
    configured_vendor: str
    active_vendor: str
    is_degraded: bool
    degradation_reason: str = ""


@dataclass(frozen=True)
class DegradedStateReport:
    """Consolidated degradation assessment across all memory subsystems."""

    overall_status: DegradedSeverity
    providers: tuple[ProviderDegradedInfo, ...] = field(default_factory=tuple)
    strict_mode: bool = False
    summary: str = ""

    @property
    def has_any_degradation(self) -> bool:
        """Check whether any provider is operating in degraded mode."""
        return any(p.is_degraded for p in self.providers)


@dataclass(frozen=True)
class MachineCliEnvelope:
    """Standardized machine envelope for CLI and tool-loop integrations."""

    status: str
    command: str
    duration_ms: int
    scope: dict[str, str]
    payload: dict[str, str] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    exit_code: int = 0
    auto_confirmed: bool = True

    @property
    def is_success(self) -> bool:
        """Check whether execution succeeded."""
        return self.status == "success" and self.exit_code == 0


@dataclass(frozen=True)
class SurveyFinding:
    """Structural findings from 4-question pre-integration repository survey."""

    message_assembly_site: str
    identity_binding: str
    installed_provider: str
    write_hook_seam: str
    is_ready_for_wiring: bool = True


@dataclass(frozen=True)
class IntegrationSeams:
    """Verification state for read and write integration seams."""

    read_seam_configured: bool
    write_seam_configured: bool
    token_budget: int
    roundtrip_test_passed: bool = False

    @property
    def is_fully_verified(self) -> bool:
        """Check whether both seams and roundtrip test are validated."""
        return (
            self.read_seam_configured
            and self.write_seam_configured
            and self.roundtrip_test_passed
        )
