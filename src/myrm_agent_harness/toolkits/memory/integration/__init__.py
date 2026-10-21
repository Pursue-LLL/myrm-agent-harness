"""Integration Memory — external service data memorisation for cross-source semantic retrieval.

[OUTPUT]
- IntegrationProvider: Protocol for data fetching from external services.
- IntegrationFetcher: Concurrent fetch scheduler with idempotent dedup.
- IntegrationTreeManager: Adaptive hierarchical summary tree backed by GraphStore.
- IntegrationSummariser: LLM-powered multi-level summarisation.

[POS]
Integration Memory sub-module.  Pulls data from third-party services (Gmail,
GitHub, Slack, Notion, …) into the local memory system, enabling cross-source
semantic retrieval without live API calls. Exposed to product via REST API /
GUI in `myrm-agent-server.app.api.integrations`; Agent reads results through
the general memory toolkit (no dedicated Agent tools).
"""

from myrm_agent_harness.toolkits.memory.integration.protocols import IntegrationProvider
from myrm_agent_harness.toolkits.memory.integration.types import (
    IntegrationLeaf,
    IntegrationNodeKind,
    IntegrationSyncOutcome,
    IntegrationSyncResult,
    IntegrationTree,
)

__all__ = [
    "IntegrationLeaf",
    "IntegrationNodeKind",
    "IntegrationProvider",
    "IntegrationSyncOutcome",
    "IntegrationSyncResult",
    "IntegrationTree",
]
