"""Registry for pre-connect disclosure cards explaining data lifecycle to users.

[INPUT]
- PreConnectDisclosure.

[OUTPUT]
- User-facing disclosure card lookup and enumeration.

[POS]
- Harness core security registry. Ensures all external integrations provide structured
  pre-authorization disclosure detailing data types read, actions performed, and purge policies.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.integration_trust.types import (
    DataFlowDirection,
    PreConnectDisclosure,
)

logger = logging.getLogger(__name__)

DEFAULT_DISCLOSURES: tuple[PreConnectDisclosure, ...] = (
    PreConnectDisclosure(
        provider_id="google_workspace",
        display_name="Google Workspace (Gmail & Drive)",
        data_types_read=(
            "Email sender, recipient, subject, and message body",
            "Drive file metadata and selected document contents",
        ),
        actions_performed=(
            "Read search results on behalf of user",
            "Index message snippets for contextual memory",
        ),
        storage_locations=(
            "Local sandbox memory index tree (mcp:google_workspace)",
            "Ephemeral embedding cache in SQLite/vector store",
        ),
        purge_policy_summary=(
            "Disconnecting will immediately purge all synced email memory trees, "
            "remove vector indices, and revoke Google OAuth access tokens."
        ),
        flow_direction=DataFlowDirection.BIDIRECTIONAL,
    ),
    PreConnectDisclosure(
        provider_id="github",
        display_name="GitHub Integration",
        data_types_read=(
            "Repository code, commit history, issues, and PR comments",
        ),
        actions_performed=(
            "Read repository content for code editing and audit tasks",
            "Create branches or draft PRs when explicitly requested",
        ),
        storage_locations=(
            "Project workspace directory",
            "Repository metadata memory tree",
        ),
        purge_policy_summary=(
            "Disconnecting revokes repository access tokens and purges "
            "cached repository index trees."
        ),
        flow_direction=DataFlowDirection.BIDIRECTIONAL,
    ),
    PreConnectDisclosure(
        provider_id="mcp",
        display_name="Model Context Protocol (MCP) Server",
        data_types_read=(
            "Dynamic resource payloads exposed by local/remote MCP server",
        ),
        actions_performed=(
            "Invoke tools exposed by MCP server",
            "Stream MCP resource updates into agent conversation context",
        ),
        storage_locations=(
            "Memory tree under namespace mcp:{server_name}",
        ),
        purge_policy_summary=(
            "Disconnecting terminates the MCP server process and recursively purges "
            "all synced memory trees under mcp:{server_name}."
        ),
        flow_direction=DataFlowDirection.BIDIRECTIONAL,
    ),
)


class PreConnectDisclosureRegistry:
    """Registry managing pre-connect disclosure cards for integration providers."""

    def __init__(self) -> None:
        self._disclosures: dict[str, PreConnectDisclosure] = {}
        for d in DEFAULT_DISCLOSURES:
            self._disclosures[d.provider_id] = d

    def register(self, disclosure: PreConnectDisclosure) -> None:
        """Register or override a pre-connect disclosure card."""
        self._disclosures[disclosure.provider_id] = disclosure

    def register_batch(self, disclosures: Sequence[PreConnectDisclosure]) -> None:
        """Batch register disclosure cards."""
        for d in disclosures:
            self.register(d)

    def get_disclosure(self, provider_id: str) -> PreConnectDisclosure | None:
        """Retrieve pre-connect disclosure card for a given provider."""
        return self._disclosures.get(provider_id)

    def list_disclosures(self) -> tuple[PreConnectDisclosure, ...]:
        """List all registered pre-connect disclosures."""
        return tuple(self._disclosures.values())
