"""Type definitions for Multi-Tenant Data Isolation and Cross-Contamination Inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProbeScenarioType = Literal[
    "zero_context_query",
    "vague_wildcard_search",
    "adversarial_injection",
    "cross_agent_boundary",
]


@dataclass(slots=True, frozen=True)
class TenantMemoryContext:
    """Security identity context for memory partitioning and access control."""

    user_id: str
    agent_id: str
    session_id: str | None = None
    scope: Literal["user", "agent", "session", "global"] = "agent"


@dataclass(slots=True, frozen=True)
class PartitionKeySpec:
    """Tamper-evident compiled composite partition key for physical storage engines."""

    composite_key: str
    user_id: str
    agent_id: str
    scope: str
    namespace_digest: str


@dataclass(slots=True, frozen=True)
class ProbeScenarioResult:
    """Result of an individual synthetic adversarial probe run."""

    scenario: ProbeScenarioType
    probe_query: str
    expected_matches: int
    actual_matches: int
    cross_hits: int
    is_isolated: bool
    details: str


@dataclass(slots=True, frozen=True)
class DataSovereigntyReport:
    """Data sovereignty and physical isolation self-inspection audit card."""

    environment_type: Literal["local_standalone", "cloud_dedicated_sandbox"]
    total_probes_run: int
    cross_hits_count: int
    isolation_pass_rate: float
    is_safe: bool
    partition_integrity_verified: bool
    scenario_results: tuple[ProbeScenarioResult, ...] = field(default_factory=tuple)
    summary: str = ""
