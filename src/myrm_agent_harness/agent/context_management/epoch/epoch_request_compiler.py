"""Compiles and orders tool definitions deterministically for Prompt Cache.

[INPUT]
- agent.context_management.epoch.epoch_tracking_types::CacheAttributionTelemetry, EpochHeaderRecord,
  EpochPhaseKind, FirstDiffAreaKind, OrderedToolSchema, ProjectedContextDelta, ProjectionChangeKind (POS:
  Types and models for epoch tracking.)

[OUTPUT]
- DeterministicToolCompiler: Compiles and orders tool definitions deterministically for Prompt Cache.
- RuntimeContextProjection: Applies delta projection contract for dynamic runtime contexts.
- EpochHeaderTracker: State machine maintaining generational EpochHeader across turns.
- PrefixDigestTelemetricEngine: Diagnoses and attributes prompt cache hits vs breaks.

[POS]
Compiles and orders tool definitions deterministically for Prompt Cache.
"""

# ============================================================================
# Epoch Request Compiler & Generational Tracking Engine (Item 157)
# Deterministic tool compiler, EpochHeader state machine, incremental
# RuntimeContextProjection contract, and PrefixDigest telemetric attribution.
# ============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Sequence

from .epoch_tracking_types import (
    CacheAttributionTelemetry,
    EpochHeaderRecord,
    EpochPhaseKind,
    FirstDiffAreaKind,
    OrderedToolSchema,
    ProjectedContextDelta,
    ProjectionChangeKind,
)

logger = logging.getLogger(__name__)


