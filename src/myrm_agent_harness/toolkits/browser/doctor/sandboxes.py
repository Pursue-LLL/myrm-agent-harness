"""Browser Doctor — stale automation sandbox cleanup.

Prunes leftover automation sandboxes (macOS ``*.code_sign_clone`` directories
created by Chrome / Patchright Chromium) once they are old enough, dry-run by
default.

[INPUT]
- lsof (optional, probes whether a sandbox is still held open before deleting it)

[OUTPUT]
- cleanup_stale_automation_sandboxes: dry-run-first sandbox prune returning a SandboxCleanupResult
- SandboxCleanupResult / SandboxFailure: typed shape of the prune summary

[POS]
Stale automation sandbox cleanup. The directory walk is synchronous and offloaded
via asyncio.to_thread by callers (doctor orchestrator, server health endpoints).
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


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


def cleanup_stale_automation_sandboxes(
    max_age_hours: float = 24.0,
    *,
    dry_run: bool = True,
) -> SandboxCleanupResult:
    """Prune stale automation sandboxes (e.g. macOS code_sign_clone) older than max_age_hours.

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

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue

            stat = candidate.stat()
            age_s = now - stat.st_mtime
            if age_s < cutoff_s:
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
                if str(candidate).startswith("/private/var/folders"):
                    try:
                        probe = subprocess.run(
                            ["lsof", "+D", str(candidate)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1.5,
                        )
                        if probe.returncode == 0:
                            logger.debug("Skipping sandbox %s: active process holds files open", candidate)
                            continue
                    except Exception:
                        pass

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
