"""Shadow Git maintenance utilities — pruning, repair, and workspace validation.

[INPUT]
shadow_git_store::_REFS_PREFIX, _PROJECTS_DIR (POS: Shadow Git constants.)

[OUTPUT]
ShadowGitMaintenance: Mixin providing auto-prune, orphan detection, repair,
    oversized workspace detection, and project-commit lookup.

[POS]
Maintenance mixin for shadow Git snapshot stores. Handles auto-pruning of
orphan projects, global size cap enforcement, corruption repair, and
workspace size validation.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from pathlib import Path

from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_PRUNE_MARKER = ".last_prune"
_PRUNE_INTERVAL_S = 86400  # 24 hours
_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_FILE_COUNT = 50_000
_MAX_TOTAL_SIZE_MB = 2048  # 2 GB global cap

_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__"}


class ShadowGitMaintenance:
    """Mixin providing maintenance operations for ShadowGitSnapshotStore.

    Expects the host class to provide:
      - _git_dir: Path
      - _store_path: Path
      - _refs_prefix: str
      - _projects_dir: str
      - _indexes_dir: str
      - _project_ref(hash) -> str
      - _project_index(hash) -> Path
      - _project_meta_path(hash) -> Path
      - _run_cmd(*args, env, stdin_data) -> str
      - _git_in_store(*args) -> str
    """

    _git_dir: Path
    _store_path: Path
    _refs_prefix: str
    _projects_dir: str
    _indexes_dir: str

    def _project_ref(self, proj_hash: str) -> str: ...
    def _project_index(self, proj_hash: str) -> Path: ...
    def _project_meta_path(self, proj_hash: str) -> Path: ...
    async def _run_cmd(self, *args: str, env: dict[str, str] | None = None, stdin_data: bytes | None = None) -> str: ...
    async def _git_in_store(self, *args: str) -> str: ...

    def _bare_env(self) -> dict[str, str]:
        """Build a clean env for store-level git commands."""
        env = os.environ.copy()
        env["GIT_DIR"] = str(self._git_dir)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
        for k in ("GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(k, None)
        return env

    async def is_oversized_workspace(self, working_dir: str) -> bool:
        """Check if workspace has too many files to snapshot safely."""
        count = 0
        wp = Path(working_dir)
        try:
            for _root, dirs, files in os.walk(wp):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
                count += len(files)
                if count > _MAX_FILE_COUNT:
                    return True
        except OSError:
            return True
        return False

    async def drop_oversized_from_index(self, env: dict[str, str], wp: Path) -> None:
        """Remove files larger than max size from the git index."""
        try:
            ls_output = await self._run_cmd("git", "ls-files", "--cached", env=env)
        except RuntimeError:
            return

        to_remove: list[str] = []
        for line in ls_output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            file_path = wp / stripped
            try:
                if file_path.exists() and file_path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                    to_remove.append(stripped)
            except OSError:
                continue

        for f in to_remove:
            with contextlib.suppress(RuntimeError):
                await self._run_cmd("git", "rm", "--cached", "--quiet", f, env=env)

    async def find_project_for_commit(self, commit_hash: str) -> tuple[str | None, str | None]:
        """Find which project a commit belongs to by checking all refs."""
        projects_dir = self._git_dir / self._projects_dir
        if not projects_dir.exists():
            return None, None

        for meta_file in projects_dir.iterdir():
            if meta_file.suffix != ".json":
                continue
            proj_hash = meta_file.stem
            ref = self._project_ref(proj_hash)

            try:
                env = self._bare_env()
                await self._run_cmd("git", "merge-base", "--is-ancestor", commit_hash, ref, env=env)
            except RuntimeError:
                try:
                    tip = await self._run_cmd("git", "rev-parse", ref, env=env)
                    if tip.strip() != commit_hash:
                        continue
                except RuntimeError:
                    continue

            try:
                meta = json.loads(meta_file.read_text())
                return proj_hash, meta.get("workdir")
            except (json.JSONDecodeError, KeyError):
                continue

        return None, None

    async def maybe_prune(self) -> None:
        """Auto-prune orphan projects and run gc if needed (idempotent, once per interval)."""
        marker = self._store_path / _PRUNE_MARKER
        now = time.time()

        if marker.exists():
            try:
                last_prune = float(marker.read_text().strip())
                if now - last_prune < _PRUNE_INTERVAL_S:
                    return
            except (ValueError, OSError):
                pass

        await self._prune_orphan_projects()
        await self._enforce_global_size_cap()
        marker.write_text(str(now))

    async def _prune_orphan_projects(self) -> None:
        """Remove refs, indexes, and metadata for projects whose workdir no longer exists."""
        projects_dir = self._git_dir / self._projects_dir
        if not projects_dir.exists():
            return

        for meta_file in projects_dir.iterdir():
            if meta_file.suffix != ".json":
                continue
            try:
                meta = json.loads(meta_file.read_text())
                workdir = meta.get("workdir", "")
                if workdir and not Path(workdir).exists():
                    proj_hash = meta_file.stem
                    ref = self._project_ref(proj_hash)
                    try:
                        env = self._bare_env()
                        await self._run_cmd("git", "update-ref", "-d", ref, env=env)
                    except RuntimeError:
                        pass

                    index_file = self._project_index(proj_hash)
                    if index_file.exists():
                        index_file.unlink(missing_ok=True)
                    meta_file.unlink(missing_ok=True)
                    logger.info("Pruned orphan project %s (workdir: %s)", proj_hash, workdir)
            except (json.JSONDecodeError, OSError):
                continue

    async def _enforce_global_size_cap(self) -> None:
        """Run git gc when store exceeds the global size cap."""
        try:
            store_size_mb = sum(f.stat().st_size for f in self._git_dir.rglob("*") if f.is_file()) / (1024 * 1024)
            if store_size_mb > _MAX_TOTAL_SIZE_MB:
                await self._git_in_store("gc", "--prune=now")
                logger.info("Ran git gc (store was %.1f MB)", store_size_mb)
        except (OSError, RuntimeError) as e:
            logger.debug("Size check/gc failed: %s", e)

    async def repair_if_corrupted(self) -> bool:
        """Check for corruption and re-init if needed."""
        head_file = self._git_dir / "HEAD"
        if not head_file.exists() or head_file.stat().st_size == 0:
            logger.warning("Shadow store HEAD missing/empty, re-initializing")
            shutil.rmtree(self._git_dir, ignore_errors=True)
            # _initialized will be set to False by the caller
            return True
        return False
