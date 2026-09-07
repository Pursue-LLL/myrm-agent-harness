"""Category bucket collision and path redirection shield for skill installations.

[INPUT]
- pathlib.Path targets for installation/uninstallation

[OUTPUT]
- CategoryBucketCollisionError, PathRedirectionError, is_category_bucket, is_path_redirect, validate_safe_install_target

[POS]
myrm_agent_harness.backends.skills.scanning.category_guard
Guards against silent data loss when skill names collide with existing category directories (GitHub Issue #75983)
and blocks Symlink/Junction traversal attacks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class CategoryBucketCollisionError(ValueError):
    """Raised when an install/uninstall target collides with an existing category directory containing sub-skills."""

    def __init__(self, target_path: Path, sub_skills: list[str]) -> None:
        self.target_path = target_path
        self.sub_skills = sub_skills
        msg = (
            f"Refusing to overwrite category bucket '{target_path.name}'. "
            f"Directory contains {len(sub_skills)} existing skills ({', '.join(sub_skills[:5])}) "
            f"and does not have a top-level SKILL.md. Installing here would wipe all sibling skills. "
            f"Please specify a different skill name or install into a dedicated subfolder."
        )
        super().__init__(msg)


class PathRedirectionError(ValueError):
    """Raised when an install/uninstall target or its component is a symlink or Windows directory junction."""

    def __init__(self, target_path: Path, reason: str) -> None:
        self.target_path = target_path
        self.reason = reason
        msg = f"Path redirection blocked for '{target_path}': {reason}"
        super().__init__(msg)


def is_path_redirect(path: Path) -> bool:
    """Check if a path is a symlink or (on Windows) a directory junction."""
    if not path.exists() and not path.is_symlink():
        return False

    try:
        if path.is_symlink():
            return True

        # Check Windows directory junctions (reparse points)
        if hasattr(path, "is_junction") and callable(getattr(path, "is_junction")):
            if path.is_junction():
                return True

        # Fallback check for Windows junctions via os.stat
        if os.name == "nt":
            try:
                stat_res = os.lstat(str(path))
                # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
                if getattr(stat_res, "st_file_attributes", 0) & 0x400:
                    return True
            except Exception:
                pass
    except Exception as exc:
        logger.debug("Error checking path redirection for %s: %s", path, exc)

    return False


def is_category_bucket(target_dir: Path) -> tuple[bool, list[str]]:
    """Determine whether target_dir is a category bucket containing sub-skills rather than a single skill.

    A directory is a category bucket if:
    1. It exists and is a directory.
    2. It does NOT contain a top-level SKILL.md.
    3. It contains one or more immediate subdirectories that contain their own SKILL.md.
    """
    if not target_dir.exists() or not target_dir.is_dir():
        return False, []

    # If it is a symlink or junction, do not treat as a standard bucket
    if is_path_redirect(target_dir):
        return False, []

    # If it contains a top-level SKILL.md, it is a single standalone skill
    skill_md = target_dir / "SKILL.md"
    if skill_md.is_file():
        return False, []

    # Check for subdirectories containing SKILL.md
    sub_skills: list[str] = []
    try:
        for child in target_dir.iterdir():
            if child.is_dir() and not is_path_redirect(child):
                child_skill_md = child / "SKILL.md"
                if child_skill_md.is_file():
                    sub_skills.append(child.name)
    except Exception as exc:
        logger.warning("Failed to inspect subdirectories of %s: %s", target_dir, exc)

    if sub_skills:
        return True, sub_skills

    return False, []


def validate_safe_install_target(target_dir: Path, base_install_root: Path | None = None) -> None:
    """Validate that target_dir is safe to write, replace, or uninstall.

    Raises:
        PathRedirectionError: If target or any parent component is a symlink or junction.
        CategoryBucketCollisionError: If target is an existing category directory containing sub-skills.
    """
    # 1. Redirection check on target itself
    if is_path_redirect(target_dir):
        raise PathRedirectionError(
            target_dir, "Target path is a symlink or Windows directory junction."
        )

    # 2. Escape check relative to base root
    if base_install_root:
        base_resolved = base_install_root.resolve()
        target_resolved = target_dir.resolve()
        if not str(target_resolved).startswith(str(base_resolved)):
            raise PathRedirectionError(
                target_dir, f"Target path escapes installation root: {base_resolved}"
            )

    # 3. Category bucket collision check
    is_bucket, sub_skills = is_category_bucket(target_dir)
    if is_bucket:
        raise CategoryBucketCollisionError(target_dir, sub_skills)
