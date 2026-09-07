"""Filesystem path security and category bucket collision guard.

[INPUT]
- pathlib.Path

[OUTPUT]
- is_path_redirect(path: Path) -> bool: Detect symlinks and Windows NTFS Directory Junctions
- is_category_bucket(path: Path) -> bool: Detect directories containing child skills without their own root SKILL.md/plugin.json
- assert_safe_install_target(target_dir: Path, base_dir: Path | None = None) -> None
- CategoryBucketCollisionError, PathRedirectSecurityError

[POS]
myrm_agent_harness.backends.skills.scanning.path_security
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class PathRedirectSecurityError(PermissionError):
    """Raised when an operation targets a symbolic link or Windows directory junction."""


class CategoryBucketCollisionError(FileExistsError):
    """Raised when an installation target collides with an existing category directory containing sibling skills."""


def is_path_redirect(path: Path | str) -> bool:
    """Check if a path is a symlink or Windows directory junction.

    Returns True when path is a symlink or (on Windows) a directory junction.
    Both allow writing/deleting outside the intended base directory.
    """
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return False

    # 1. Standard POSIX / Python symlink check
    if p.is_symlink() or os.path.islink(p):
        return True

    # 2. Windows Directory Junction check (Python 3.12+)
    if hasattr(p, "is_junction") and callable(p.is_junction):
        try:
            if p.is_junction():
                return True
        except (OSError, ValueError):
            pass

    return False


def is_category_bucket(target_dir: Path | str) -> bool:
    """Check if target_dir is a category bucket holding other sub-skills.

    A directory is a category bucket if:
    1. It exists and is a directory;
    2. It does NOT have its own SKILL.md or plugin.json at the root level;
    3. It contains at least one immediate or nested subdirectory that contains a SKILL.md or plugin.json.
    """
    p = Path(target_dir)
    if not p.exists() or not p.is_dir() or is_path_redirect(p):
        return False

    # If it is a valid standalone skill or plugin package, it's not a naked category bucket
    has_root_manifest = (
        (p / "SKILL.md").is_file()
        or (p / "skill.json").is_file()
        or (p / "plugin.json").is_file()
        or (p / "receipt.json").is_file()
    )
    if has_root_manifest:
        return False

    # Check for child skills inside
    try:
        for child in p.iterdir():
            if child.is_dir() and not is_path_redirect(child):
                if (
                    (child / "SKILL.md").is_file()
                    or (child / "skill.json").is_file()
                    or (child / "plugin.json").is_file()
                    or (child / "receipt.json").is_file()
                ):
                    return True
    except OSError as exc:
        logger.debug("Error inspecting directory %s for category bucket check: %s", p, exc)

    return False


def assert_safe_install_target(target_dir: Path | str, base_dir: Path | str | None = None) -> None:
    """Validate that target_dir is safe for installation, replacement, or uninstallation.

    Raises:
        PathRedirectSecurityError: If target_dir is a symlink or Windows directory junction.
        CategoryBucketCollisionError: If target_dir collides with an existing category bucket directory.
        PermissionError: If target_dir escapes base_dir when base_dir is specified.
    """
    p = Path(target_dir)

    # 1. Base directory escape check
    if base_dir is not None:
        b = Path(base_dir).resolve()
        try:
            resolved = p.resolve()
            if not str(resolved).startswith(str(b)):
                raise PathRedirectSecurityError(
                    f"Target path '{p}' escapes base directory '{b}'"
                )
        except OSError as exc:
            raise PathRedirectSecurityError(f"Cannot resolve path '{p}': {exc}") from exc

    # 2. Redirect check
    if is_path_redirect(p):
        raise PathRedirectSecurityError(
            f"Target directory '{p}' is a symlink or directory junction. Refusing destructive file operations."
        )

    # 3. Category bucket collision check
    if is_category_bucket(p):
        raise CategoryBucketCollisionError(
            f"Installation target '{p.name}' collides with an existing category directory containing child skills. "
            f"Refusing to overwrite to prevent silent data loss (GitHub Issue #75983 guard)."
        )