def _compute_sha256(content: str) -> str:
    """Compute standard SHA-256 hex digest for given UTF-8 text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DeterministicToolCompiler:
    """Compiles and orders tool definitions deterministically for Prompt Cache."""

    @staticmethod
    def compile_tools(
        tools: Sequence[tuple[str, str, dict[str, object] | str]],
    ) -> tuple[tuple[OrderedToolSchema, ...], str]:
        """Normalize, alphabetize, and compile tools into deterministic schemas.

        Args:
            tools: Sequence of (tool_name, description, parameters_schema) tuples.

        Returns:
            A tuple of (ordered_tool_schemas, aggregate_tools_digest).
        """
        ordered: list[OrderedToolSchema] = []
        # Sort strictly by tool name for zero order drift
        sorted_tools = sorted(tools, key=lambda item: item[0])

        digest_parts: list[str] = []
        for name, description, schema in sorted_tools:
            if isinstance(schema, str):
                try:
                    parsed = json.loads(schema)
                    schema_json = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
                except Exception:
                    schema_json = schema
            else:
                schema_json = json.dumps(schema, sort_keys=True, separators=(",", ":"))

            tool_digest = _compute_sha256(f"{name}:{description}:{schema_json}")
            digest_parts.append(tool_digest)

            ordered.append(
                OrderedToolSchema(
                    name=name,
                    description=description,
                    parameters_schema_json=schema_json,
                    schema_digest=tool_digest,
                )
            )

        aggregate_digest = _compute_sha256("||".join(digest_parts)) if digest_parts else _compute_sha256("")
        return tuple(ordered), aggregate_digest


class RuntimeContextProjection:
    """Applies delta projection contract for dynamic runtime contexts."""

    def __init__(self) -> None:
        self._snapshots: dict[str, str] = {}

    def project(self, namespace: str, content: str | None) -> ProjectedContextDelta:
        """Project dynamic context namespace.

        Only appends deltas on mutation; unchanged states cost 0 extra tokens.
        Cleared states emit an explicit invalidation marker.
        """
        previous_hash = self._snapshots.get(namespace)

        # Invalidation case
        if not content:
            if previous_hash is not None:
                self._snapshots.pop(namespace, None)
                marker = f"[RuntimeContext: {namespace} CLEARED]"
                return ProjectedContextDelta(
                    kind=ProjectionChangeKind.INVALIDATION_CLEAR,
                    namespace=namespace,
                    delta_content=marker,
                    snapshot_hash="",
                )
            return ProjectedContextDelta(
                kind=ProjectionChangeKind.NOOP,
                namespace=namespace,
                delta_content=None,
                snapshot_hash="",
            )

        current_hash = _compute_sha256(content)
        if previous_hash == current_hash:
            return ProjectedContextDelta(
                kind=ProjectionChangeKind.NOOP,
                namespace=namespace,
                delta_content=None,
                snapshot_hash=current_hash,
            )

        # State mutated: append structured delta at session tail
        self._snapshots[namespace] = current_hash
        tagged_delta = f"[RuntimeContext: {namespace}]\n{content}\n[/RuntimeContext: {namespace}]"
        return ProjectedContextDelta(
            kind=ProjectionChangeKind.DELTA_APPEND,
            namespace=namespace,
            delta_content=tagged_delta,
            snapshot_hash=current_hash,
        )

    def get_snapshot_hash(self, namespace: str) -> str | None:
        """Get currently registered hash snapshot for namespace."""
        return self._snapshots.get(namespace)


class EpochHeaderTracker:
    """State machine maintaining generational EpochHeader across turns."""

    def __init__(self, session_id: str) -> None:
        self._session_id: str = session_id
        self._generation: int = 0
        self._last_epoch: EpochHeaderRecord | None = None
        self._resumed: bool = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def current_generation(self) -> int:
        return self._generation

    @property
    def last_epoch(self) -> EpochHeaderRecord | None:
        return self._last_epoch

    def mark_resumed(self) -> None:
        """Mark that this session tracker was resumed from persistent storage."""
        self._resumed = True

    def record_request(
        self,
        provider: str,
        model: str,
        system_prompt: str,
        tools_schema_digest: str,
        temperature: float = 0.0,
    ) -> EpochHeaderRecord:
        """Record and advance an epoch turn, returning immutable EpochHeaderRecord."""
        self._generation += 1
        system_prompt_digest = _compute_sha256(system_prompt)
        prefix_input = (
            f"{provider}:{model}:{temperature:.2f}:{system_prompt_digest}:{tools_schema_digest}"
        )
        prefix_digest = _compute_sha256(prefix_input)

        if self._last_epoch is None:
            if self._resumed:
                phase = EpochPhaseKind.RESUME
                starts_series = True
                self._resumed = False
            else:
                phase = EpochPhaseKind.INITIAL
                starts_series = True
        else:
            prev = self._last_epoch
            is_config_changed = (
                prev.provider != provider
                or prev.model != model
                or prev.temperature != temperature
                or prev.system_prompt_digest != system_prompt_digest
                or prev.tools_schema_digest != tools_schema_digest
            )
            if is_config_changed:
                phase = EpochPhaseKind.CHANGE
                starts_series = True
            else:
                phase = EpochPhaseKind.SERIES
                starts_series = False

        record = EpochHeaderRecord(
            epoch_id=f"epoch-{uuid.uuid4().hex[:12]}",
            session_id=self._session_id,
            generation=self._generation,
            phase=phase,
            starts_series=starts_series,
            provider=provider,
            model=model,
            temperature=temperature,
            system_prompt_digest=system_prompt_digest,
            tools_schema_digest=tools_schema_digest,
            prefix_digest=prefix_digest,
        )

        self._last_epoch = record
        return record


class PrefixDigestTelemetricEngine:
    """Diagnoses and attributes prompt cache hits vs breaks."""

    @staticmethod
    def diagnose_cache_turn(
        current_epoch: EpochHeaderRecord,
        previous_epoch: EpochHeaderRecord | None,
        cache_read_tokens: int,
        cache_miss_tokens: int,
        messages_prefix_intact: bool = True,
    ) -> CacheAttributionTelemetry:
        """Analyze cache hit telemetry and attribute root cause."""
        # Baseline hit check
        if cache_read_tokens > 0 and cache_miss_tokens == 0:
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.NONE,
                is_runtime_defect=False,
                diagnostic_hint="Cache fully hit with 100% prefix reuse.",
            )

        # First turn cannot have a break against prior turn
        if previous_epoch is None:
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.NONE,
                is_runtime_defect=False,
                diagnostic_hint="Initial turn: cache creation expected.",
            )

        # Attributing root cause of break
        if previous_epoch.system_prompt_digest != current_epoch.system_prompt_digest:
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.SYSTEM_PROMPT,
                is_runtime_defect=True,
                diagnostic_hint=(
                    "System prompt mutated mid-session. Move dynamic parameters to user messages."
                ),
            )

        if previous_epoch.tools_schema_digest != current_epoch.tools_schema_digest:
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.TOOL_SCHEMA,
                is_runtime_defect=True,
                diagnostic_hint=(
                    "Tool schema or ordering changed mid-session. Maintain static catalog or use deferred loading."
                ),
            )

        if (
            previous_epoch.provider != current_epoch.provider
            or previous_epoch.model != current_epoch.model
            or previous_epoch.temperature != current_epoch.temperature
        ):
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.PARAM_MISMATCH,
                is_runtime_defect=True,
                diagnostic_hint="Model route or temperature altered mid-session.",
            )

        if not messages_prefix_intact:
            return CacheAttributionTelemetry(
                session_id=current_epoch.session_id,
                generation=current_epoch.generation,
                prefix_digest=current_epoch.prefix_digest,
                cache_read_tokens=cache_read_tokens,
                cache_miss_tokens=cache_miss_tokens,
                first_diff_area=FirstDiffAreaKind.MESSAGE_HISTORY,
                is_runtime_defect=True,
                diagnostic_hint=(
                    "Message history prefix mutated retroactively. Only append-only mutations allowed."
                ),
            )

        # Prefix is identical and message history prefix is intact, but cache read was missed/low
        return CacheAttributionTelemetry(
            session_id=current_epoch.session_id,
            generation=current_epoch.generation,
            prefix_digest=current_epoch.prefix_digest,
            cache_read_tokens=cache_read_tokens,
            cache_miss_tokens=cache_miss_tokens,
            first_diff_area=FirstDiffAreaKind.PROVIDER_EVICTION,
            is_runtime_defect=False,
            diagnostic_hint=(
                "Prefix digest completely stable. Miss attributed to provider cold start or LRU eviction."
            ),
        )
