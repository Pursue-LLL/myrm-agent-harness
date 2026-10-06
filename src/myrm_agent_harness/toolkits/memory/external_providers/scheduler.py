"""Scheduler for single active external memory provider and 5-stage lifecycle.

[INPUT]
- external_providers.models::{DerivedObservationRecord, EvidenceRecord, MemoryScopeContext}
- external_providers.protocols::{ExternalMemoryProviderProtocol, PrefetchResult, ProviderExecutionMetrics}
- external_providers.lineage_manager::{SupersedesLineageManager}

[OUTPUT]
- SingleActiveProviderScheduler: coordinates 5-stage pipeline with timeout circuit breaking and fallback.

[POS]
Coordinates unified lifecycle pipeline: prefetch -> inject -> sync -> extract -> mirror_write.
Enforces single active external provider pattern, 300ms circuit breaking, and trivial prompt gating.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.external_providers.lineage_manager import (
    SupersedesLineageManager,
)
from myrm_agent_harness.toolkits.memory.external_providers.models import (
    DerivedObservationRecord,
    EvidenceRecord,
    MemoryScopeContext,
)
from myrm_agent_harness.toolkits.memory.external_providers.protocols import (
    ExternalMemoryProviderProtocol,
    PrefetchResult,
    ProviderExecutionMetrics,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


_TRIVIAL_PROMPT_PATTERN = re.compile(
    r"^(yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|"
    r"hi|hey|hello|yo|sup|continue|go ahead|do it|proceed|got it|"
    r"cool|nice|great|done|next|lgtm|k)[\s!?.:;,'\"~`]*$",
    re.IGNORECASE,
)


def is_trivial_prompt(text: str) -> bool:
    """Check whether text is a trivial acknowledgement or bare greeting."""
    stripped = text.strip()
    if not stripped or stripped.startswith("/"):
        return True
    return bool(_TRIVIAL_PROMPT_PATTERN.match(stripped))


class SingleActiveProviderScheduler:
    """Orchestrates single active external memory provider alongside resident internal memory."""

    def __init__(
        self,
        lineage_manager: SupersedesLineageManager | None = None,
        default_timeout_ms: int = 300,
    ) -> None:
        self._lineage_manager: SupersedesLineageManager = (
            lineage_manager if lineage_manager is not None else SupersedesLineageManager()
        )
        self._default_timeout_ms: int = default_timeout_ms
        self._providers: dict[str, ExternalMemoryProviderProtocol] = {}
        self._active_provider_name: str | None = None
        self._cached_prefetches: dict[str, PrefetchResult] = {}

    @property
    def lineage_manager(self) -> SupersedesLineageManager:
        """Return the underlying lineage manager."""
        return self._lineage_manager

    @property
    def active_provider(self) -> ExternalMemoryProviderProtocol | None:
        """Return the currently active external memory provider instance."""
        if self._active_provider_name is None:
            return None
        return self._providers.get(self._active_provider_name)

    def register_provider(self, provider: ExternalMemoryProviderProtocol) -> None:
        """Register a pluggable external provider."""
        self._providers[provider.name] = provider

    def activate_provider(self, name: str) -> None:
        """Activate exactly one external provider, deactivating any prior active one."""
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' is not registered.")
        provider = self._providers[name]
        if not provider.is_available():
            raise RuntimeError(f"Provider '{name}' is registered but currently unavailable.")
        self._active_provider_name = name

    def deactivate_provider(self) -> None:
        """Deactivate active external provider; fallback purely to internal resident memory."""
        self._active_provider_name = None

    async def run_prefetch(
        self,
        session_id: str,
        query: str,
        scope: MemoryScopeContext,
        timeout_ms: int | None = None,
    ) -> PrefetchResult:
        """Stage 1: Pre-fetch relevant observations with circuit breaking and trivial prompt gating."""
        effective_timeout_ms = timeout_ms if timeout_ms is not None else self._default_timeout_ms

        if is_trivial_prompt(query):
            res = PrefetchResult(
                provider_name=self._active_provider_name or "none",
                observations=(),
                latency_ms=0.0,
                is_fallback=False,
                cached=False,
            )
            self._cached_prefetches[session_id] = res
            return res

        provider = self.active_provider
        if provider is None:
            local_obs = self._lineage_manager.filter_by_scope(scope)
            res = PrefetchResult(
                provider_name="builtin_internal",
                observations=local_obs,
                latency_ms=0.0,
                is_fallback=False,
                cached=False,
            )
            self._cached_prefetches[session_id] = res
            return res

        start_time = time.perf_counter()
        try:
            coro = provider.prefetch(session_id, query, scope)
            records = await asyncio.wait_for(coro, timeout=effective_timeout_ms / 1000.0)
            latency = (time.perf_counter() - start_time) * 1000.0
            res = PrefetchResult(
                provider_name=provider.name,
                observations=tuple(records),
                latency_ms=latency,
                is_fallback=False,
                cached=False,
            )
        except (TimeoutError, Exception):
            latency = (time.perf_counter() - start_time) * 1000.0
            fallback_records = self._lineage_manager.filter_by_scope(scope)
            res = PrefetchResult(
                provider_name=provider.name,
                observations=fallback_records,
                latency_ms=latency,
                is_fallback=True,
                cached=False,
            )

        self._cached_prefetches[session_id] = res
        return res

    def format_inject(
        self,
        session_id: str,
        observations: Sequence[DerivedObservationRecord] | None = None,
    ) -> str:
        """Stage 2: Format recalled observations into a deterministic prompt block."""
        provider = self.active_provider
        effective_obs: Sequence[DerivedObservationRecord]
        if observations is not None:
            effective_obs = observations
        else:
            cached = self._cached_prefetches.get(session_id)
            effective_obs = cached.observations if cached is not None else ()

        if not effective_obs:
            return ""

        if provider is not None:
            try:
                formatted = provider.format_inject(effective_obs)
                if formatted.strip():
                    return formatted
            except Exception:
                pass

        lines: list[str] = ["<external_memory_context>"]
        for obs in effective_obs:
            lines.append(f"  <memory category='{obs.category}' id='{obs.observation_id}'>{obs.content}</memory>")
        lines.append("</external_memory_context>")
        return "\n".join(lines)

    async def run_sync_turn(self, evidence: EvidenceRecord) -> None:
        """Stage 3: Incrementally sync a completed turn to evidence tier and active provider."""
        self._lineage_manager.record_evidence(evidence)
        provider = self.active_provider
        if provider is not None:
            with contextlib.suppress(Exception):
                await provider.sync_turn(evidence)

    async def run_extract_session(
        self,
        session_id: str,
        evidences: Sequence[EvidenceRecord],
        scope: MemoryScopeContext,
    ) -> Sequence[DerivedObservationRecord]:
        """Stage 4: Extract structured observations at session boundaries."""
        provider = self.active_provider
        if provider is None:
            return ()

        try:
            extracted = await provider.extract_session(session_id, evidences, scope)
            for obs in extracted:
                self._lineage_manager.publish_observation(obs)
            return extracted
        except Exception:
            return ()

    async def run_mirror_write(
        self,
        records: Sequence[DerivedObservationRecord],
    ) -> None:
        """Stage 5: Mirror external observations to local storage for offline resilience."""
        for rec in records:
            self._lineage_manager.publish_observation(rec)

        provider = self.active_provider
        if provider is not None:
            with contextlib.suppress(Exception):
                await provider.mirror_write(records)

    async def execute_full_lifecycle(
        self,
        session_id: str,
        query: str,
        scope: MemoryScopeContext,
        evidence: EvidenceRecord,
    ) -> ProviderExecutionMetrics:
        """Execute and benchmark full 5-stage lifecycle for telemetry verification."""
        provider_name = self._active_provider_name or "builtin_internal"
        latencies: dict[str, float] = {}

        t0 = time.perf_counter()
        prefetch_res = await self.run_prefetch(session_id, query, scope)
        latencies["prefetch"] = (time.perf_counter() - t0) * 1000.0

        t1 = time.perf_counter()
        _ = self.format_inject(session_id, prefetch_res.observations)
        latencies["inject"] = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        await self.run_sync_turn(evidence)
        latencies["sync"] = (time.perf_counter() - t2) * 1000.0

        t3 = time.perf_counter()
        extracted = await self.run_extract_session(session_id, (evidence,), scope)
        latencies["extract"] = (time.perf_counter() - t3) * 1000.0

        t4 = time.perf_counter()
        await self.run_mirror_write(extracted)
        latencies["mirror"] = (time.perf_counter() - t4) * 1000.0

        return ProviderExecutionMetrics(
            provider_name=provider_name,
            stage_latencies_ms=latencies,
            tokens_consumed=0,
            records_synced=1,
            records_extracted=len(extracted),
            records_mirrored=len(extracted),
            executed_at=_utc_now(),
        )
