"""Filesystem path redirection and category bucket collision guard for skill installations.

[POS]
myrm_agent_harness.backends.skills.scanning.path_guard
Thin compatibility facade forwarding to path_security.py (SSOT).
"""

from __future__ import annotations

# Compatibility facade forwarding directly to path_security.py (SSOT)
from myrm_agent_harness.backends.skills.scanning.path_security import *  # noqa: F403



def is_path_redirect(path: Path | str) -> bool:
    """Check if a path is a symlink or (on Windows) a directory junction.

    A redirect allows an attacker or unintended operation in skills/ to redirect
    a later rmtree or write operation outside the sandbox or target directory.
    """
    p = Path(path)
    try:
        # Check standard symlink
        if p.is_symlink() or os.path.islink(p):
            return True

        # Check Windows Directory Junction if available
        if hasattr(p, "is_junction") and p.is_junction():
            return True

        # Resolve path and compare
        # Note: on some platforms resolve() might resolve normal canonical paths without link,
        # but if the resolved path parent deviates unexpectedly, it's suspicious.
        return False
    except (OSError, ValueError):
        return True


def is_category_bucket(target_dir: Path | str) -> bool:
    """Check if target_dir is a category bucket containing sub-skills rather than a standalone skill.

    A directory is deemed a Category Bucket if:
    1. It exists as a directory.
    2. It does NOT directly contain a root `SKILL.md` (case-insensitive).
    3. It contains at least one child sub-directory or sub-skill.
    """
    p = Path(target_dir)
    if not p.exists() or not p.is_dir():
        return False

    # If it directly has a SKILL.md, it is a valid single skill root (can be updated/overwritten)
    if (p / "SKILL.md").exists() or (p / "skill.md").exists():
        return False

    # Inspect children: if it contains other sub-directories, it's a category container
    try:
        for child in p.iterdir():
            if child.is_dir():
                return True
    except OSError:
        pass

    return False


def check_install_target_safety(target_dir: Path | str, skill_name: str = "") -> None:
    """Validate that target_dir is safe to write, replace, or remove without collateral damage.

    Raises:
        PathRedirectSecurityError: If target_dir is a symlink or directory junction.
        CategoryBucketCollisionError: If target_dir is a category bucket containing other sub-skills.
    """
    p = Path(target_dir)
    name = skill_name or p.name

    if is_path_redirect(p):
        logger.error(
            "Security violation: skill target '%s' is a symlink/junction redirect: %s",
            name,
            p,
        )
        raise PathRedirectSecurityError(
            f"Skill target directory '{name}' ({p}) is a symlink or junction redirect. "
            "Refusing to perform filesystem operations to prevent path escape."
        )

    if is_category_bucket(p):
        child_count = 0
        try:
            child_count = sum(1 for c in p.iterdir() if c.is_dir())
        except OSError:
            pass
        logger.warning(
            "Category bucket collision: '%s' contains %d sub-skills without a root SKILL.md",
            name,
            child_count,
        )
        raise CategoryBucketCollisionError(
            f"Target directory '{name}' exists as a category bucket containing {child_count} sub-directories "
            "without a root SKILL.md. Overwriting or deleting it would permanently destroy sibling skills. "
            "Please install the skill into a distinct sub-namespace or rename it."
        )
