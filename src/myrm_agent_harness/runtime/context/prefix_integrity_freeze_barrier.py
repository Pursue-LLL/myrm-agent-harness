"""Pre-flight prefix integrity freeze and active assertion barrier.

[INPUT]
Assembled outgoing model payloads, session identifiers, and barrier configuration modes.

[OUTPUT]
Deeply frozen immutable request payloads, deterministic baseline fingerprint locks,
and millisecond-level pre-flight assertion barrier enforcement.

[POS]
Active pre-flight barrier defending 99% prompt cache hits before provider dispatch.
"""

import hashlib
import json
import logging
import threading
from collections.abc import Mapping, Sequence

from myrm_agent_harness.runtime.context.prefix_integrity_barrier_types import (
    BarrierInterceptionMode,
    BaselinePrefixFingerprint,
    FrozenModelPayload,
    FrozenToolDescriptor,
    PrefixDriftKind,
    PrefixIntegrityViolationError,
    PreFlightInspectionResult,
)

logger = logging.getLogger(__name__)


def _compute_sha256(text: str) -> str:
    """Compute standard hex SHA-256 digest."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PreFlightPrefixIntegrityBarrier:
    """Barrier freezing model payloads and proactively blocking prefix cache drift."""

    def __init__(
        self,
        mode: BarrierInterceptionMode = BarrierInterceptionMode.STRICT_ASSERTION,
    ) -> None:
        self._mode = mode
        self._lock = threading.RLock()
        self._baselines: dict[str, BaselinePrefixFingerprint] = {}
        self._exemptions: dict[str, str] = {}
        self._audit_records: list[PreFlightInspectionResult] = []

    def set_interception_mode(self, mode: BarrierInterceptionMode) -> None:
        """Switch enforcement policy between STRICT_ASSERTION and WARN_AUDIT_ONLY."""
        with self._lock:
            self._mode = mode

    def grant_authorized_drift(self, session_id: str, reason: str) -> None:
        """Authorize a single controlled prefix invalidation and re-baseline."""
        with self._lock:
            self._exemptions[session_id] = reason
            logger.info("Authorized prefix drift granted for session %s: %s", session_id, reason)

    def freeze_payload(
        self,
        session_id: str,
        system_prompt: str,
        tools: Sequence[Mapping[str, str]],
        messages_count: int,
        model_name: str,
    ) -> FrozenModelPayload:
        """Freeze outgoing model request into an immutable payload snapshot."""
        sys_hash = _compute_sha256(system_prompt)

        frozen_tools: list[FrozenToolDescriptor] = []
        for t in tools:
            name = t.get("name", "")
            desc = t.get("description", "")
            schema_repr = json.dumps(t.get("parameters", {}), sort_keys=True)
            schema_hash = _compute_sha256(schema_repr)
            frozen_tools.append(
                FrozenToolDescriptor(
                    name=name,
                    description=desc,
                    parameters_schema_hash=schema_hash,
                )
            )

        # Deterministic sequential tool fingerprint
        tools_canonical_str = "|".join(
            f"{ft.name}:{ft.parameters_schema_hash}" for ft in frozen_tools
        )
        tools_hash = _compute_sha256(tools_canonical_str)

        return FrozenModelPayload(
            session_id=session_id,
            system_prompt=system_prompt,
            system_prompt_sha256=sys_hash,
            tools=tuple(frozen_tools),
            tools_fingerprint_sha256=tools_hash,
            messages_count=messages_count,
            model_name=model_name,
        )

    def inspect_and_assert_pre_flight(
        self,
        payload: FrozenModelPayload,
        allow_explicit_exemption: bool = False,
    ) -> PreFlightInspectionResult:
        """Verify pre-flight payload against golden baseline, asserting strict prefix parity."""
        with self._lock:
            session_id = payload.session_id
            baseline = self._baselines.get(session_id)

            # 1. Establish initial baseline on first turn
            if baseline is None:
                new_baseline = BaselinePrefixFingerprint(
                    session_id=session_id,
                    system_prompt_sha256=payload.system_prompt_sha256,
                    tools_fingerprint_sha256=payload.tools_fingerprint_sha256,
                    model_name=payload.model_name,
                )
                self._baselines[session_id] = new_baseline
                result = PreFlightInspectionResult(
                    session_id=session_id,
                    is_valid=True,
                    is_baseline_established=True,
                )
                self._audit_records.append(result)
                return result

            # 2. Check for authorized exemption
            has_exemption = allow_explicit_exemption or (session_id in self._exemptions)
            if has_exemption:
                self._exemptions.pop(session_id, None)
                updated_baseline = BaselinePrefixFingerprint(
                    session_id=session_id,
                    system_prompt_sha256=payload.system_prompt_sha256,
                    tools_fingerprint_sha256=payload.tools_fingerprint_sha256,
                    model_name=payload.model_name,
                )
                self._baselines[session_id] = updated_baseline
                result = PreFlightInspectionResult(
                    session_id=session_id,
                    is_valid=True,
                    is_baseline_established=True,
                    exemption_granted=True,
                )
                self._audit_records.append(result)
                return result

            # 3. Detect drift violations
            drifts: list[PrefixDriftKind] = []
            violation_details: list[str] = []

            if payload.system_prompt_sha256 != baseline.system_prompt_sha256:
                drifts.append(PrefixDriftKind.SYSTEM_PROMPT_MUTATION)
                violation_details.append(
                    f"System prompt SHA-256 changed from {baseline.system_prompt_sha256[:10]} "
                    f"to {payload.system_prompt_sha256[:10]}"
                )

            if payload.tools_fingerprint_sha256 != baseline.tools_fingerprint_sha256:
                drifts.append(PrefixDriftKind.TOOL_SCHEMA_MUTATION)
                violation_details.append(
                    f"Tools sequence SHA-256 changed from {baseline.tools_fingerprint_sha256[:10]} "
                    f"to {payload.tools_fingerprint_sha256[:10]}"
                )

            if payload.model_name != baseline.model_name:
                drifts.append(PrefixDriftKind.MODEL_SWITCH)
                violation_details.append(
                    f"Model changed from {baseline.model_name} to {payload.model_name}"
                )

            if not drifts:
                result = PreFlightInspectionResult(
                    session_id=session_id,
                    is_valid=True,
                    is_baseline_established=False,
                )
                self._audit_records.append(result)
                return result

            # Drift detected
            msg = "; ".join(violation_details)
            result = PreFlightInspectionResult(
                session_id=session_id,
                is_valid=False,
                is_baseline_established=False,
                drifts=tuple(drifts),
                violation_message=msg,
            )
            self._audit_records.append(result)

            if self._mode == BarrierInterceptionMode.STRICT_ASSERTION:
                primary_drift = drifts[0]
                raise PrefixIntegrityViolationError(
                    message="Pre-flight prefix integrity assertion failed",
                    drift_kind=primary_drift,
                    details=msg,
                )

            logger.warning(
                "Pre-flight prefix drift tolerated under %s mode: %s",
                self._mode,
                msg,
            )
            return result

    def get_baseline(self, session_id: str) -> BaselinePrefixFingerprint | None:
        """Fetch active golden baseline fingerprint for session."""
        with self._lock:
            return self._baselines.get(session_id)

    def get_audit_history(self) -> list[PreFlightInspectionResult]:
        """Fetch read-only audit records of pre-flight checks."""
        with self._lock:
            return list(self._audit_records)
