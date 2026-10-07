"""Glob boundary enforcer for safe, cycle-free, and depth-governed filesystem traversal.

Prevents directory traversal escapes, recursive deadlocks, symlink loops, and
context blowup in sandbox and virtual filesystems while delineating directory hits
with explicit trailing slash markers aligned with the VikingFS protocol.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .trailing_slash_delineator import TrailingSlashDelineator
from .vfs_boundary_types import (
    GlobBoundaryViolationError,
    GlobSafetyAudit,
    GlobSafetyConfig,
    VFSGlobHit,
    VFSPathKind,
)


class GlobBoundaryEnforcer:
    """Enforces safety gates, depth thresholds, and explicit directory trailing slashes on glob ops."""

    def __init__(
        self,
        delineator: TrailingSlashDelineator | None = None,
    ) -> None:
        self._delineator = delineator or TrailingSlashDelineator()
        self._last_audit: GlobSafetyAudit | None = None

    @property
    def last_audit(self) -> GlobSafetyAudit | None:
        """Returns diagnostic audit from the most recent glob execution."""
        return self._last_audit

    def safe_glob(
        self,
        root_dir: str | Path,
        pattern: str,
        config: GlobSafetyConfig | None = None,
    ) -> tuple[VFSGlobHit, ...]:
        """Executes a boundary-guarded glob traversal under strict safety limits."""
        cfg = config or GlobSafetyConfig()
        root_path = Path(root_dir).resolve()

        if not root_path.exists() or not root_path.is_dir():
            self._last_audit = GlobSafetyAudit(
                root_directory=str(root_path),
                pattern=pattern,
                total_scanned=0,
                matched_count=0,
                truncated_by_depth=False,
                truncated_by_limit=False,
                symlink_cycles_detected=0,
                traversal_violations=0,
            )
            return ()

        # Assert no directory traversal pattern escape
        self._assert_safe_pattern(pattern, root_path)

        visited_inodes: set[tuple[int, int]] = set()
        hits: list[VFSGlobHit] = []
        total_scanned = 0
        truncated_by_depth = False
        truncated_by_limit = False
        symlink_cycles = 0

        # Stack for DFS traversal: (current_dir, current_depth)
        stack: list[tuple[Path, int]] = [(root_path, 0)]

        # Normalized pattern for matching relative paths
        norm_pattern = self._delineator.normalize_separators(pattern.strip())
        match_only_dirs = norm_pattern.endswith("/")

        while stack:
            curr_dir, curr_depth = stack.pop()

            if curr_depth > cfg.max_depth:
                truncated_by_depth = True
                continue

            try:
                entries = sorted(os.scandir(curr_dir), key=lambda e: e.name)
            except (PermissionError, OSError):
                continue

            subdirs_to_visit: list[Path] = []

            for entry in entries:
                total_scanned += 1
                entry_depth = curr_depth + 1

                if entry_depth > cfg.max_depth:
                    truncated_by_depth = True
                    continue

                if cfg.ignore_hidden and entry.name.startswith("."):
                    continue

                entry_path = Path(entry.path)
                try:
                    rel_path_str = self._delineator.normalize_separators(
                        str(entry_path.relative_to(root_path))
                    )
                except ValueError:
                    continue

                is_symlink = entry.is_symlink()
                if is_symlink and not cfg.follow_symlinks:
                    kind = VFSPathKind.SYMLINK
                    is_dir = False
                elif is_symlink and cfg.follow_symlinks:
                    try:
                        stat_res = entry_path.stat()
                        inode_key = (stat_res.st_dev, stat_res.st_ino)
                        if inode_key in visited_inodes:
                            symlink_cycles += 1
                            continue
                        visited_inodes.add(inode_key)
                        is_dir = entry_path.is_dir()
                        kind = VFSPathKind.DIRECTORY if is_dir else VFSPathKind.FILE
                    except (OSError, RuntimeError):
                        continue
                else:
                    is_dir = entry.is_dir()
                    kind = VFSPathKind.DIRECTORY if is_dir else VFSPathKind.FILE

                # Check pattern match against relative path or basename
                is_match = self._matches_pattern(
                    rel_path_str=rel_path_str,
                    raw_name=entry.name,
                    pattern=norm_pattern,
                    is_dir=is_dir,
                )

                if is_match:
                    if match_only_dirs and not is_dir:
                        pass
                    else:
                        delineated_path = (
                            self._delineator.delineate_path(rel_path_str, is_dir=is_dir)
                            if cfg.require_trailing_slash_for_dirs
                            else rel_path_str
                        )
                        hits.append(
                            VFSGlobHit(
                                path=delineated_path,
                                raw_name=entry.name,
                                kind=kind,
                                depth=curr_depth + 1,
                                is_directory=is_dir,
                                has_trailing_slash=delineated_path.endswith("/"),
                            )
                        )

                        if len(hits) >= cfg.max_results:
                            truncated_by_limit = True
                            break

                if is_dir:
                    subdirs_to_visit.append(entry_path)

            if truncated_by_limit:
                break

            # Add subdirectories to traversal stack (in reverse order for deterministic sorting)
            for subdir in reversed(subdirs_to_visit):
                stack.append((subdir, curr_depth + 1))

        # Deterministic sorting: directories first, then alphabetical by path
        hits.sort(key=lambda h: (not h.is_directory, h.path))

        self._last_audit = GlobSafetyAudit(
            root_directory=str(root_path),
            pattern=pattern,
            total_scanned=total_scanned,
            matched_count=len(hits),
            truncated_by_depth=truncated_by_depth,
            truncated_by_limit=truncated_by_limit,
            symlink_cycles_detected=symlink_cycles,
            traversal_violations=0,
        )

        return tuple(hits)

    def _assert_safe_pattern(self, pattern: str, root_path: Path) -> None:
        """Validates that glob pattern does not attempt traversal beyond root."""
        cleaned = self._delineator.normalize_separators(pattern)
        parts = cleaned.split("/")

        # Check for upward traversal beyond root
        depth = 0
        for part in parts:
            if part == "..":
                depth -= 1
                if depth < 0:
                    self._last_audit = GlobSafetyAudit(
                        root_directory=str(root_path),
                        pattern=pattern,
                        total_scanned=0,
                        matched_count=0,
                        truncated_by_depth=False,
                        truncated_by_limit=False,
                        symlink_cycles_detected=0,
                        traversal_violations=1,
                    )
                    raise GlobBoundaryViolationError(
                        f"Glob pattern '{pattern}' breaches root directory boundary via '..'"
                    )
            elif part and part != ".":
                depth += 1

    def _matches_pattern(
        self,
        rel_path_str: str,
        raw_name: str,
        pattern: str,
        is_dir: bool,
    ) -> bool:
        """Evaluates whether path or entry matches glob pattern, respecting directory tokens."""
        clean_pat = pattern.rstrip("/")

        # Direct match on basename
        if fnmatch.fnmatch(raw_name, clean_pat):
            return True

        # Match on relative path
        if fnmatch.fnmatch(rel_path_str, clean_pat):
            return True

        # Handle wildcard recursive '**' patterns
        if "**" in clean_pat:
            if fnmatch.fnmatch(rel_path_str, clean_pat):
                return True
            parts = clean_pat.split("**/")
            if len(parts) == 2 and fnmatch.fnmatch(rel_path_str, f"*{parts[1]}"):
                return True

        return False
