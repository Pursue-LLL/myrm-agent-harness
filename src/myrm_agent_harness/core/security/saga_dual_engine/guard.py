"""Spatiotemporal Dual-Engine Guard.

Orchestrates:
1. ToolIntent duality: Acquisition (free retry, read-only) vs Emission (physical, irreversible).
2. Connector Trust Gate: explicit authorization lease before touching external systems.
3. Secondary HITL confirmation for physical emissions.
4. Declarative Saga compensation registration and immutable emission audit log.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from myrm_agent_harness.core.security.saga_dual_engine.saga_engine import (
    SagaExecutionEngine,
)
from myrm_agent_harness.core.security.saga_dual_engine.trust_gate import (
    ConnectorTrustGate,
)
from myrm_agent_harness.core.security.saga_dual_engine.types import (
    CompensationStatus,
    ConnectorUntrustedError,
    EmissionAuditRecord,
    EmissionUnconfirmedError,
    JsonScalar,
    ToolIntent,
)


class SpatiotemporalDualEngineGuard:
    """Guard enforcing spatiotemporal tool duality, connector trust, and saga tracking."""

    def __init__(
        self,
        saga_engine: SagaExecutionEngine | None = None,
        trust_gate: ConnectorTrustGate | None = None,
    ) -> None:
        self._saga_engine = saga_engine if saga_engine is not None else SagaExecutionEngine()
        self._trust_gate = trust_gate if trust_gate is not None else ConnectorTrustGate()
        self._emission_audit_log: list[EmissionAuditRecord] = []

    @property
    def saga_engine(self) -> SagaExecutionEngine:
        """Underlying SagaExecutionEngine."""
        return self._saga_engine

    @property
    def trust_gate(self) -> ConnectorTrustGate:
        """Underlying ConnectorTrustGate."""
        return self._trust_gate

    def execute_tool(
        self,
        tool_name: str,
        intent: ToolIntent,
        action_fn: Callable[[], str],
        params: Mapping[str, JsonScalar],
        agent_id: str,
        approver_id: str | None = None,
        connector_id: str | None = None,
        connector_host: str | None = None,
        required_scope: str | None = None,
        hitl_confirmed: bool = False,
        compensator_name: str | None = None,
        compensation_params: Mapping[str, JsonScalar] | None = None,
    ) -> tuple[str, EmissionAuditRecord | None]:
        """Execute tool respecting spatiotemporal duality and security gates."""
        # 1. Acquisition Branch: Reversible read-only operation
        if intent == ToolIntent.ACQUISITION:
            output = action_fn()
            self._saga_engine.record_step(
                tool_name=tool_name,
                intent=intent,
                params=params,
                compensator_name=None,
                compensation_params=None,
            )
            return output, None

        # 2. Emission Branch: Irreversible physical cross-boundary I/O
        if intent == ToolIntent.EMISSION:
            # Layer 1: Connector Trust Authorization
            if not connector_id or not connector_host:
                raise ConnectorUntrustedError(
                    f"External connector_id and connector_host are required for emission tool '{tool_name}'"
                )
            self._trust_gate.assert_connector_trusted(
                connector_id=connector_id,
                host=connector_host,
                required_scope=required_scope,
            )

            # Layer 2: Secondary HITL Confirmation
            if not hitl_confirmed:
                raise EmissionUnconfirmedError(
                    f"Irreversible physical emission tool '{tool_name}' on connector '{connector_id}' "
                    "requires explicit secondary HITL confirmation"
                )

            # Execution
            output = action_fn()

            # Layer 3: Declarative Saga Step Recording
            self._saga_engine.record_step(
                tool_name=tool_name,
                intent=intent,
                params=params,
                compensator_name=compensator_name,
                compensation_params=compensation_params,
            )

            # Layer 4: Immutable Emission Audit Log
            raw_params_bytes = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
            params_hash = hashlib.sha256(raw_params_bytes).hexdigest()
            comp_status = (
                CompensationStatus.PENDING if compensator_name else CompensationStatus.NOT_REQUIRED
            )

            audit_record = EmissionAuditRecord(
                audit_id=f"emit-aud-{uuid.uuid4().hex[:10]}",
                agent_id=agent_id,
                approver_id=approver_id or "system",
                connector_id=connector_id,
                tool_name=tool_name,
                params_hash=params_hash,
                receipt=output[:100],
                compensation_status=comp_status,
                timestamp=datetime.now(UTC).isoformat(),
            )
            self._emission_audit_log.append(audit_record)
            return output, audit_record

        raise ValueError(f"Unknown ToolIntent: {intent}")

    def rollback_saga(self) -> list[tuple[str, bool]]:
        """Trigger reverse LIFO compensation across all recorded emission steps."""
        return self._saga_engine.rollback()

    def get_audit_log(self) -> list[EmissionAuditRecord]:
        """Fetch copy of immutable emission audit trail."""
        return list(self._emission_audit_log)
