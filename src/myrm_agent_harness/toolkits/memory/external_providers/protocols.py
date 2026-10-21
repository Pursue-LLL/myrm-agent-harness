"""Protocols and interfaces for external memory providers.

[INPUT]
- external_providers.models::{DerivedObservationRecord, EvidenceRecord, MemoryScopeContext, ProviderKind}

[OUTPUT]
- PrefetchResult: container for recalled observations and execution latency.
- ProviderExecutionMetrics: telemetry metrics for provider calls.
- ExternalMemoryProviderProtocol: 5-stage lifecycle protocol for external memory providers.

[POS]
Defines the unified 5-stage plugin contract: prefetch -> inject -> sync -> extract -> mirror_write.
Strictly decoupled from LLM tool definitions to prevent function calling schema conflicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryScopeContext,
    ProviderKind,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PrefetchResult:
    """Result container returned by the prefetch stage."""

    provider_name: str
    observations: tuple[DerivedObservationRecord, ...]
    latency_ms: float
    is_fallback: bool = False
    cached: bool = False


@dataclass(frozen=True, slots=True)
class ProviderExecutionMetrics:
    """Metrics tracking for lifecycle pipeline execution."""

    provider_name: str
    stage_latencies_ms: dict[str, float] = field(default_factory=dict)
    tokens_consumed: int = 0
    records_synced: int = 0
    records_extracted: int = 0
    records_mirrored: int = 0
    executed_at: datetime = field(default_factory=_utc_now)


@runtime_checkable
class ExternalMemoryProviderProtocol(Protocol):
    """Unified 5-stage pluggable external memory provider contract.

    Follows the single-active-provider architecture: built-in memory stays
    resident, while one external provider acts as an augmented derived index.
    """

    @property
    def name(self) -> str:
        """Provider identifier (e.g. 'hindsight', 'mem0', 'open_viking')."""
        ...

    @property
    def kind(self) -> ProviderKind:
        """Provider architecture archetype."""
        ...

    def is_available(self) -> bool:
        """Check whether the external provider is configured and reachable."""
        ...

    async def prefetch(
        self,
        session_id: str,
        query: str,
        scope: MemoryScopeContext,
    ) -> Sequence[DerivedObservationRecord]:
        """Stage 1: Pre-fetch relevant observations before LLM reasoning."""
        ...

    def format_inject(
        self,
        observations: Sequence[DerivedObservationRecord],
    ) -> str:
        """Stage 2: Format recalled observations into a deterministic prompt block."""
        ...

    async def sync_turn(
        self,
        evidence: EvidenceRecord,
    ) -> None:
        """Stage 3: Incrementally sync a completed dialog turn non-blockingly."""
        ...

    async def extract_session(
        self,
        session_id: str,
        evidences: Sequence[EvidenceRecord],
        scope: MemoryScopeContext,
    ) -> Sequence[DerivedObservationRecord]:
        """Stage 4: Extract structured observations at session boundaries."""
        ...

    async def mirror_write(
        self,
        records: Sequence[DerivedObservationRecord],
    ) -> None:
        """Stage 5: Mirror external records to local storage for offline resilience."""
        ...

    async def shutdown(self) -> None:
        """Gracefully release connections and background workers."""
        ...
