"""myrm_agent_harness/agent/sub_agents/fleet_router/artifact_relay.py

[INPUT]
- hashlib
- time
- uuid

[OUTPUT]
- CrossGatewayArtifactRelayService

[POS]
myrm_agent_harness/agent/sub_agents/fleet_router/artifact_relay.py
"""

import hashlib
import time
import uuid

from myrm_agent_harness.agent.sub_agents.fleet_router.connection_pool import (
    GatewayNotFoundError,
    MultiGatewayConnectionPool,
)
from myrm_agent_harness.agent.sub_agents.fleet_router.types import (
    CrossGatewayArtifactEnvelope,
)


class CrossGatewayArtifactRelayService:
    """Relays artifacts across remote fleet gateways with SHA-256 integrity verification."""

    def __init__(self, connection_pool: MultiGatewayConnectionPool | None = None) -> None:
        self.connection_pool = connection_pool
        self._relay_journal: dict[str, CrossGatewayArtifactEnvelope] = {}

    def relay_artifact(
        self,
        source_gateway: str,
        target_gateway: str,
        name: str,
        file_path: str,
        chunk_data: str,
        now: float | None = None,
    ) -> CrossGatewayArtifactEnvelope:
        if self.connection_pool:
            if not self.connection_pool.get_gateway(source_gateway):
                raise GatewayNotFoundError(f"Source gateway '{source_gateway}' does not exist.")
            if not self.connection_pool.get_gateway(target_gateway):
                raise GatewayNotFoundError(f"Target gateway '{target_gateway}' does not exist.")

        data_bytes = chunk_data.encode("utf-8")
        sha256_hash = hashlib.sha256(data_bytes).hexdigest()
        created_time = now if now is not None else time.time()
        artifact_id = f"art-relay-{uuid.uuid4().hex[:8]}"

        envelope = CrossGatewayArtifactEnvelope(
            artifact_id=artifact_id,
            source_gateway=source_gateway,
            target_gateway=target_gateway,
            name=name,
            file_path=file_path,
            sha256=sha256_hash,
            chunk_data=chunk_data,
            created_at=created_time,
        )

        self._relay_journal[artifact_id] = envelope
        return envelope

    def verify_artifact_integrity(self, envelope: CrossGatewayArtifactEnvelope) -> bool:
        computed_sha = hashlib.sha256(envelope.chunk_data.encode("utf-8")).hexdigest()
        return computed_sha.lower() == envelope.sha256.lower()

    def get_artifact(self, artifact_id: str) -> CrossGatewayArtifactEnvelope | None:
        return self._relay_journal.get(artifact_id)

    def list_relayed_artifacts(
        self, gateway_id: str | None = None
    ) -> list[CrossGatewayArtifactEnvelope]:
        if not gateway_id:
            return list(self._relay_journal.values())
        return [
            art
            for art in self._relay_journal.values()
            if art.source_gateway == gateway_id or art.target_gateway == gateway_id
        ]
