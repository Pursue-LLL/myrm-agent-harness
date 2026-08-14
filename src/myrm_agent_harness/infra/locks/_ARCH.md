# locks/

## Overview
Unified locking mechanisms for concurrent operations.

## Scope & Semantics
- **Intra-sandbox asyncio coordination**: `FileLock` coordinates multiple
  asyncio tasks *within the same process* (e.g. DeliveryQueue workers
  preventing duplicate delivery). The design boundary is single-process
  coordination: the underlying `fcntl.flock` is per-inode and therefore also
  effective across processes, but cross-process locking is owned by the server
  layer (`filelock` library, `app/startup/server_lock.py`). Sandboxes are
  isolated, so there is no cross-sandbox contention.
- **Blocking**: `blocking=True` is rejected with `TypeError` (fail-fast).
  Synchronous `fcntl.flock` would freeze the asyncio event loop; callers that
  need to wait must use `blocking=False` with their own backoff/retry.
- **Lock modes**: only `exclusive` and `shared` are accepted; any other value
  is rejected with `ValueError` (fail-fast) so a typo can never silently
  downgrade an exclusive lock to a shared one.
- **Lock file location**: derived from a state directory. Callers pass a
  `lock_dir` (e.g. `base_dir / "locks"`); lock file names are sanitized from
  the resource id (path-injection safe).
- **Lock file lifecycle**: a lock file is **unlinked after release**. This is
  a deliberate decision, not an accident: locks are dynamic (one file per
  resource id, e.g. one per delivery), so keeping them would let the directory
  grow without bound. Unlinking is safe because coordination is confined to a
  single process with no cross-process window on the same inode. Do **not**
  switch to "keep the lock file" semantics borrowed from cross-process lock
  libraries (e.g. CoPaw) — those keep stable inodes precisely because multiple
  processes may still hold a descriptor to the old inode, which cannot happen
  here. On Windows, a shared lock degrades to exclusive (`msvcrt.locking` has
  no shared mode); this is a documented platform limit, not a bug.
- **Symlink safety**: lock files are opened with `O_NOFOLLOW` (when the
  platform exposes it), so a symlink planted in the lock directory is rejected
  instead of being followed and truncated — protecting arbitrary files the
  symlink might point at.
- **Crash safety**: fcntl locks are released by the OS when the process dies.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Unified locking mechanisms for concurrent operations. | — |
| file_lock.py | Core | Unified file locking implementation. Provides fcntl-based locks for coordinating asyncio tasks in the same sandbox process. | ✅ |
