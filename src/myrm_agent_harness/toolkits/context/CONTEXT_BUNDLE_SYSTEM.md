# Context Bundle System

## Design Goal

Provide a single volume contract for memory, workspace, session offload, and archive scenes
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
        ├── offload_root     → runtime/context/offload.py paths
        ├── archive_path     → future export/import (#8)
        ├── index registry   → ContextIndexRegistry (per-scene health probes)
        └── lifecycle hooks  → OpenClaw-style phases (registration only)
```

## Volume Layout (schema_version = 1)

| Path | Scene |
|------|-------|
| `{state_dir}/memory/` | MEMORY |
| `{state_dir}/harness/` | WORKSPACE (default) + storage root |
| `{state_dir}/harness/.context/` | OFFLOAD |
| `{state_dir}/harness/archives/` | ARCHIVE |
| `{state_dir}/context_bundle_manifest.json` | manifest |

Task cwd (user project directory) is carried on `AgentContextOverlay.task_workspace_root`
in `ResolvedContextBinding`, decoupled from long-lived memory paths.

## Server Contract

- `ResolvedContextBinding` extends memory scope fields with bundle metadata.
- `GET /context-bundle` — health DTO for Settings and Doctor.
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
| OFFLOAD / ARCHIVE | `StaticSceneHealthBackend` — path writability |

## Out of Scope

- Unified `context_search` HTTP API — removed; use agentic grep/glob instead
- BM25 tri-path workspace recall (#3)
- Bundle tarball export/import (#8)
- Remote sync (#9)
