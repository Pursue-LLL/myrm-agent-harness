"""Browser Doctor — stale automation sandbox cleanup.

Prunes leftover automation sandboxes (macOS ``*.code_sign_clone`` directories
created by Chrome-family browsers) once they are old enough and their browser is
no longer running, dry-run by default.

[INPUT]
- psutil (optional, process table: which browser apps are running)
- Info.plist of each running ``.app`` (CFBundleIdentifier, matches the ``<bundle id>.code_sign_clone`` directory name)

[OUTPUT]
- cleanup_stale_automation_sandboxes: dry-run-first sandbox prune returning a SandboxCleanupResult
- SandboxCleanupResult / SandboxFailure: typed shape of the prune summary

[POS]
Stale automation sandbox cleanup. A running browser keeps its clone for the whole
session but holds no file in it open, so liveness comes from the process table:
every clone of a running browser app is left alone, in the preview and in the
prune alike, and an unreadable process table protects everything. The directory
walk is synchronous and offloaded via asyncio.to_thread by callers (doctor
orchestrator, server health endpoints).
"""

from __future__ import annotations

import contextlib
import logging
import plistlib
import shutil
import time
from pathlib import Path
from typing import TypedDict
from xml.parsers.expat import ExpatError

logger = logging.getLogger(__name__)

_CLONE_SUFFIX = ".code_sign_clone"
_APP_EXECUTABLE_MARKER = ".app/Contents/MacOS/"


class SandboxFailure(TypedDict):
    """A sandbox that could not be pruned."""

    path: str
    reason: str


class SandboxCleanupResult(TypedDict):
    """Summary of one sandbox prune pass."""

    candidates_inspected: int
    pruned: int
    reclaimed_bytes: int
    dry_run: bool
    failed: list[SandboxFailure]


def _read_bundle_id(app_path: str) -> str | None:
    """CFBundleIdentifier of the ``.app`` bundle at ``app_path``, ``None`` when it cannot be read."""
    try:
        with open(f"{app_path}/Contents/Info.plist", "rb") as plist_file:
            bundle_id = plistlib.load(plist_file).get("CFBundleIdentifier")
    except (OSError, ValueError, ExpatError):
        return None
    return bundle_id if isinstance(bundle_id, str) and bundle_id else None


def _running_app_bundle_ids() -> frozenset[str] | None:
    """Bundle identifiers of the macOS apps that currently have a running executable.

    Returns ``None`` when the process table cannot be read; callers must then treat
    every sandbox as in use, because "nothing runs" would be a guess.
    """
    try:
        import psutil
    except (ImportError, TypeError):
        logger.warning("psutil not available, cannot tell whether a browser still uses its sandbox")
        return None

    bundle_ids_by_app: dict[str, str | None] = {}
    running: set[str] = set()
    try:
        for proc in psutil.process_iter(["exe"]):
            executable = proc.info.get("exe") or ""
            marker = executable.find(_APP_EXECUTABLE_MARKER)
            if marker < 0:
                continue
            # The first ``.app`` on the path owns the executable; the outermost app of a nested helper is not it.
            app_path = executable[: marker + len(".app")]
            if app_path not in bundle_ids_by_app:
                bundle_ids_by_app[app_path] = _read_bundle_id(app_path)
            bundle_id = bundle_ids_by_app[app_path]
            if bundle_id:
                running.add(bundle_id)
    except Exception as exc:
        logger.warning("Failed to read the process table for sandbox liveness: %s", exc)
        return None
    return frozenset(running)


def _owning_bundle_id(candidate: Path) -> str | None:
    """Bundle id taken from the ``<bundle id>.code_sign_clone`` directory that is or contains ``candidate``."""
    for directory in (candidate, candidate.parent):
        if directory.name.endswith(_CLONE_SUFFIX):
            return directory.name.removesuffix(_CLONE_SUFFIX)
    return None


def cleanup_stale_automation_sandboxes(
    max_age_hours: float = 24.0,
    *,
    dry_run: bool = True,
) -> SandboxCleanupResult:
    """Prune stale automation sandboxes (e.g. macOS code_sign_clone) older than max_age_hours.

    Clones of any Chrome-family browser qualify, not only automation-launched ones; a clone is
    skipped while its browser app is running (dry-run included), so the preview matches the prune.

    Args:
        max_age_hours: Minimum age in hours before a sandbox is eligible for cleanup.
        dry_run: If True, only reports candidates without deleting.

    Returns:
        Summary dict containing inspected, pruned counts, and reclaimed bytes.
    """
    candidates: list[Path] = []
    # 1. macOS AMFI code_sign_clone path probe (*.code_sign_clone covers Chrome, Patchright Chromium, Canary, etc.)
    var_folders = Path("/private/var/folders")
    if var_folders.is_dir():
        try:
            for clone_dir in var_folders.glob("*/*/*/*.code_sign_clone"):
                if clone_dir.is_dir():
                    try:
                        sub_clones = [
                            sub
                            for sub in clone_dir.iterdir()
                            if sub.is_dir() and sub.name.startswith("code_sign_clone.")
                        ]
                    except (OSError, PermissionError):
                        sub_clones = []
                    if sub_clones:
                        candidates.extend(sub_clones)
                    else:
                        candidates.append(clone_dir)
        except (PermissionError, OSError) as exc:
            logger.debug(f"Scan var_folders code_sign_clone skipped: {exc}")

    pruned = 0
    reclaimed_bytes = 0
    now = time.time()
    cutoff_s = max_age_hours * 3600.0
    failed: list[SandboxFailure] = []
    sample_sizes: list[int] = []
    # Only macOS with leaked or live clones pays for the process-table walk.
    running_apps = _running_app_bundle_ids() if candidates else frozenset[str]()

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue

            stat = candidate.stat()
            age_s = now - stat.st_mtime
            if age_s < cutoff_s:
                continue

            if running_apps is None or _owning_bundle_id(candidate) in running_apps:
                logger.debug("Skipping sandbox %s: its browser is still running or liveness is unknown", candidate)
                continue

            # Calculate directory size (in dry_run, sample first 3 if large batch to avoid I/O storms)
            if dry_run and len(sample_sizes) >= 3:
                dir_bytes = int(sum(sample_sizes) / len(sample_sizes))
            else:
                dir_bytes = 0
                for item in candidate.rglob("*"):
                    try:
                        if item.is_file() and not item.is_symlink():
                            dir_bytes += item.stat().st_size
                    except (OSError, PermissionError):
                        pass
                if dry_run:
                    sample_sizes.append(dir_bytes)

            if not dry_run:
                try:
                    shutil.rmtree(candidate)
                except FileNotFoundError:
                    pass
                except Exception as rm_exc:
                    logger.warning("Failed to remove sandbox %s: %s", candidate, rm_exc)

                if candidate.exists():
                    failed.append({"path": str(candidate), "reason": "directory_still_exists_after_rmtree"})
                    continue

                with contextlib.suppress(Exception):
                    parent = candidate.parent
                    if parent.name.endswith(".code_sign_clone") and parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()

                logger.info("Pruned stale automation sandbox: %s", candidate)

            pruned += 1
            reclaimed_bytes += dir_bytes
        except FileNotFoundError:
            # Removed concurrently by another process or OS cleaner
            continue
        except Exception as exc:
            failed.append({"path": str(candidate), "reason": str(exc)})

    return {
        "candidates_inspected": len(candidates),
        "pruned": pruned,
        "reclaimed_bytes": reclaimed_bytes,
        "dry_run": dry_run,
        "failed": failed,
    }
