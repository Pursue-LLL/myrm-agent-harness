# integration/

## Overview
Integration Memory sub-module — pulls data from third-party services (Gmail, GitHub, Slack, Notion, …) into the local memory system, enabling cross-source semantic retrieval without live API calls.

## Architecture

```
IntegrationProvider (Protocol)      ← Business layer implements per-service
        ↓ fetch()
IntegrationLeaf (DTO)
        ↓
IntegrationFetcher                  ← Concurrent scheduler, dedup, embedding
   ├→ VectorStore.upsert()          → IntegrationMemory in vector backend
   └→ IntegrationTreeManager        → Graph nodes (adaptive hierarchy)
        ↓
IntegrationSummariser               ← Bottom-up LLM summarisation
        ↓
REST API / GUI (myrm-agent-server.app.api.integrations.integration_memory)
        ↓
Memory backends (VectorStore + GraphStore) → consumed by Agent via existing memory tools
```

### Adaptive Branching
The tree structure is **not** a fixed two-layer schema. Depth is determined by data volume: when a branch accumulates more than a configurable leaf threshold, a new CATEGORY level is inserted. Node kinds: ROOT → PROVIDER → ACCOUNT → [CATEGORY…] → LEAF.

### Deduplication
Idempotent sync via `(provider, external_object_id)` pair. Re-syncing the same data is a no-op.

### Framework Boundary
- **Framework (harness)**: Protocol, types, fetcher, tree manager, summariser. No Agent tools — integration management is a product-level REST/GUI concern, not a per-turn Agent action.
- **Business (server)**: Concrete `IntegrationProvider` implementations (Gmail, GitHub, etc.), credential storage, scheduling policies, REST endpoints exposed via `app.api.integrations`.
- **Control plane**: Not involved (single-tenant scope).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports core types and protocols. | — |
| types.py | Types | IntegrationLeaf, IntegrationTree, IntegrationSyncResult, IntegrationNodeKind, IntegrationSyncOutcome. | — |
| protocols.py | Protocol | IntegrationProvider protocol: fetch(), get_sync_cursor(), validate_connection(). | ✅ |
| tree_manager.py | Core | IntegrationTreeManager: adaptive hierarchical tree backed by GraphStore. | ✅ |
| fetcher.py | Core | IntegrationFetcher: concurrent pull scheduler with idempotent dedup. | ✅ |
| summarizer.py | Core | IntegrationSummariser: bottom-up LLM tree summarisation. | ✅ |
