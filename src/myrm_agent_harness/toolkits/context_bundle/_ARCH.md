## Overview
Unified context bundle abstraction for memory, workspace, offload, and archive scenes.
Provides a thin Facade over existing storage and volume paths without duplicating
MemoryManager, vector search, or Agent runtime logic.

Detailed design: [CONTEXT_BUNDLE_SYSTEM.md](CONTEXT_BUNDLE_SYSTEM.md)

## File Index

| File | Role | Description |
|------|------|-------------|
| `spec.py` | Core | `ContextBundleSpec`, `ContextScene`, `IncognitoPolicy`, `AgentContextOverlay` |
| `volume.py` | Core | `VolumeLayout` — MYRM_DATA_DIR path mapping + manifest |
| `facade.py` | Core | `ContextBundleFacade` — memory/storage/offload/index/hooks entry; `vault_dir()` delegates to `core.artifacts.paths` |
| `index.py` | Protocol | `ContextIndexRegistry` extension mount point (optional index backends) |
| `hooks.py` | Protocol | `ContextLifecycleHooks` mount point for OpenClaw-style lifecycle |
| `health.py` | Core | Scene health probe adapters (`MemorySceneHealthBackend`, `WorkspaceSceneHealthBackend`, `StaticSceneHealthBackend`) |
| `migrate.py` | Core | Dry-run + non-destructive manifest/directory migration |
| `__init__.py` | Package | Public exports |

## Boundaries

- **Reuses**: `toolkits.storage.LocalStorageBackend`, existing memory/offload paths
- **Does not import**: `agent/`, `runtime/` (toolkits gate)
- **Does not implement**: RemoteSync, BM25 recall, unified HTTP search API (workspace recall uses agentic grep/glob)

## Volume Layout (V1)

```
{MYRM_DATA_DIR}/
  context_bundle_manifest.json
  memory/           ← ContextScene.MEMORY
  harness/          ← workspace scene default + storage root
    .context/       ← ContextScene.OFFLOAD (tool/conversation offload)
    archives/       ← ContextScene.ARCHIVE
  qdrant/
```

Task workspace cwd (user-selected project directory) is expressed via
`AgentContextOverlay.task_workspace_root` on the Server binding, decoupled from memory paths.

### Task workspace artifact vault

Large tool/sub-agent payloads for a task cwd are stored outside the memory bundle:

| Path | Purpose |
|------|---------|
| `{task_workspace}/.agent/vault/objects/` | Binary blobs referenced by `vault://<uuid>` |
| `{task_workspace}/.agent/vault/meta/` | Vault object metadata JSON |

Override layout for deployments: set infra env `AGENT_WORKSPACE_VAULT_RELATIVE` (relative segments only).
Single source of truth: `myrm_agent_harness.core.artifacts.paths`.
