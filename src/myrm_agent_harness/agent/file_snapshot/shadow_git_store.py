"""Shadow Git snapshot store — workspace versioning via an isolated bare repo.

All git operations use GIT_DIR + GIT_WORK_TREE + GIT_INDEX_FILE environment
variables to isolate the shadow store from the user's repository. The user's
.git, .gitignore, and git config are never touched.

Storage layout (single shared store, git objects deduplicated across projects):

    {MYRM_DATA_DIR}/file_snapshots/
        store/                          — shared bare-ish git repo
            HEAD, config, objects/      — standard git internals (shared)
            refs/myrm/<hash16>          — per-project branch tip
            indexes/<hash16>            — per-project git index
            projects/<hash16>.json      — {workdir, created_at, last_touch}
            info/exclude                — default excludes (shared)

[INPUT]
shadow_git_maintenance::ShadowGitMaintenance (POS: Maintenance mixin for pruning, repair, workspace validation.)

[OUTPUT]
ShadowGitSnapshotStore: Shadow Git-backed file snapshot store with env-variable isolation.

[POS]
Shadow Git file snapshot store using an isolated bare repo with env-variable
isolation (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_CONFIG_GLOBAL).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .shadow_git_maintenance import ShadowGitMaintenance
from .types import (
    FileChange,
    FileDiff,
    FileSnapshotInfo,
    RestoreResult,
    SnapshotId,
    SnapshotTrigger,
)

logger = get_agent_logger(__name__)

_REFS_PREFIX = "refs/myrm"
_INDEXES_DIR = "indexes"
_PROJECTS_DIR = "projects"
_MAX_SNAPSHOTS_PER_PROJECT = 50

_COMMIT_ID_RE = re.compile(r"^[0-9a-f]{40}$")

DEFAULT_EXCLUDES = (
    "node_modules/\n.venv/\nvenv/\nenv/\n__pycache__/\n.cache/\n.pytest_cache/\n"
    ".mypy_cache/\n.ruff_cache/\ndist/\nbuild/\ntarget/\nout/\n.next/\n.nuxt/\n"
    ".git/\n.hg/\n.svn/\n.DS_Store\nThumbs.db\n.myrm/\n"
    "*.sqlite\n*.sqlite3\n*.db\n*.mp4\n*.mov\n*.avi\n*.zip\n*.tar.gz\n*.tar.bz2\n"
    "*.7z\n*.rar\n*.jar\n*.war\n*.pyc\n*.pyo\n.idea/\n.vscode/\n*.log\n"
)


def _project_hash(working_dir: str) -> str:
    """Deterministic per-project hash from absolute path."""
    abs_path = str(Path(working_dir).expanduser().resolve())
    return hashlib.sha256(abs_path.encode()).hexdigest()[:16]


def _validate_commit_hash(value: str) -> bool:
    return bool(_COMMIT_ID_RE.match(value))


def _safe_path(base: Path, user_input: str) -> Path:
    """Resolve user input against base, preventing path traversal."""
    resolved = (base / user_input).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal detected: {user_input}")
    return resolved


def _default_store_path() -> Path:
    data_dir = os.environ.get("MYRM_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "file_snapshots"
    return Path.home() / ".myrm" / "file_snapshots"


class ShadowGitSnapshotStore(ShadowGitMaintenance):
    """Shadow Git-backed file snapshot store.

    Uses a single shared bare repo with per-project refs and indexes
    for content deduplication and complete isolation from user repos.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = store_path or _default_store_path()
        self._git_dir = self._store_path / "store"
        self._refs_prefix = _REFS_PREFIX
        self._projects_dir = _PROJECTS_DIR
        self._indexes_dir = _INDEXES_DIR
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return

        self._git_dir.mkdir(parents=True, exist_ok=True)

        head_file = self._git_dir / "HEAD"
        if not head_file.exists() or head_file.stat().st_size == 0:
            await self._init_bare_repo()

        self._initialized = True

    async def _init_bare_repo(self) -> None:
        """Initialize the shared bare repo with proper excludes."""
        init_env = os.environ.copy()
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            init_env.pop(k, None)
        init_env["GIT_CONFIG_GLOBAL"] = os.devnull
        init_env["GIT_CONFIG_SYSTEM"] = os.devnull
        await self._run_cmd("git", "init", "--bare", str(self._git_dir), env=init_env)

        await self._git_in_store("config", "gc.auto", "0")
        await self._git_in_store("config", "user.name", "Myrm Snapshot")
        await self._git_in_store("config", "user.email", "snapshot@myrm.local")

        exclude_dir = self._git_dir / "info"
        exclude_dir.mkdir(parents=True, exist_ok=True)
        (exclude_dir / "exclude").write_text(DEFAULT_EXCLUDES)

        (self._git_dir / _INDEXES_DIR).mkdir(exist_ok=True)
        (self._git_dir / _PROJECTS_DIR).mkdir(exist_ok=True)

    def _project_ref(self, proj_hash: str) -> str:
        return f"{_REFS_PREFIX}/{proj_hash}"

    def _project_index(self, proj_hash: str) -> Path:
        return self._git_dir / _INDEXES_DIR / proj_hash

    def _project_meta_path(self, proj_hash: str) -> Path:
        return self._git_dir / _PROJECTS_DIR / f"{proj_hash}.json"

    def _git_env(self, working_dir: str, proj_hash: str) -> dict[str, str]:
        """Build an isolated git environment."""
        env = os.environ.copy()
        env["GIT_DIR"] = str(self._git_dir)
        env["GIT_WORK_TREE"] = str(Path(working_dir).resolve())
        env["GIT_INDEX_FILE"] = str(self._project_index(proj_hash))
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        env.pop("GIT_AUTHOR_NAME", None)
        env.pop("GIT_AUTHOR_EMAIL", None)
        env.pop("GIT_COMMITTER_NAME", None)
        env.pop("GIT_COMMITTER_EMAIL", None)
        return env

    async def _git_in_store(self, *args: str) -> str:
        return await self._run_cmd("git", *args, env=self._bare_env())

    async def _run_cmd(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        stdin_data: bytes | None = None,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_data else asyncio.subprocess.DEVNULL,
            env=env,
        )
        stdout, stderr = await proc.communicate(input=stdin_data)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Command {' '.join(args)} failed (rc={proc.returncode}): {stderr.decode().strip()}"
            )
        return stdout.decode().strip()

    def _touch_project(self, proj_hash: str, working_dir: str) -> None:
        """Update project metadata (last_touch, workdir)."""
        meta_path = self._project_meta_path(proj_hash)
        now = time.time()
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                meta["last_touch"] = now
            except (json.JSONDecodeError, KeyError):
                meta = {"workdir": working_dir, "created_at": now, "last_touch": now}
        else:
            meta = {"workdir": working_dir, "created_at": now, "last_touch": now}
        meta_path.write_text(json.dumps(meta, indent=2))

    # ------------------------------------------------------------------
    # FileSnapshotProtocol implementation
    # ------------------------------------------------------------------

    async def take_snapshot(
        self,
        working_dir: str,
        trigger: SnapshotTrigger,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SnapshotId:
        """Take a snapshot of the current workspace state."""
        await self._ensure_initialized()

        wp = Path(working_dir).resolve()
        if not wp.exists() or not wp.is_dir():
            raise ValueError(f"Workspace does not exist: {working_dir}")

        if str(wp) in ("/", str(Path.home())):
            raise ValueError(f"Refusing to snapshot root or home directory: {wp}")

        if await self.is_oversized_workspace(str(wp)):
            raise ValueError(f"Workspace exceeds file count limit")

        proj_hash = _project_hash(str(wp))
        env = self._git_env(str(wp), proj_hash)
        ref = self._project_ref(proj_hash)

        await self._run_cmd("git", "add", "--all", env=env)
        await self.drop_oversized_from_index(env, wp)

        # Resolve parent commit for skip-detection and CAS
        parent: str | None = None
        try:
            parent = await self._run_cmd("git", "rev-parse", "--verify", ref, env=env)
        except RuntimeError:
            pass

        # Skip if no files changed since last snapshot (avoids redundant commits)
        if parent:
            try:
                await self._run_cmd("git", "diff-index", "--cached", "--quiet", parent, env=env)
                logger.debug("No changes since last snapshot for %s, skipping", working_dir)
                return parent
            except RuntimeError:
                pass  # diff-index returns non-zero when changes exist

        tree_hash = await self._run_cmd("git", "write-tree", env=env)

        msg_lines = [
            f"snapshot {trigger.value}: {description}",
            "",
            f"trigger={trigger.value}",
            f"timestamp={time.time()}",
            f"working_dir={wp}",
        ]
        if metadata:
            msg_lines.append(f"metadata={json.dumps(metadata, separators=(',', ':'))}")
        commit_msg = "\n".join(msg_lines)

        parent_args = ["-p", parent] if parent else []

        commit_hash = await self._run_cmd(
            "git", "commit-tree", tree_hash, *parent_args,
            env=env,
            stdin_data=commit_msg.encode(),
        )

        # CAS: pass old value to prevent concurrent overwrites
        update_args = ["git", "update-ref", ref, commit_hash]
        if parent:
            update_args.append(parent)
        await self._run_cmd(*update_args, env=env)
        self._touch_project(proj_hash, str(wp))
        logger.info("Shadow-git snapshot %s for %s (trigger=%s)", commit_hash[:12], working_dir, trigger.value)

        await self.maybe_prune()
        return commit_hash

    async def restore(
        self,
        snapshot_id: SnapshotId,
        files: list[str] | None = None,
    ) -> RestoreResult:
        """Restore workspace to a snapshot state."""
        await self._ensure_initialized()

        if not _validate_commit_hash(snapshot_id):
            return RestoreResult(success=False, snapshot_id=snapshot_id, files_restored=0, error="Invalid snapshot ID")

        proj_hash, working_dir = await self.find_project_for_commit(snapshot_id)
        if not proj_hash or not working_dir:
            return RestoreResult(success=False, snapshot_id=snapshot_id, files_restored=0, error="Snapshot not found")

        wp = Path(working_dir)
        if not wp.exists():
            return RestoreResult(success=False, snapshot_id=snapshot_id, files_restored=0, error=f"Workspace no longer exists: {working_dir}")

        pre_rollback_id: str | None = None
        try:
            pre_rollback_id = await self.take_snapshot(working_dir, SnapshotTrigger.PRE_ROLLBACK, f"Pre-rollback before restoring {snapshot_id[:12]}")
        except Exception as e:
            logger.warning("Failed to create pre-rollback snapshot: %s", e)

        env = self._git_env(working_dir, proj_hash)

        try:
            if files:
                for f in files:
                    safe = _safe_path(wp, f)
                    rel = str(safe.relative_to(wp))
                    await self._run_cmd("git", "checkout", snapshot_id, "--", rel, env=env)
                restored = len(files)
            else:
                await self._run_cmd("git", "read-tree", snapshot_id, env=env)
                await self._run_cmd("git", "checkout-index", "--all", "--force", env=env)
                ls_output = await self._run_cmd("git", "ls-tree", "-r", "--name-only", snapshot_id, env=env)
                restored = len(ls_output.splitlines())

            return RestoreResult(
                success=True,
                snapshot_id=snapshot_id,
                files_restored=restored,
                pre_rollback_snapshot_id=pre_rollback_id,
            )
        except Exception as e:
            logger.error("Restore failed for %s: %s", snapshot_id, e)
            return RestoreResult(
                success=False,
                snapshot_id=snapshot_id,
                files_restored=0,
                pre_rollback_snapshot_id=pre_rollback_id,
                error=str(e),
            )

    async def diff(self, snapshot_id: SnapshotId) -> FileDiff:
        """Compare a snapshot with current workspace state."""
        await self._ensure_initialized()

        if not _validate_commit_hash(snapshot_id):
            return FileDiff(snapshot_id=snapshot_id)

        proj_hash, working_dir = await self.find_project_for_commit(snapshot_id)
        if not proj_hash or not working_dir:
            return FileDiff(snapshot_id=snapshot_id)

        env = self._git_env(working_dir, proj_hash)

        try:
            await self._run_cmd("git", "add", "--all", env=env)
            current_tree = await self._run_cmd("git", "write-tree", env=env)
            diff_output = await self._run_cmd(
                "git", "diff-tree", "-r", "--name-status", snapshot_id, current_tree, env=env,
            )
            numstat_output = await self._run_cmd(
                "git", "diff-tree", "-r", "--numstat", snapshot_id, current_tree, env=env,
            )
        except RuntimeError as e:
            logger.warning("Diff failed: %s", e)
            return FileDiff(snapshot_id=snapshot_id)

        line_stats: dict[str, tuple[int | None, int | None]] = {}
        for line in numstat_output.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added_str, deleted_str, filepath = parts
            added = int(added_str) if added_str != "-" else None
            deleted = int(deleted_str) if deleted_str != "-" else None
            line_stats[filepath] = (added, deleted)

        changes: list[FileChange] = []
        wp = Path(working_dir)
        for line in diff_output.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, filepath = parts[0].strip(), parts[1].strip()
            change_type = {"A": "added", "D": "deleted", "M": "modified"}.get(status, "modified")
            new_size: int | None = None
            if change_type != "deleted":
                try:
                    new_size = (wp / filepath).stat().st_size
                except OSError:
                    pass
            lines_added, lines_deleted = line_stats.get(filepath, (None, None))
            changes.append(FileChange(
                path=filepath,
                change_type=change_type,
                new_size=new_size,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
            ))

        return FileDiff(snapshot_id=snapshot_id, changes=changes, total_changes=len(changes))

    async def list_snapshots(
        self,
        working_dir: str,
        limit: int = 20,
    ) -> list[FileSnapshotInfo]:
        """List snapshots for a workspace, newest first."""
        await self._ensure_initialized()

        proj_hash = _project_hash(working_dir)
        ref = self._project_ref(proj_hash)
        env = self._git_env(working_dir, proj_hash)

        try:
            log_output = await self._run_cmd(
                "git", "log", ref, f"--max-count={limit}",
                "--format=%H%n%ct%n%B%n---END---",
                env=env,
            )
        except RuntimeError:
            return []

        snapshots: list[FileSnapshotInfo] = []

        for entry in log_output.split("---END---"):
            lines = entry.strip().splitlines()
            if len(lines) < 3:
                continue

            commit_hash = lines[0].strip()
            try:
                created_at = float(lines[1].strip())
            except ValueError:
                created_at = 0.0

            trigger = SnapshotTrigger.MANUAL
            description = ""
            file_count = 0
            meta: dict[str, Any] = {}

            for line in lines[2:]:
                if line.startswith("trigger="):
                    try:
                        trigger = SnapshotTrigger(line.split("=", 1)[1])
                    except ValueError:
                        pass
                elif line.startswith("metadata="):
                    try:
                        meta = json.loads(line.split("=", 1)[1])
                    except (json.JSONDecodeError, IndexError):
                        pass
                elif line.startswith("snapshot "):
                    description = line

            try:
                tree_output = await self._run_cmd("git", "ls-tree", "-r", "--name-only", commit_hash, env=env)
                file_count = len(tree_output.splitlines())
            except RuntimeError:
                pass

            snapshots.append(FileSnapshotInfo(
                snapshot_id=commit_hash,
                working_dir=working_dir,
                trigger=trigger,
                created_at=created_at,
                file_count=file_count,
                description=description,
                metadata=meta,
            ))

        return snapshots

    async def get_snapshot_info(self, snapshot_id: SnapshotId) -> FileSnapshotInfo | None:
        """Get metadata for a specific snapshot by commit hash."""
        await self._ensure_initialized()

        if not _validate_commit_hash(snapshot_id):
            return None

        proj_hash, working_dir = await self.find_project_for_commit(snapshot_id)
        if not proj_hash or not working_dir:
            return None

        env = self._git_env(working_dir, proj_hash)

        try:
            log_output = await self._run_cmd(
                "git", "log", snapshot_id, "--max-count=1",
                "--format=%H%n%ct%n%B",
                env=env,
            )
        except RuntimeError:
            return None

        lines = log_output.strip().splitlines()
        if len(lines) < 3:
            return None

        commit_hash = lines[0].strip()
        try:
            created_at = float(lines[1].strip())
        except ValueError:
            created_at = 0.0

        trigger = SnapshotTrigger.MANUAL
        description = ""
        meta: dict[str, Any] = {}

        for line in lines[2:]:
            if line.startswith("trigger="):
                try:
                    trigger = SnapshotTrigger(line.split("=", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("metadata="):
                try:
                    meta = json.loads(line.split("=", 1)[1])
                except (json.JSONDecodeError, IndexError):
                    pass
            elif line.startswith("snapshot "):
                description = line

        return FileSnapshotInfo(
            snapshot_id=commit_hash,
            working_dir=working_dir,
            trigger=trigger,
            created_at=created_at,
            file_count=0,
            description=description,
            metadata=meta,
        )

    async def delete_snapshot(self, snapshot_id: SnapshotId) -> bool:
        """Snapshots are cleaned up via the pruning mechanism. Returns True for protocol compatibility."""
        return True

    async def cleanup(
        self,
        working_dir: str,
        max_snapshots: int = _MAX_SNAPSHOTS_PER_PROJECT,
    ) -> int:
        """Cleanup old snapshots for a project, keeping the most recent."""
        await self._ensure_initialized()

        snapshots = await self.list_snapshots(working_dir, limit=max_snapshots + 100)
        if len(snapshots) <= max_snapshots:
            return 0

        proj_hash = _project_hash(working_dir)
        ref = self._project_ref(proj_hash)
        env = self._git_env(working_dir, proj_hash)

        keep = snapshots[max_snapshots - 1]
        try:
            await self._run_cmd("git", "update-ref", ref, keep.snapshot_id, env=env)
            deleted = len(snapshots) - max_snapshots
            logger.info("Pruned %d old snapshots for %s", deleted, working_dir)
            return deleted
        except RuntimeError as e:
            logger.warning("Cleanup failed for %s: %s", working_dir, e)
            return 0

    async def repair_if_corrupted(self) -> bool:
        """Check for corruption and re-init if needed."""
        needs_repair = await super().repair_if_corrupted()
        if needs_repair:
            self._initialized = False
            await self._ensure_initialized()
        return needs_repair
