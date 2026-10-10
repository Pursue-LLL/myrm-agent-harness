"""Registry implementation for connector-domain mappings and domain-scoped grants.

[INPUT] Connector IDs, data domains, binding payloads, and grant toggle updates.
[OUTPUT] Persisted ConnectorDomainBinding entities and DomainGrantConfig states.
[POS] Harness framework toolkit memory registry for domain isolation boundaries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.domain_isolation.models import (
    ConnectorDomainBinding,
    DataDomain,
    DomainGrantConfig,
)


class DomainIsolationRegistry:
    """Manages connector-to-domain associations and independent grant permissions."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        self._storage_path: Path | None = (
            Path(storage_path) if storage_path is not None else None
        )
        self._bindings: dict[str, ConnectorDomainBinding] = {}
        self._grants: dict[DataDomain, DomainGrantConfig] = {
            "work": DomainGrantConfig(
                domain="work",
                allow_write=True,
                allow_recall=True,
                allow_proactive=True,
                allow_egress=True,
            ),
            "personal": DomainGrantConfig(
                domain="personal",
                allow_write=True,
                allow_recall=True,
                allow_proactive=False,
                allow_egress=False,
            ),
        }
        if self._storage_path is not None and self._storage_path.exists():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            content = self._storage_path.read_text(encoding="utf-8")
            if not content.strip():
                return
            data = json.loads(content)
            if isinstance(data, dict):
                bindings_data = data.get("bindings", {})
                for k, v in bindings_data.items():
                    if isinstance(v, dict):
                        self._bindings[k] = ConnectorDomainBinding.model_validate(v)
                grants_data = data.get("grants", {})
                for domain_key, grant_dict in grants_data.items():
                    if domain_key in ("work", "personal") and isinstance(grant_dict, dict):
                        self._grants[domain_key] = DomainGrantConfig.model_validate(grant_dict)
        except Exception:
            pass

    def _save_to_disk(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "bindings": {k: v.model_dump() for k, v in self._bindings.items()},
            "grants": {k: v.model_dump() for k, v in self._grants.items()},
        }
        self._storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def set_binding(
        self,
        connector_id: str,
        domain: DataDomain,
        channel: str = "",
        account_id: str | None = None,
    ) -> ConnectorDomainBinding:
        """Associate a connector with a domain. Explicit user declaration, default 'work'."""
        now_iso = datetime.now(UTC).isoformat()
        existing = self._bindings.get(connector_id)
        created_at = existing.created_at if existing and existing.created_at else now_iso

        binding = ConnectorDomainBinding(
            connector_id=connector_id,
            channel=channel or (existing.channel if existing else ""),
            account_id=account_id if account_id is not None else (existing.account_id if existing else None),
            domain=domain,
            created_at=created_at,
            updated_at=now_iso,
        )
        self._bindings[connector_id] = binding
        self._save_to_disk()
        return binding

    def get_binding(self, connector_id: str) -> ConnectorDomainBinding | None:
        """Fetch binding details for a connector."""
        return self._bindings.get(connector_id)

    def resolve_domain(self, connector_id: str) -> DataDomain:
        """Resolve domain for connector; falls back to 'work' without guessing."""
        binding = self._bindings.get(connector_id)
        return binding.domain if binding is not None else "work"

    def list_bindings(
        self, domain: DataDomain | None = None
    ) -> list[ConnectorDomainBinding]:
        """List all connector bindings, optionally filtered by domain."""
        if domain is None:
            return list(self._bindings.values())
        return [b for b in self._bindings.values() if b.domain == domain]

    def remove_binding(self, connector_id: str) -> bool:
        """Delete binding for a connector."""
        if connector_id in self._bindings:
            del self._bindings[connector_id]
            self._save_to_disk()
            return True
        return False

    def get_grant(self, domain: DataDomain) -> DomainGrantConfig:
        """Get grant configuration for a domain."""
        return self._grants[domain]

    def update_grant(
        self,
        domain: DataDomain,
        allow_write: bool | None = None,
        allow_recall: bool | None = None,
        allow_proactive: bool | None = None,
        allow_egress: bool | None = None,
    ) -> DomainGrantConfig:
        """Update permissions for a specific domain independently."""
        current = self._grants[domain]
        updated = DomainGrantConfig(
            domain=domain,
            allow_write=allow_write if allow_write is not None else current.allow_write,
            allow_recall=allow_recall if allow_recall is not None else current.allow_recall,
            allow_proactive=(
                allow_proactive if allow_proactive is not None else current.allow_proactive
            ),
            allow_egress=allow_egress if allow_egress is not None else current.allow_egress,
        )
        self._grants[domain] = updated
        self._save_to_disk()
        return updated
