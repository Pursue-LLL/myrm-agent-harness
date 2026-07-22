# observers/

## Overview
Observers module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Observers module. | — |
| artifact_observer.py | Core | Artifact observer for registering generated files and pushing realtime content. | ✅ |
| base.py | Core | Provides FileOperationObserver. | ✅ |
| diff_collector.py | Core | Diff collector — cumulative unified diffs via SnapshotStore baseline; corrects blank-CREATE+MODIFY to avoid /dev/null hunks. | ✅ |
| format_observer.py | Core | Auto-format observer — runs code formatters after AI file edits. | ✅ |
| observer_manager.py | Core | Provides ObserverManager. | ✅ |
| snapshot_observer.py | Core | File snapshot observer — captures pre-modification content for revert; oversized/store-full skips record metadata-only (`skip_reason`, `revertible=false`) for honest UX. | ✅ |
| tracker_observer.py | Core | Provides TrackerObserver. | ✅ |
| activity_observer.py | Core | File activity observer. Records file writes to FileActivityTracker for conflict detection. | ✅ |

## Key Dependencies

- `runtime`
- `toolkits`
- `utils`
