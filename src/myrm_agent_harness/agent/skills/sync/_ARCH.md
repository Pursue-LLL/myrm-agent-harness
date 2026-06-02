# Skill Sync Architecture

## Purpose

Bidirectional skill synchronization enabling collective skill evolution across devices and sandboxes. Inspired by SkillClaw's "multi-user collective evolution" but adapted for our three deployment modes (Local/Tauri, SaaS, Community).

## Design Principles

1. **Protocol-first**: `SkillSyncProtocol` and `SkillQualityGateProtocol` are framework-defined interfaces. Business layer provides implementations.
2. **Reuse infrastructure**: Leverages existing `StorageProvider`, `SkillPacker`/`SkillUnpacker`, and `IdleTaskRegistry` — zero new storage primitives.
3. **Incremental sync**: `SkillSyncManifest` (SQLite) tracks per-skill SHA256 hashes and timestamps for efficient delta sync.
4. **Quality gate**: Only skills meeting minimum thresholds (execution count, success rate) get pushed to shared repositories.

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
| SaaS | `HTTPSyncBackend` (server layer) | Control-plane shared repo | Business-defined LLM gate |
| Community | `HTTPSyncBackend` | Community marketplace API | LLM + admin review |

## Conflict Resolution

Conflicts occur when both local and remote versions changed since last sync. Strategies:
- `REMOTE_WINS`: Accept remote (safe for pull-from-marketplace)
- `LOCAL_WINS`: Keep local (safe for push-back)
- `NEWER_WINS`: Timestamp comparison
- `SKIP`: Leave unresolved, manual intervention

## Integration Points

- **Evolution Engine**: Calls `manager.register_local_skill()` after skill creation/update
- **IdleWorker**: Periodically triggers `full_sync()` via `skill_sync` task type
- **Server API**: Exposes sync status + manual trigger endpoints
- **Frontend**: Displays sync status indicator + manual sync button
