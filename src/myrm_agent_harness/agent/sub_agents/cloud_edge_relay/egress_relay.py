"""Cloud-Edge Egress Relay Coordinator for Network Partition Crawling (Item 58).

[INPUT]
- LocalEgressRelayRequest from cloud sandbox tasks targeting network-restricted sources.

[OUTPUT]
- LocalEgressRelayResponse containing sanitized structured data extracted via local egress.

[POS]
- Safely orchestrates outbound request relaying from cloud sandbox to local desktop egress
  while guarding against SSRF and intranet probe attacks.
"""

from __future__ import annotations

import urllib.parse
import uuid
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.sub_agents.cloud_edge_relay.types import (
    LocalEgressRelayRequest,
    LocalEgressRelayResponse,
    NetworkEgressStatusEnum,
    RelayNodeRoleEnum,
)

DISALLOWED_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # noqa: S104
    "169.254.169.254",
    "metadata.google.internal",
})


class CloudEdgeEgressRelayCoordinator:
    """Coordinates relaying web fetch requests from restricted cloud nodes to local egress nodes."""

    def __init__(self, default_timeout_seconds: float = 15.0) -> None:
        self._default_timeout_seconds = max(1.0, min(60.0, default_timeout_seconds))
        self._pending_requests: dict[str, LocalEgressRelayRequest] = {}
        self._completed_responses: dict[str, LocalEgressRelayResponse] = {}

    def validate_target_url(self, url: str) -> None:
        """Validates that a URL is a legitimate public web destination."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Invalid URL scheme '{parsed.scheme}': only http and https are permitted.")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ValueError(f"URL '{url}' lacks a valid hostname.")
        if host in DISALLOWED_HOSTS or host.startswith("10.") or host.startswith("192.168."):
            raise ValueError(f"Target host '{host}' is disallowed for egress relay to prevent SSRF.")

    def create_relay_request(
        self,
        target_url: str,
        intent: str,
        headers: Mapping[str, str] | None = None,
        payload: Mapping[str, str | int | float | bool] | None = None,
        timeout_seconds: float | None = None,
        source_node: RelayNodeRoleEnum = RelayNodeRoleEnum.CLOUD_SANDBOX,
    ) -> LocalEgressRelayRequest:
        """Constructs and enqueues an egress relay request after URL safety verification."""
        self.validate_target_url(target_url)
        relay_id = f"relay-{uuid.uuid4().hex[:8]}"
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._default_timeout_seconds
        )
        req = LocalEgressRelayRequest(
            relay_id=relay_id,
            target_url=target_url,
            intent=intent,
            headers=dict(headers) if headers is not None else {},
            payload=dict(payload) if payload is not None else {},
            timeout_seconds=timeout,
            source_node=source_node,
        )
        self._pending_requests[relay_id] = req
        return req

    def complete_relay_request(
        self,
        relay_id: str,
        status: NetworkEgressStatusEnum,
        extracted_data: str,
        status_code: int = 200,
        latency_ms: float = 0.0,
        error_message: str = "",
    ) -> LocalEgressRelayResponse:
        """Records completion of a relay fetch executed by the local client node."""
        if relay_id not in self._pending_requests:
            raise KeyError(f"Relay request '{relay_id}' is not in pending queue.")

        response = LocalEgressRelayResponse(
            relay_id=relay_id,
            status=status,
            extracted_data=extracted_data,
            status_code=status_code,
            latency_ms=latency_ms,
            error_message=error_message,
        )
        self._completed_responses[relay_id] = response
        del self._pending_requests[relay_id]
        return response

    def get_relay_response(self, relay_id: str) -> LocalEgressRelayResponse | None:
        """Retrieves outcome for a finished relay request."""
        return self._completed_responses.get(relay_id)

    def list_pending_relays(self) -> Sequence[LocalEgressRelayRequest]:
        """Returns all currently pending relay requests waiting for local execution."""
        return tuple(self._pending_requests.values())

    def list_completed_relays(self) -> Sequence[LocalEgressRelayResponse]:
        """Returns all completed relay responses."""
        return tuple(self._completed_responses.values())

    def clear(self) -> None:
        """Resets pending and completed queues."""
        self._pending_requests.clear()
        self._completed_responses.clear()
