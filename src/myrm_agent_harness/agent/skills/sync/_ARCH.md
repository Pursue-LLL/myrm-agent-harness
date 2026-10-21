# Skill Sync Architecture

## Purpose

Bidirectional skill synchronization enabling collective skill evolution across devices and sandboxes. Inspired by SkillClaw's "multi-user collective evolution" but adapted for our three deployment modes (Local/Tauri, SaaS, Community).

## Design Principles

1. **Protocol-first**: `SkillSyncProtocol` and `SkillQualityGateProtocol` are framework-defined interfaces. Business layer provides implementations.
2. **Reuse infrastructure**: Leverages existing `StorageProvider`, `SkillPacker`/`SkillUnpacker`, and `IdleTaskRegistry` — zero new storage primitives.
3. **Incremental sync**: `SkillSyncManifest` (SQLite) tracks per-skill SHA256 hashes and timestamps for efficient delta sync.
4. **Quality gate**: Only skills meeting minimum thresholds (execution count, success rate) get pushed to shared repositories.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill sync module exports: protocols, manager, manifest, backends, quality gate. | — |
| types.py | Core | Frozen dataclasses for sync status, push/pull results, and gate verdicts. | ✅ |
| protocols.py | Core | SkillSyncProtocol and SkillQualityGateProtocol framework interfaces. | ✅ |
| manifest.py | Core | SkillSyncManifest SQLite persistence for per-skill SHA256 hashes and sync timestamps. | ✅ |
| quality_gate.py | Core | ThresholdQualityGate default implementation for push validation. | ✅ |
| manager.py | Core | SkillSyncManager orchestrator: pull-first full_sync, push with quality gate. | ✅ |
| local_sync.py | Core | LocalFSSyncBackend using StorageProvider for multi-device file-system sync. | ✅ |
| idle_integration.py | Core | IdleWorker bridge registering skill_sync periodic task. | ✅ |

## Component Map

```
sync/
├── __init__.py          # Module exports
├── _ARCH.md             # This file
├── types.py             # Data structures (frozen dataclasses)
├── protocols.py         # SkillSyncProtocol + SkillQualityGateProtocol
├── manifest.py          # SkillSyncManifest (SQLite state persistence)
├── quality_gate.py      # ThresholdQualityGate (default impl)
├── manager.py           # SkillSyncManager (orchestrator)
├── local_sync.py        # LocalFSSyncBackend (StorageProvider-based)
└── idle_integration.py  # IdleWorker registration bridge
```

## Data Flow

```
Evolution Engine ──▶ register_local_skill() ──▶ Manifest (local_ahead)
                                                      │
IdleWorker ─── skill_sync task ──▶ SkillSyncManager.full_sync()
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                    pull_shared_skills()     push_evolved_skills()
                              │                       │
                              ▼                       ▼
                    SyncBackend.pull_skills() QualityGate.evaluate()
                              │                       │
                              ▼                       ▼
                    Unpack + write local     SkillPacker.package_files()
                                                      │
                                                      ▼
                                            SyncBackend.push_skills()
                                                      │
                                                      ▼
                                            Manifest.mark_pushed()
```

## Deployment Mode Mapping

| Mode | SyncBackend | Shared Medium | Quality Gate |
|------|-------------|---------------|--------------|
| Local/Tauri | `LocalFSSyncBackend` | iCloud Drive / Dropbox / NAS | `ThresholdQualityGate` |
| SaaS | `HTTPSyncBackend` (planned, not yet implemented) | Control-plane shared repo | Business-defined LLM gate |
| Community | `HTTPSyncBackend` (planned) | Community marketplace API | LLM + admin review |

## Conflict Resolution

The current implementation uses a **pull-first** strategy (`full_sync()` pulls before pushing),
which effectively avoids conflicts by ensuring remote changes are applied before local pushes.

The `SkillSyncProtocol.resolve_conflict()` interface is defined and implemented but not yet
called by `SkillSyncManager` — it is a reserved extension point for future use if explicit
conflict detection is needed (e.g., in multi-user SaaS scenarios).

Defined strategies:
- `REMOTE_WINS`: Accept remote (safe for pull-from-marketplace)
- `LOCAL_WINS`: Keep local (safe for push-back)
- `NEWER_WINS`: Reserved, currently falls back to `SKIP`
- `SKIP`: Leave unresolved, local version kept

## Integration Points

- **Evolution Engine**: Calls `manager.register_local_skill()` after skill creation/update
- **IdleWorker**: Periodically triggers `full_sync()` via `skill_sync` task type
- **Server API**: Exposes sync status + manual trigger endpoints
- **Frontend**: Displays sync status indicator + manual sync button
