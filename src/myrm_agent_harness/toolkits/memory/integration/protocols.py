"""Integration Provider protocol — storage-agnostic data source abstraction.

[INPUT]
- typing::Protocol, runtime_checkable (POS: Structural subtyping)

[OUTPUT]
- IntegrationProvider: Protocol for fetching data from an external service.

[POS]
Defines the contract that any third-party data provider (Gmail, GitHub, Slack,
Notion, etc.) must satisfy.  Business-layer implementations register concrete
providers; the framework only depends on this protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.memory.integration.types import IntegrationLeaf


@runtime_checkable
class IntegrationProvider(Protocol):
    """Contract for fetching data from one external service.

    Implementations are registered at the business layer (myrm-agent-server)
    and injected into the framework-side IntegrationFetcher. The framework
    never imports concrete provider classes.

    ``provider_id`` must be a stable lowercase identifier such as ``"gmail"``,
    ``"github"``, ``"slack"``, ``"notion"``.
    """

    @property
    def provider_id(self) -> str:
        """Unique lowercase identifier for this provider (e.g. 'gmail')."""
        ...

    @property
    def display_name(self) -> str:
        """Human-readable name shown in the frontend (e.g. 'Gmail')."""
        ...

    async def fetch(
        self,
        *,
        account_key: str = "",
        since_cursor: str | None = None,
        max_items: int = 200,
    ) -> list[IntegrationLeaf]:
        """Pull new/updated data from the external service.

        Args:
            account_key: Stable account identifier (empty for single-account providers).
            since_cursor: Opaque pagination/sync cursor from the previous run.
                          ``None`` for a full initial sync.
            max_items: Upper bound on items to fetch in a single call.

        Returns:
            A list of IntegrationLeaf records ready for ingestion.
        """
        ...

    async def get_sync_cursor(self, *, account_key: str = "") -> str | None:
        """Return the latest sync cursor for incremental fetching.

        Implementations should persist the cursor externally (e.g. in
        metadata storage) so that subsequent ``fetch()`` calls can
        request only delta updates.
        """
        ...

    async def validate_connection(self, *, account_key: str = "") -> bool:
        """Test whether the provider credentials are still valid."""
        ...
