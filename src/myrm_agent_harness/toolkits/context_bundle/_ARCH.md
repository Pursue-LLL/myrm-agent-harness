## Overview
Unified context bundle abstraction for the memory and workspace scenes.
Provides a thin Facade over existing storage and volume paths without duplicating
MemoryManager, vector search, or Agent runtime logic.

Detailed design: [CONTEXT_BUNDLE_SYSTEM.md](CONTEXT_BUNDLE_SYSTEM.md)

## File Index

| File | Role | Description |
|------|------|-------------|
| `spec.py` | Core | `ContextBundleSpec`, `ContextScene` |
| `volume.py` | Core | `VolumeLayout` — MYRM_DATA_DIR path mapping + manifest |
| `facade.py` | Core | `ContextBundleFacade` — memory/storage/index entry; `vault_dir()` delegates to `core.artifacts.paths` |
| `index.py` | Protocol | `ContextIndexRegistry` extension mount point (optional index backends) |
| `health.py` | Core | Scene health probe adapters (`MemorySceneHealthBackend`, `WorkspaceSceneHealthBackend`) |
| `migrate.py` | Core | Dry-run + non-destructive manifest/directory migration |
| `__init__.py` | Package | Public exports |

## Boundaries

- **Reuses**: `toolkits.storage.LocalStorageBackend`, existing memory paths
- **Does not import**: `agent/`, `runtime/` (toolkits gate)
- **Does not implement**: RemoteSync, BM25 recall, unified HTTP search API (workspace recall uses agentic grep/glob)

## Volume Layout (V1)

```
{MYRM_DATA_DIR}/
  context_bundle_manifest.json
  memory/           ← ContextScene.MEMORY
  harness/          ← workspace scene default + storage root
  qdrant/
```

Task workspace cwd (user-selected project directory) is not part of the bundle: callers pass it per
call (e.g. `vault_dir(workspace_root)`), decoupled from memory paths.

### Task workspace artifact vault

Large tool/sub-agent payloads for a task cwd are stored outside the memory bundle:

| Path | Purpose |
|------|---------|
| `{task_workspace}/.agent/vault/objects/` | Binary blobs referenced by `vault://<uuid>` |
| `{task_workspace}/.agent/vault/meta/` | Vault object metadata JSON |

Override layout for deployments: set infra env `AGENT_WORKSPACE_VAULT_RELATIVE` (relative segments only).
Single source of truth: `myrm_agent_harness.core.artifacts.paths`.
