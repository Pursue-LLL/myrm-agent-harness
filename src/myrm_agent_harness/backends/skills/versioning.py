"""Skill version comparison utilities.

Compares semantic versions (major.minor.patch) to detect available upgrades.
Falls back to lexicographic comparison for non-semver strings.

[INPUT]
- (none)

[OUTPUT]
- VersionDelta: Result of comparing a local version against a remote vers...
- compare_versions: Compare two version strings and determine if an update is...

[POS]
Skill version comparison utilities.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass(frozen=True, slots=True)
class VersionDelta:
    """Result of comparing a local version against a remote version."""

    current: str
    remote: str
    has_update: bool


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    """Parse a semver-like string into (major, minor, patch).

    Returns None if the string is not a valid semver.
    """
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2) or 0)
    patch = int(m.group(3) or 0)
    return (major, minor, patch)


def compare_versions(current: str, remote: str) -> VersionDelta:
    """Compare two version strings and determine if an update is available.

    Tries semver comparison first; falls back to lexicographic comparison.
    Empty or identical versions always yield has_update=False.
    """
    if not current or not remote or current == remote:
        return VersionDelta(current=current, remote=remote, has_update=False)

    cur_parsed = _parse_semver(current)
    rem_parsed = _parse_semver(remote)

    if cur_parsed is not None and rem_parsed is not None:
        has_update = rem_parsed > cur_parsed
    else:
        has_update = remote > current

    return VersionDelta(current=current, remote=remote, has_update=has_update)
