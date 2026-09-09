"""Filesystem path security and category bucket collision guard.

[INPUT]
- pathlib.Path

[OUTPUT]
- is_path_redirect(path: Path) -> bool: Detect symlinks and Windows NTFS Directory Junctions
- is_category_bucket(path: Path) -> bool | tuple[bool, list[str]]: Detect directories containing child skills
- assert_safe_install_target(target_dir: Path, base_dir: Path | None = None) -> None
- CategoryBucketCollisionError, PathRedirectSecurityError

[POS]
myrm_agent_harness.backends.skills.scanning.path_security
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import overload

logger = logging.getLogger(__name__)


class PathRedirectSecurityError(PermissionError, ValueError):
    """Raised when an operation targets a symbolic link or Windows directory junction."""

    def __init__(self, message: str, target_path: Path | None = None, reason: str | None = None) -> None:
        super().__init__(message)
        self.target_path = target_path
        self.reason = reason or message


class CategoryBucketCollisionError(FileExistsError, ValueError):
    """Raised when an installation target collides with an existing category directory containing sibling skills."""

    def __init__(
        self,
        message: str | Path,
        sub_skills: list[str] | None = None,
    ) -> None:
        if isinstance(message, Path):
            target_path = message
            sub_skills_list = sub_skills or []
            formatted_msg = (
                f"Refusing to overwrite category bucket '{target_path.name}'. "
                f"Directory contains {len(sub_skills_list)} existing skills ({', '.join(sub_skills_list[:5])}) "
                f"and does not have a top-level SKILL.md. Installing here would wipe all sibling skills. "
                f"Please specify a different skill name or install into a dedicated subfolder."
            )
            super().__init__(formatted_msg)
            self.target_path = target_path
            self.sub_skills = sub_skills_list
        else:
            super().__init__(message)
            self.target_path = None
            self.sub_skills = sub_skills or []


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


class CategoryBucketResult(tuple[bool, list[str]]):
    """Result tuple for is_category_bucket supporting both bool casting and tuple unpacking."""

    def __new__(cls, is_bucket: bool, sub_skills: list[str]) -> CategoryBucketResult:
        return super().__new__(cls, (is_bucket, sub_skills))

    def __bool__(self) -> bool:
        return self[0]

    @property
    def is_bucket(self) -> bool:
        return self[0]

    @property
    def sub_skills(self) -> list[str]:
        return self[1]


def is_category_bucket(target_dir: Path | str) -> CategoryBucketResult:
    """Check if target_dir is a category bucket holding other sub-skills.

    A directory is a category bucket if:
    1. It exists and is a directory;
    2. It does NOT have its own SKILL.md or plugin.json at the root level;
    3. It contains at least one immediate or nested subdirectory that contains a SKILL.md or plugin.json.

    Returns CategoryBucketResult (truthy/falsy, and unpackable as `(is_bucket, sub_skills)`).
    """
    p = Path(target_dir)
    if not p.exists() or not p.is_dir() or is_path_redirect(p):
        return CategoryBucketResult(False, [])

    # If it is a valid standalone skill or plugin package, it's not a naked category bucket
    has_root_manifest = (
        (p / "SKILL.md").is_file()
        or (p / "skill.json").is_file()
        or (p / "plugin.json").is_file()
        or (p / "receipt.json").is_file()
    )
    if has_root_manifest:
        return CategoryBucketResult(False, [])

    # Check for child skills inside
    found_sub_skills: list[str] = []
    try:
        for child in p.iterdir():
            if child.is_dir() and not is_path_redirect(child):
                if (
                    (child / "SKILL.md").is_file()
                    or (child / "skill.json").is_file()
                    or (child / "plugin.json").is_file()
                    or (child / "receipt.json").is_file()
                ):
                    found_sub_skills.append(child.name)
    except OSError as exc:
        logger.debug("Error inspecting directory %s for category bucket check: %s", p, exc)

    return CategoryBucketResult(len(found_sub_skills) > 0, found_sub_skills)


def assert_safe_install_target(
    target_dir: Path | str,
    base_dir: Path | str | None = None,
    base_install_root: Path | str | None = None,
) -> None:
    """Validate that target_dir is safe for installation, replacement, or uninstallation.

    Raises:
        PathRedirectSecurityError: If target_dir is a symlink or Windows directory junction,
                                  or escapes base_dir / base_install_root.
        CategoryBucketCollisionError: If target_dir collides with an existing category bucket directory.
    """
    p = Path(target_dir)
    effective_base = base_dir if base_dir is not None else base_install_root

    # 1. Base directory escape check
    if effective_base is not None:
        b = Path(effective_base).resolve()
        try:
            resolved = p.resolve()
            if not str(resolved).startswith(str(b)):
                raise PathRedirectSecurityError(
                    f"Target path '{p}' escapes installation root '{b}'",
                    target_path=p,
                    reason="escapes installation root",
                )
        except OSError as exc:
            raise PathRedirectSecurityError(
                f"Cannot resolve path '{p}': {exc}",
                target_path=p,
                reason=str(exc),
            ) from exc

    # 2. Redirect check
    if is_path_redirect(p):
        raise PathRedirectSecurityError(
            f"Target directory '{p}' is a symlink or directory junction. Refusing destructive file operations.",
            target_path=p,
            reason="Path is a symlink or directory junction",
        )

    # 3. Category bucket collision check
    bucket_res = is_category_bucket(p)
    if bucket_res:
        raise CategoryBucketCollisionError(p, bucket_res.sub_skills)


# Aliases for unified backwards-compatibility across scanning modules
PathRedirectionError = PathRedirectSecurityError
validate_safe_install_target = assert_safe_install_target
check_install_target_safety = assert_safe_install_target

__all__ = [
    "CategoryBucketCollisionError",
    "CategoryBucketResult",
    "PathRedirectSecurityError",
    "PathRedirectionError",
    "assert_safe_install_target",
    "check_install_target_safety",
    "is_category_bucket",
    "is_path_redirect",
    "validate_safe_install_target",
]

