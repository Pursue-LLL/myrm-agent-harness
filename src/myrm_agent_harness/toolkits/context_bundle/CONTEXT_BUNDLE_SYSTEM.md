# Context Bundle System

## Design Goal

Provide a single volume contract for the memory and workspace scenes
so Server and Harness share one namespace layout under `MYRM_DATA_DIR`, without duplicating
MemoryManager, vector search, or Agent runtime logic.

## Architecture

```
Server (ContextBundleService, ResolvedContextBinding)
        │
        ▼
Harness (ContextBundleFacade)
        ├── memory_path      → MemoryManager (existing)
        ├── harness_path     → LocalStorageBackend / workspace scene
        └── index registry   → ContextIndexRegistry (per-scene health probes)
```

## Volume Layout (schema_version = 1)

| Path | Scene |
|------|-------|
| `{state_dir}/memory/` | MEMORY |
| `{state_dir}/harness/` | WORKSPACE (default) + storage root |
| `{state_dir}/context_bundle_manifest.json` | manifest |

Context offload files (compacted outputs, evicted outputs, snapshots) belong to the runtime
context root (`runtime/paths/execution_paths`), not to the bundle: the layout never declares a
second path for them.

Task cwd (user project directory) is not part of the bundle: callers pass it per call
(e.g. `vault_dir(workspace_root)`), which keeps it decoupled from long-lived memory paths.

### Task workspace artifact vault

Sub-agent and tool outputs too large for the LLM context use the Shared Artifact Vault
(`agent/artifacts/vault.py`) under the task workspace — default `{task_workspace}/.agent/vault`.
Agents exchange `vault://<uuid>` pointers only (zero-copy within the sandbox).
Path resolution: `core/artifacts/paths.py` (`AGENT_WORKSPACE_VAULT_RELATIVE` optional override).
`ContextBundleFacade.vault_dir()` exposes the same path for health and server GC alignment.

## Server Contract

- `ResolvedContextBinding` extends memory scope fields with bundle metadata.
- `GET /context-bundle` — health DTO for Settings → Developer → System Health (`SystemHealthPanel`).
- `POST /context-bundle/migrate/dry-run` — non-destructive migration preview.
- `POST /context-bundle/migrate/apply` — non-destructive manifest + directory init.

## Workspace Search

Workspace file discovery uses agentic search (`grep_tool` / `glob_tool`) via
`FilesystemFileSearchMiddleware` on the Server agent factory. No vector index
or `/context-search` HTTP endpoint.

## Health Probes

| Scene | Probe |
|-------|-------|
| MEMORY | `MemorySceneHealthBackend` — memory path writability |
| WORKSPACE | `WorkspaceSceneHealthBackend` — harness path + optional ripgrep availability |

## Out of Scope

- Unified `context_search` HTTP API — workspace recall uses agentic grep/glob only
- BM25 tri-path workspace recall (#3)
- Bundle tarball export/import (owned by the Server's instance archive)
- Remote sync (#9)
