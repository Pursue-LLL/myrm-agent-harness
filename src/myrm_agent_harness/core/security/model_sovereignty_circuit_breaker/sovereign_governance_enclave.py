"""
[POS] src/myrm_agent_harness/core/security/model_sovereignty_circuit_breaker/sovereign_governance_enclave.py
[INPUT] time, uuid, logging, typing, .types
[OUTPUT] SovereignGovernanceEnclave

Data, model, and toolchain self-hosted digital sovereignty audit enclave & local mesh manager.
Evaluates full-stack autonomy posture and schedules heterogeneous compute nodes.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .types import MeshNodeSpec, SovereignEnclavePosture

logger = logging.getLogger(__name__)


class SovereignGovernanceEnclave:
    """Enclave scoring full-stack self-hosted sovereignty and coordinating local heterogeneous mesh."""

    NODE_HEARTBEAT_TIMEOUT_SECONDS: float = 30.0

    def __init__(self) -> None:
        self._mesh_nodes: dict[str, MeshNodeSpec] = {}

    def audit_sovereignty_posture(
        self,
        is_data_self_hosted: bool,
        is_model_self_hosted: bool,
        is_tool_sandbox_isolated: bool,
        active_storage_mode: str = "sqlite_local_volume",
        active_model_endpoint: str = "http://localhost:11434",
    ) -> SovereignEnclavePosture:
        """Audit full-stack autonomy across data, models, and tools, computing a 0-100 score."""
        enclave_id = f"sovereign-{uuid.uuid4().hex[:12]}"
        now = time.time()

        score = 0
        if is_data_self_hosted:
            score += 35
        if is_model_self_hosted:
            score += 35
        else:
            # Partial credit for sovereign routing over public API
            score += 10
        if is_tool_sandbox_isolated:
            score += 30

        posture = SovereignEnclavePosture(
            enclave_id=enclave_id,
            is_data_self_hosted=is_data_self_hosted,
            is_model_self_hosted=is_model_self_hosted,
            is_tool_sandbox_isolated=is_tool_sandbox_isolated,
            sovereignty_score=score,
            active_storage_mode=active_storage_mode,
            active_model_endpoint=active_model_endpoint,
            timestamp=now,
        )

        logger.info(
            "Audited sovereignty posture %s: score=%d (data=%s, model=%s, sandbox=%s)",
            enclave_id,
            score,
            is_data_self_hosted,
            is_model_self_hosted,
            is_tool_sandbox_isolated,
        )
        return posture

    def register_mesh_node(
        self,
        node_id: str,
        hostname: str,
        node_type: str,
        capacity_weight: int = 10,
    ) -> MeshNodeSpec:
        """Register or update a compute node in heterogeneous local mesh."""
        now = time.time()
        node = MeshNodeSpec(
            node_id=node_id,
            hostname=hostname,
            node_type=node_type,
            is_healthy=True,
            capacity_weight=capacity_weight,
            last_heartbeat=now,
        )
        self._mesh_nodes[node_id] = node
        logger.info("Registered mesh node '%s' (%s, type=%s, weight=%d)", node_id, hostname, node_type, capacity_weight)
        return node

    def record_node_heartbeat(self, node_id: str) -> bool:
        """Record heartbeat pulse for a registered mesh node."""
        node = self._mesh_nodes.get(node_id)
        if node is None:
            return False

        updated = MeshNodeSpec(
            node_id=node.node_id,
            hostname=node.hostname,
            node_type=node.node_type,
            is_healthy=True,
            capacity_weight=node.capacity_weight,
            last_heartbeat=time.time(),
        )
        self._mesh_nodes[node_id] = updated
        return True

    def list_healthy_nodes(self) -> list[MeshNodeSpec]:
        """List active nodes whose heartbeats have not expired."""
        now = time.time()
        healthy: list[MeshNodeSpec] = []
        for node in self._mesh_nodes.values():
            if now - node.last_heartbeat <= self.NODE_HEARTBEAT_TIMEOUT_SECONDS:
                healthy.append(node)
            else:
                # Mark as unhealthy
                unhealthy = MeshNodeSpec(
                    node_id=node.node_id,
                    hostname=node.hostname,
                    node_type=node.node_type,
                    is_healthy=False,
                    capacity_weight=node.capacity_weight,
                    last_heartbeat=node.last_heartbeat,
                )
                self._mesh_nodes[node.node_id] = unhealthy
        return healthy

    def get_best_compute_node(self, preferred_type: str = "gpu_worker") -> MeshNodeSpec | None:
        """Pick optimal online node matching preferred node_type by highest capacity weight."""
        healthy = self.list_healthy_nodes()
        candidates = [n for n in healthy if n.node_type == preferred_type and n.is_healthy]
        if not candidates:
            # Fall back to any healthy node
            candidates = [n for n in healthy if n.is_healthy]
        if not candidates:
            return None
        return max(candidates, key=lambda n: n.capacity_weight)
