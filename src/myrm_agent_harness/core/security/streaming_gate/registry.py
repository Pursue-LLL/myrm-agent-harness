"""Registry for declared streaming endpoint contracts.

[INPUT]
- StreamingEndpointContract.

[OUTPUT]
- Contract lookup and enumeration across streaming routes.

[POS]
- Harness core security registry. Enforces that all SSE, WebSocket, and chunked HTTP
  endpoints declare an explicit security contract.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.streaming_gate.types import (
    StreamingEndpointContract,
)

logger = logging.getLogger(__name__)


class StreamingEndpointRegistry:
    """Registry maintaining security contracts for all long-lived streaming endpoints."""

    def __init__(self) -> None:
        self._contracts: dict[str, StreamingEndpointContract] = {}

    def register_contract(self, contract: StreamingEndpointContract) -> None:
        """Register or update the security contract for a streaming endpoint path."""
        self._contracts[contract.endpoint_path] = contract
        logger.debug(
            "Registered streaming contract for '%s' (transport=%s, scope=%s)",
            contract.endpoint_path,
            contract.transport,
            contract.required_scope,
        )

    def register_contracts(self, contracts: Sequence[StreamingEndpointContract]) -> None:
        """Batch register streaming endpoint contracts."""
        for c in contracts:
            self.register_contract(c)

    def get_contract(self, endpoint_path: str) -> StreamingEndpointContract | None:
        """Retrieve the declared security contract for an endpoint, if registered."""
        if endpoint_path in self._contracts:
            return self._contracts[endpoint_path]

        # Check prefix/pattern matching for parameterized routes (e.g. /tasks/{task_id}/stream)
        for path_pattern, contract in self._contracts.items():
            if "{" in path_pattern:
                base_prefix = path_pattern.split("{")[0]
                if endpoint_path.startswith(base_prefix):
                    return contract

        return None

    def list_contracts(self) -> tuple[StreamingEndpointContract, ...]:
        """Return all registered streaming endpoint contracts."""
        return tuple(self._contracts.values())

    def unregister(self, endpoint_path: str) -> bool:
        """Remove a contract registration."""
        return self._contracts.pop(endpoint_path, None) is not None
