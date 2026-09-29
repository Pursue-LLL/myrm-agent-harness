"""Path pattern matching — single source of truth for glob-style path protection.

Every path-based protection rule in the framework (sensitive files, protected
instruction files, evidence directories, Goal-scoped write protection) resolves
its patterns through this module. One matcher means one verdict: the
pre-write interceptor and the post-hoc integrity check can no longer disagree
about whether a given file is protected.

Why a dedicated matcher instead of :mod:`fnmatch` or :func:`glob.glob`:
both are wrong for this domain, in ways that fail silently.

``fnmatch``
    Treats ``*`` as "any characters including ``/``", so ``*.py`` matches
    ``a/b/c.py`` (over-broad) while ``**/migrations/**`` requires a literal
    ``**/`` prefix and never matches a bare ``migrations/`` (under-broad).
    It also offers no way to anchor or unanchor a relative pattern against an
    absolute path — comparing ``/repo/app/.env`` against ``.env`` is False.

``glob.glob``
    Never matches a leading dot for a ``*`` wildcard, so ``*.env`` and
    ``**/*.env`` silently return nothing even when ``app/config/.env`` exists.
    An empty result is indistinguishable from "nothing to protect", which is
    how a protection rule ends up reporting success while protecting nothing.

Semantics implemented here:

* ``**`` as a whole segment spans zero or more directories; a trailing ``**``
  spans the remainder of the path.
* ``*`` and ``?`` stay within one path segment.
* A relative pattern matches at any directory depth (a segment-aligned suffix
  of the path), so ``.env`` and ``data/*.csv`` behave as users writing them in
  a protection field expect. Protection is fail-closed: a pattern that matches
  more than the author intended over-protects rather than under-protects.
* An absolute pattern is anchored to the full path and never suffix-matched.
* Leading dots are ordinary characters — ``*.env`` matches ``.env``.

[INPUT]
- (none — pure matching plus a bounded filesystem walk; no agent/toolkit imports)

[OUTPUT]
- compile_path_pattern: compiled regex for one pattern (cached)
- path_matches_pattern: whether one path satisfies one pattern
- first_matching_pattern: first satisfied pattern, for error attribution
- PathPatternMatch: a protected file paired with the rule covering it
- iter_matching_files: bounded walk yielding protected files under a root
- normalise_path_pattern: canonical single-slash form of a pattern

[POS]
Path pattern matching — the single matcher behind every path protection rule.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "MAX_WALK_FILES",
    "PRUNED_DIR_NAMES",
    "PathPatternMatch",
    "compile_path_pattern",
    "first_matching_pattern",
    "iter_matching_files",
    "normalise_path_pattern",
    "path_matches_pattern",
]

logger = logging.getLogger(__name__)

# Directories whose contents are build output or dependency trees.
#
# This list is intentionally NOT shared with the search-candidate pruner in
# ``agent.meta_tools.file_search.fallback_discovery``. The two answer different
# questions with opposite failure costs: skipping a directory there costs search
# recall, while skipping one here leaves protected files uncovered. Merging them
# would let either side weaken the other.
PRUNED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        ".tox",
        ".next",
        ".turbo",
        "dist",
        "build",
        "target",
    }
)

# Upper bound on files inspected by a single sweep. Protects against a pattern
# that degenerates into "match everything" on a very large repository.
MAX_WALK_FILES: int = 20_000

# Compiled patterns are reused across every path checked against a rule set, so
# the cache holds the small fixed tuples the framework ships plus whatever the
# user typed into a protection field.
_PATTERN_CACHE_SIZE: int = 2048

# Regex fragment for ``**/``: zero or more complete directory segments.
_RECURSIVE_DIR = "(?:[^/]+/)*"


def _normalise_separators(value: str) -> str:
    """Collapse Windows separators and duplicate slashes to a POSIX-style path."""
    return value.replace("\\", "/").replace("//", "/")


@lru_cache(maxsize=_PATTERN_CACHE_SIZE)
def compile_path_pattern(pattern: str, *, case_sensitive: bool = True) -> re.Pattern[str]:
    """Compile a glob-style path pattern into an anchored regex.

    The returned regex is intended for :meth:`re.Pattern.fullmatch` against a
    normalised path, so it never matches a partial segment.

    Args:
        pattern: Glob-style pattern to compile.
        case_sensitive: When False, the matcher ignores letter case. Required
            for rules such as protected instruction files, which must be
            recognised regardless of how the filesystem spells them.

    Raises:
        re.error: if the pattern is empty or contains an unterminated
            character class.
    """
    normalised = _normalise_separators(pattern).strip()
    if not normalised:
        raise re.error("empty path pattern", pattern, 0)
    flags = 0 if case_sensitive else re.IGNORECASE

    parts: list[str] = []
    index = 0
    length = len(normalised)
    while index < length:
        char = normalised[index]

        if char == "*":
            starts_segment = index == 0 or normalised[index - 1] == "/"
            is_recursive = normalised.startswith("**", index) and starts_segment
            if is_recursive:
                after = index + 2
                if after == length:
                    # Trailing ``**`` covers the whole remainder, nested
                    # segments included, and the empty remainder as well.
                    parts.append(".*")
                    index = after
                    continue
                if normalised[after] == "/":
                    # ``**/`` spans zero or more complete directories.
                    #
                    # Runs of consecutive ``**/`` collapse into one group.
                    # Stacked copies would nest unbounded quantifiers, so a
                    # pattern such as ``a/**/**/**/x`` degrades to exponential
                    # backtracking and stalls every write-time check.
                    if not parts or parts[-1] != _RECURSIVE_DIR:
                        parts.append(_RECURSIVE_DIR)
                    while after + 1 < length and normalised.startswith("**/", after + 1):
                        after += 3
                    index = after + 1
                    continue
            parts.append("[^/]*")
            index += 1
            continue

        if char == "?":
            parts.append("[^/]")
            index += 1
            continue

        if char == "[":
            closing = normalised.find("]", index + 2)
            if closing == -1:
                raise re.error("unterminated character class", pattern, index)
            body = normalised[index + 1 : closing]
            if body.startswith("!"):
                body = "^" + body[1:]
            parts.append("[" + body.replace("\\", "\\\\") + "]")
            index = closing + 1
            continue

        parts.append(re.escape(char))
        index += 1

    return re.compile("".join(parts), flags)


def normalise_path_pattern(pattern: str) -> str:
    """Return the canonical single-slash form of a pattern, for display."""
    normalised = _normalise_separators(pattern).strip()
    while len(normalised) > 1 and normalised.endswith("/"):
        normalised = normalised[:-1]
    return normalised


def path_matches_pattern(
    path: str | Path, pattern: str, *, case_sensitive: bool = False
) -> bool:
    """Return True when *path* is covered by *pattern*.

    A relative pattern is matched against every segment-aligned suffix of the
    path, so it applies at any depth. An absolute pattern is anchored to the
    whole path. Both forms are compared after separator normalisation, so an
    absolute path is matched by a relative pattern and vice versa.

    Case is ignored by default. Every rule in this module guards a path the
    Agent must not touch, and the filesystems the product ships on (APFS, NTFS)
    treat ``Key.Pem`` and ``key.pem`` as one file; a case-sensitive default
    would let a protected file be reached by respelling it. Pass
    ``case_sensitive=True`` only where a rule is meant to distinguish case.

    Args:
        path: Filesystem path to test. May be relative or absolute.
        pattern: Glob-style pattern. See the module docstring for semantics.
        case_sensitive: When True, letter case must match exactly.

    Returns:
        True when the path satisfies the pattern; False for an empty path.

    Raises:
        re.error: if the pattern is empty or malformed. An unusable rule must
            surface to the caller rather than silently protecting nothing;
            use :func:`first_matching_pattern` to skip bad entries in a set.
    """
    normalised_path = _normalise_separators(str(path))
    if not normalised_path:
        return False

    normalised_pattern = normalise_path_pattern(pattern)
    matcher = compile_path_pattern(normalised_pattern, case_sensitive=case_sensitive)
    if matcher.fullmatch(normalised_path):
        return True

    if normalised_pattern.startswith("/"):
        return False

    # Relative pattern: retry on each segment-aligned suffix so that a pattern
    # written without a leading ``**/`` still applies inside subdirectories.
    separator = normalised_path.find("/")
    while separator != -1:
        if matcher.fullmatch(normalised_path[separator + 1 :]):
            return True
        separator = normalised_path.find("/", separator + 1)
    return False


def first_matching_pattern(
    path: str | Path, patterns: Sequence[str], *, case_sensitive: bool = False
) -> str | None:
    """Return the first pattern in *patterns* that covers *path*, else None.

    The result names the rule that fired, so an error message can point at the
    exact entry the user typed. Case handling matches
    :func:`path_matches_pattern`: ignored unless *case_sensitive* is set.
    """
    for pattern in patterns:
        try:
            if path_matches_pattern(path, pattern, case_sensitive=case_sensitive):
                return pattern
        except re.error:
            continue
    return None


@dataclass(frozen=True, slots=True)
class PathPatternMatch:
    """One protected file, together with the rule that covers it."""

    path: str
    pattern: str


def iter_matching_files(
    root: str | Path,
    patterns: Sequence[str],
    *,
    max_files: int = MAX_WALK_FILES,
) -> Iterator[PathPatternMatch]:
    """Yield every file under *root* that any pattern protects, with its rule.

    The walk is bounded on two axes so a broad pattern cannot stall a Goal:
    dependency and build directories named in :data:`PRUNED_DIR_NAMES` are
    skipped, and at most *max_files* candidates are inspected. Both limits are
    reported through the module logger so a narrow result is never mistaken
    for a complete one.

    Args:
        root: Directory to sweep. Non-directories yield nothing.
        patterns: Patterns to test each file against.
        max_files: Maximum number of files inspected before stopping.

    Yields:
        A :class:`PathPatternMatch` per protected file, in walk order.
    """
    if not patterns:
        return

    root_prefix = str(root)
    if not Path(root_prefix).is_dir():
        return

    inspected = 0
    for dirpath, dirnames, filenames in os.walk(root_prefix, topdown=True):
        dirnames[:] = [name for name in dirnames if name not in PRUNED_DIR_NAMES]
        for filename in filenames:
            inspected += 1
            if inspected > max_files:
                logger.warning(
                    "Path protection sweep stopped after %d files under %s; "
                    "narrow the pattern or exclude build directories.",
                    max_files,
                    root_prefix,
                )
                return
            candidate = os.path.join(dirpath, filename)
            matched = first_matching_pattern(candidate, patterns)
            if matched is not None:
                yield PathPatternMatch(path=candidate, pattern=matched)
