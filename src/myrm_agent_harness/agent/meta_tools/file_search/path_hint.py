"""Similar-path hints when a requested file or directory is not found."""

from __future__ import annotations

import os
from difflib import get_close_matches
from pathlib import Path


def suggest_similar_paths(
    target_path: str,
    *,
    max_suggestions: int = 3,
) -> list[str]:
    """Return up to ``max_suggestions`` paths similar to ``target_path``.

    Looks in the parent directory for basename matches; if the parent does not
    exist, walks up one level when possible.
    """
    norm = os.path.normpath(target_path)
    parent = os.path.dirname(norm) or "."
    basename = os.path.basename(norm)
    if not basename:
        return []

    candidates: list[str] = []
    search_dirs: list[str] = [parent]
    grandparent = os.path.dirname(parent)
    if grandparent and grandparent != parent:
        search_dirs.append(grandparent)

    seen: set[str] = set()
    for directory in search_dirs:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            continue
        try:
            names = [entry.name for entry in dir_path.iterdir()]
        except OSError:
            continue
        for match in get_close_matches(basename, names, n=max_suggestions, cutoff=0.5):
            candidate = os.path.join(directory, match)
            if candidate in seen:
                continue
            seen.add(candidate)
            candidates.append(candidate)
            if len(candidates) >= max_suggestions:
                return candidates

    return candidates


def format_path_not_found_hint(target_path: str, suggestions: list[str]) -> str:
    if not suggestions:
        return f"The path '{target_path}' does not exist. Please check the path and try again."
    joined = ", ".join(f"'{s}'" for s in suggestions)
    return (
        f"The path '{target_path}' does not exist. "
        f"Did you mean: {joined}?"
    )
