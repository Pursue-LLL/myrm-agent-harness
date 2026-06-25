"""
[INPUT]
myrm_agent_harness.core.security.path_security::safe_join_path (POS: Workspace path boundary guard)
myrm_agent_harness.toolkits.workspace.indexer::WorkspacePathIndexer (POS: Local workspace file enumerator)

[OUTPUT]
rank_basename: ranks a basename against a query.
suggest_workspace_paths: returns root-relative file or directory suggestions.

[POS]
Workspace path suggestion ranker. Applies safe path-mode lookup and GUI-friendly fuzzy ranking over local files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from myrm_agent_harness.core.security.path_security import (
    is_dangerous_path,
    is_sensitive_file,
    safe_join_path,
)
from myrm_agent_harness.toolkits.workspace.indexer import WorkspacePathIndexer
from myrm_agent_harness.toolkits.workspace.models import (
    WorkspacePathSuggestion,
    WorkspaceScoreTier,
    WorkspaceSuggestionKind,
    WorkspaceSuggestionOptions,
)

_WORD_SPLIT_RE = re.compile(r"[-_.\s]+")


def rank_basename(name: str, query: str) -> tuple[WorkspaceScoreTier, int, list[tuple[int, int]]] | None:
    """Rank ``name`` against ``query``. Higher score is better."""

    if not query:
        return ("substring", 40, [])

    lowered_name = name.lower()
    lowered_query = query.lower()

    if lowered_name == lowered_query:
        return ("exact", 1000, [(0, len(name))])

    if lowered_name.startswith(lowered_query):
        return ("prefix", 900 + len(query), [(0, len(query))])

    word_match = _word_boundary_match(name, lowered_query)
    if word_match is not None:
        return ("word", 800 + len(query), [word_match])

    index = lowered_name.find(lowered_query)
    if index >= 0:
        return ("substring", 700 + len(query), [(index, index + len(query))])

    ranges = _subsequence_ranges(lowered_name, lowered_query)
    if ranges:
        span = ranges[-1][1] - ranges[0][0]
        compactness = max(0, 100 - span)
        return ("subsequence", 500 + compactness, ranges)

    return None


def suggest_workspace_paths(
    root: str | Path,
    query: str,
    options: WorkspaceSuggestionOptions | None = None,
) -> list[WorkspacePathSuggestion]:
    """Suggest files/directories under ``root`` for a GUI mention picker."""

    opts = options or WorkspaceSuggestionOptions()
    root_path = Path(root).expanduser().resolve()
    normalized_query = query.strip()

    if _is_path_mode(normalized_query) or opts.kind == "directory":
        return _suggest_path_mode(root_path, normalized_query, opts)

    ranked: list[tuple[int, str, WorkspacePathSuggestion]] = []
    for rel_path in WorkspacePathIndexer.list_files(root_path):
        basename = os.path.basename(rel_path)
        if not _visible_for_query(basename, normalized_query, opts.include_hidden):
            continue

        full_path = root_path / rel_path
        if _blocked_path(full_path):
            continue

        rank = rank_basename(basename, normalized_query)
        if rank is None:
            continue
        tier, score, ranges = rank
        ranked.append(
            (
                score,
                rel_path,
                WorkspacePathSuggestion(
                    kind="file",
                    relative_path=rel_path,
                    basename=basename,
                    directory=os.path.dirname(rel_path),
                    score_tier=tier,
                    score=score,
                    match_ranges=ranges,
                    size=_file_size(full_path),
                ),
            )
        )

    ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [item[2] for item in ranked[: opts.limit]]


def _suggest_path_mode(
    root: Path,
    query: str,
    options: WorkspaceSuggestionOptions,
) -> list[WorkspacePathSuggestion]:
    path_query = query.lstrip("/")
    if path_query in {"", ".", "./"}:
        parent_part = ""
        needle = ""
    else:
        parent_part, needle = path_query.rsplit("/", 1) if "/" in path_query else ("", path_query)

    try:
        parent = safe_join_path(root, parent_part or ".")
    except ValueError:
        return []
    if not parent.exists() or not parent.is_dir():
        return []

    suggestions: list[WorkspacePathSuggestion] = []
    for child in parent.iterdir():
        if _blocked_path(child):
            continue
        kind: WorkspaceSuggestionKind = "directory" if child.is_dir() else "file"
        if options.kind != "any" and kind != options.kind:
            continue
        if not _visible_for_query(child.name, needle, options.include_hidden):
            continue
        rank = rank_basename(child.name, needle)
        if rank is None:
            continue
        tier, score, ranges = rank
        try:
            rel = child.relative_to(root).as_posix()
        except ValueError:
            continue
        suggestions.append(
            WorkspacePathSuggestion(
                kind=kind,
                relative_path=rel,
                basename=child.name,
                directory=os.path.dirname(rel),
                score_tier="path" if not needle else tier,
                score=score,
                match_ranges=ranges,
                size=_file_size(child) if kind == "file" else None,
            )
        )

    suggestions.sort(key=lambda item: (item.kind != "directory", -item.score, item.basename.lower()))
    return suggestions[: options.limit]


def _word_boundary_match(name: str, lowered_query: str) -> tuple[int, int] | None:
    parts: list[tuple[int, str]] = []
    start = 0
    for token in _WORD_SPLIT_RE.split(name):
        if token:
            token_start = name.find(token, start)
            parts.append((token_start, token))
            start = token_start + len(token)

    for index, char in enumerate(name):
        if index > 0 and char.isupper() and not name[index - 1].isupper():
            parts.append((index, name[index:]))

    for index, token in parts:
        if token.lower().startswith(lowered_query):
            return (index, index + len(lowered_query))
    return None


def _subsequence_ranges(lowered_name: str, lowered_query: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    name_index = 0
    for query_char in lowered_query:
        found_at = lowered_name.find(query_char, name_index)
        if found_at < 0:
            return []
        ranges.append((found_at, found_at + 1))
        name_index = found_at + 1
    return ranges


def _is_path_mode(query: str) -> bool:
    return "/" in query or query.startswith(("./", "../", "~"))


def _visible_for_query(name: str, query: str, include_hidden: bool) -> bool:
    if include_hidden:
        return True
    return not name.startswith(".") or query.startswith(".")


def _blocked_path(path: Path) -> bool:
    path_str = str(path)
    return is_dangerous_path(path_str) or is_sensitive_file(path_str)


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
