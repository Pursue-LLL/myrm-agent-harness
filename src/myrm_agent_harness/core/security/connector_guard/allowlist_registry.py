"""Declarative Connector Host and SNI Allowlist Registry."""

from __future__ import annotations

import threading
from urllib.parse import urlparse

from .types import ConnectorAllowlistEntry


class ConnectorAllowlistRegistry:
    """Thread-safe registry mapping connectors to authorized official hosts and SNI boundaries."""

    def __init__(self, load_defaults: bool = True) -> None:
        self._lock = threading.Lock()
        self._connectors: dict[str, ConnectorAllowlistEntry] = {}
        if load_defaults:
            self._load_standard_defaults()

    def _load_standard_defaults(self) -> None:
        """Register canonical enterprise connector profiles."""
        standard_profiles: list[ConnectorAllowlistEntry] = [
            ConnectorAllowlistEntry(
                connector_id="github",
                official_hosts=("api.github.com", "github.com", "uploads.github.com"),
                allow_subdomains=False,
                allowed_schemes=("https",),
                description="GitHub official API and git endpoints",
            ),
            ConnectorAllowlistEntry(
                connector_id="feishu",
                official_hosts=("open.feishu.cn", "open.larksuite.com"),
                allow_subdomains=False,
                allowed_schemes=("https",),
                description="Feishu / Lark Open Platform API",
            ),
            ConnectorAllowlistEntry(
                connector_id="jira",
                official_hosts=("api.atlassian.com",),
                allow_subdomains=True,
                allowed_schemes=("https",),
                description="Atlassian Jira Cloud REST API",
            ),
            ConnectorAllowlistEntry(
                connector_id="slack",
                official_hosts=("slack.com", "api.slack.com"),
                allow_subdomains=False,
                allowed_schemes=("https",),
                description="Slack Web API",
            ),
            ConnectorAllowlistEntry(
                connector_id="salesforce",
                official_hosts=("login.salesforce.com", "api.salesforce.com"),
                allow_subdomains=True,
                allowed_schemes=("https",),
                description="Salesforce Lightning & REST Platform",
            ),
        ]
        for profile in standard_profiles:
            self._connectors[profile.connector_id] = profile

    def register(self, entry: ConnectorAllowlistEntry) -> None:
        """Register or update an allowlist entry for a connector."""
        with self._lock:
            self._connectors[entry.connector_id] = entry

    def unregister(self, connector_id: str) -> bool:
        """Remove a connector from the registry."""
        with self._lock:
            return self._connectors.pop(connector_id, None) is not None

    def get(self, connector_id: str) -> ConnectorAllowlistEntry | None:
        """Retrieve allowlist entry by connector ID."""
        with self._lock:
            return self._connectors.get(connector_id)

    def list_entries(self) -> list[ConnectorAllowlistEntry]:
        """List all registered connector entries."""
        with self._lock:
            return list(self._connectors.values())

    def match_host(
        self, host: str, connector_id: str | None = None
    ) -> ConnectorAllowlistEntry | None:
        """Find a connector entry authorizing the given host.

        If connector_id is provided, checks only that specific connector's allowlist.
        Otherwise, searches across all registered connectors.
        """
        normalized_host = host.lower().strip().rstrip(".")
        with self._lock:
            if connector_id:
                entry = self._connectors.get(connector_id)
                if entry and self._is_host_allowed(normalized_host, entry):
                    return entry
                return None

            for entry in self._connectors.values():
                if self._is_host_allowed(normalized_host, entry):
                    return entry
            return None

    def _is_host_allowed(
        self, normalized_host: str, entry: ConnectorAllowlistEntry
    ) -> bool:
        for official_host in entry.official_hosts:
            official_norm = official_host.lower().strip().rstrip(".")
            if normalized_host == official_norm:
                return True
            if entry.allow_subdomains and normalized_host.endswith(f".{official_norm}"):
                return True
        return False

    def validate_url_scheme(self, url: str, entry: ConnectorAllowlistEntry) -> bool:
        """Verify URL scheme against connector allowed schemes."""
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        return scheme in entry.allowed_schemes

    def clear(self) -> None:
        """Clear all registered connectors."""
        with self._lock:
            self._connectors.clear()
