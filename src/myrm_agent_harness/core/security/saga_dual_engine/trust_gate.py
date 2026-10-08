"""Connector Trust Authorization Gate.

Enforces explicit human/operator trust authorization before allowing Agent
connections to external systems, databases, enterprise ERP, or third-party APIs.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.core.security.saga_dual_engine.types import (
    ConnectorTrustLease,
    ConnectorUntrustedError,
)


class ConnectorTrustGate:
    """Gate verifying explicit trust leases for external connectors."""

    def __init__(self) -> None:
        self._leases: dict[str, ConnectorTrustLease] = {}

    def grant_lease(
        self,
        connector_id: str,
        host: str,
        authorized_scopes: Sequence[str],
        ttl_seconds: int = 3600,
    ) -> ConnectorTrustLease:
        """Issue an explicit trust authorization lease for an external connector."""
        lease_id = f"lease-{uuid.uuid4().hex[:10]}"
        expires_at = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()

        lease = ConnectorTrustLease(
            lease_id=lease_id,
            connector_id=connector_id,
            host=host,
            authorized_scopes=tuple(authorized_scopes),
            expires_at=expires_at,
            is_active=True,
        )
        self._leases[lease_id] = lease
        return lease

    def revoke_lease(self, lease_id: str) -> bool:
        """Revoke an active trust lease."""
        lease = self._leases.get(lease_id)
        if lease is None or not lease.is_active:
            return False

        updated = ConnectorTrustLease(
            lease_id=lease.lease_id,
            connector_id=lease.connector_id,
            host=lease.host,
            authorized_scopes=lease.authorized_scopes,
            expires_at=lease.expires_at,
            is_active=False,
        )
        self._leases[lease_id] = updated
        return True

    def find_active_lease(self, connector_id: str, host: str) -> ConnectorTrustLease | None:
        """Find a currently valid active lease matching connector and host."""
        now_iso = datetime.now(UTC).isoformat()
        for lease in self._leases.values():
            if (
                lease.connector_id == connector_id
                and lease.host == host
                and lease.is_active
                and lease.expires_at > now_iso
            ):
                return lease
        return None

    def assert_connector_trusted(
        self,
        connector_id: str,
        host: str,
        required_scope: str | None = None,
    ) -> ConnectorTrustLease:
        """Assert that an external connector has an active, valid trust lease."""
        lease = self.find_active_lease(connector_id, host)
        if lease is None:
            raise ConnectorUntrustedError(
                f"External connector '{connector_id}' on host '{host}' is UNTRUSTED. "
                "Explicit operator trust authorization lease is required before I/O."
            )

        if required_scope and required_scope not in lease.authorized_scopes:
            raise ConnectorUntrustedError(
                f"Connector '{connector_id}' is not authorized for scope '{required_scope}'. "
                f"Authorized scopes: {list(lease.authorized_scopes)}"
            )

        return lease
