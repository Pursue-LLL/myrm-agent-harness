"""Detect Obsidian-style vault roots for markdown write protection.

[INPUT]
- Local filesystem paths resolved by file_ops strategies

[OUTPUT]
- find_vault_root: nearest ancestor directory containing `.obsidian/`
- is_vault_markdown_path: True when path is `.md` under a vault root

[POS]
Scope detection for vault write guards — no server imports.
"""

from __future__ import annotations

from pathlib import Path

_OBSIDIAN_DIR = ".obsidian"


def find_vault_root(file_path: str) -> Path | None:
    """Return the vault root if ``file_path`` lives under an Obsidian vault."""
    path = Path(file_path).resolve()
    search_roots = [path.parent, *path.parents]
    for candidate in search_roots:
        if (candidate / _OBSIDIAN_DIR).is_dir():
            return candidate
    return None


def is_vault_markdown_path(file_path: str) -> bool:
    """True when the path is a markdown file inside an Obsidian vault."""
    if Path(file_path).suffix.lower() != ".md":
        return False
    return find_vault_root(file_path) is not None
