"""Canonical local skill ID derived from filesystem path.

[INPUT]
- pathlib.Path (filesystem skill install directory)

[OUTPUT]
- local_skill_id_from_path: Compute stable local::{16hex} ID from a directory path
- resolve_local_install_dir: Resolve canonical ID back to install directory under a root

[POS]
Local skill ID SSOT for harness install/uninstall and server catalog alignment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def local_skill_id_from_path(path: Path) -> str:
    """Compute stable local skill ID from an on-disk skill directory."""
    path_str = str(path.resolve())
    path_hash = hashlib.sha256(path_str.encode("utf-8")).hexdigest()[:16]
    return f"local::{path_hash}"


def resolve_local_install_dir(skill_id: str, install_root: Path) -> Path | None:
    """Resolve a canonical local skill ID to its install directory."""
    if not skill_id.startswith("local::"):
        return None

    suffix = skill_id.removeprefix("local::")
    if len(suffix) != 16:
        return None

    if not install_root.is_dir():
        return None

    for item in install_root.iterdir():
        if not item.is_dir():
            continue
        if local_skill_id_from_path(item) == skill_id:
            return item
    return None
