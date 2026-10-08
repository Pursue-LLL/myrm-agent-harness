"""Managed Connectors Hub for multi-channel external ecosystem credentials and health monitoring.

[POS] src/myrm_agent_harness/core/security/managed_permission_rollback/connectors_hub.py
[INPUT] myrm_agent_harness.core.security.managed_permission_rollback.types
[OUTPUT] ManagedConnectorsHub
"""

from __future__ import annotations

import logging
import time
from typing import Final

from myrm_agent_harness.core.security.managed_permission_rollback.types import (
    ConnectorChannelType,
    ConnectorStatus,
    ManagedConnectorMeta,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class ManagedConnectorsHub:
    """Central registry and health monitor for enterprise external ecosystem integrations."""

    def __init__(self) -> None:
        self._connectors: dict[str, ManagedConnectorMeta] = {}

    def register_connector(
        self,
        connector_id: str,
        channel_type: ConnectorChannelType,
        display_name: str,
        account_identifier: str = "",
        token_lifetime_seconds: float | None = 3600.0,
    ) -> ManagedConnectorMeta:
        """Register or renew an external ecosystem connector."""
        now = time.time()
        token_expires_at = (now + token_lifetime_seconds) if token_lifetime_seconds else None

        meta = ManagedConnectorMeta(
            connector_id=connector_id,
            channel_type=channel_type,
            display_name=display_name,
            status=ConnectorStatus.ACTIVE,
            last_heartbeat_at=now,
            token_expires_at=token_expires_at,
            account_identifier=account_identifier,
        )
        self._connectors[connector_id] = meta
        logger.info(
            "Registered managed connector '%s' (type=%s, account=%s)",
            connector_id,
            channel_type.value,
            account_identifier,
        )
        return meta

    def record_heartbeat(self, connector_id: str) -> ManagedConnectorMeta | None:
        """Record an active ping from the connector, refreshing heartbeat and verifying token expiry."""
        meta = self._connectors.get(connector_id)
        if meta is None:
            return None

        now = time.time()
        status = meta.status

        # If token expired, downgrade status to EXPIRED
        if meta.token_expires_at and now > meta.token_expires_at:
            status = ConnectorStatus.EXPIRED
        elif status == ConnectorStatus.DISCONNECTED:
            status = ConnectorStatus.ACTIVE

        updated = ManagedConnectorMeta(
            connector_id=meta.connector_id,
            channel_type=meta.channel_type,
            display_name=meta.display_name,
            status=status,
            last_heartbeat_at=now,
            token_expires_at=meta.token_expires_at,
            account_identifier=meta.account_identifier,
        )
        self._connectors[connector_id] = updated
        return updated

    def update_status(
        self, connector_id: str, status: ConnectorStatus
    ) -> ManagedConnectorMeta | None:
        """Explicitly transition connector health state (e.g. DEGRADED, DISCONNECTED)."""
        meta = self._connectors.get(connector_id)
        if meta is None:
            return None

        updated = ManagedConnectorMeta(
            connector_id=meta.connector_id,
            channel_type=meta.channel_type,
            display_name=meta.display_name,
            status=status,
            last_heartbeat_at=time.time(),
            token_expires_at=meta.token_expires_at,
            account_identifier=meta.account_identifier,
        )
        self._connectors[connector_id] = updated
        logger.warning(
            "Connector status changed: id=%s new_status=%s",
            connector_id,
            status.value,
        )
        return updated

    def get_connector(self, connector_id: str) -> ManagedConnectorMeta | None:
        """Fetch connector metadata by ID."""
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[ManagedConnectorMeta]:
        """List all managed ecosystem connectors and their health posture."""
        return list(self._connectors.values())
