# infra/state_archive/

## Overview
Generic mechanism layer for moving or protecting a whole state directory: consistent SQLite snapshots, a verified zip container with a trailing manifest, and a crash-recoverable promotion of a staged tree into a live root. It never decides which application paths are archived; callers pass explicit sources and top-level names.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Facade | Public API re-exports. | ✅ |
| `models.py` | Core | Manifest/entry value objects, limits, typed archive errors (verification, write, insufficient space). | ✅ |
| `snapshot.py` | Core | `snapshot_sqlite` (online backup or `VACUUM INTO`) and header-based `is_sqlite_file`. | ✅ |
| `writer.py` | Core | `ArchiveWriter`: streams files and SQLite snapshots into a zip, records sources it cannot open as skipped, aborts on a failure mid-member, publishes atomically. | ✅ |
| `reader.py` | Core | `read_manifest` (zip-slip/symlink/duplicate/limits checks) and `extract_payload` (size + SHA-256 verified, all-or-nothing). | ✅ |
| `promotion.py` | Core | `promote` / `recover_interrupted` / `rollback` with a filesystem-inspecting journal. | ✅ |

## Contracts
- Archive layout: `manifest.json` plus `payload/<relative path>`; format id `myrm-state-archive` v1.
- Promotion runs before any process opens the affected files; entries are top-level names, so SQLite `-wal`/`-shm` siblings must be listed with their database.
- A source that cannot be opened is skipped and listed in the manifest's `skipped`. A zip cannot drop a member once it has begun, so a read or write failure after that point raises `ArchiveWriteError` and the archive is never published; the reader rejects members the manifest does not declare.
- Only SQLite sources are point-in-time consistent. Plain files are streamed as they are on disk, so a file rewritten in place while an export runs can be captured mid-write; route such files through `add_sqlite` or write them atomically.
- Depends only on `infra.sqlite_backup` and `infra.atomic_write`.
