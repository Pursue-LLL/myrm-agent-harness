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
from enum import StrEnum

_SEMVER_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?")


class VersionBumpType(StrEnum):
    """Classification of semantic version change between two versions."""

    INITIAL = "initial"
    SAME = "same"
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"
    DOWNGRADE = "downgrade"


@dataclass(frozen=True, slots=True)
class VersionGuardResult:
    """Result of evaluating the skill version upgrade guard."""

    allowed: bool
    bump_type: VersionBumpType
    current_version: str
    incoming_version: str
    reason: str = ""


class SkillDowngradeBlockedError(ValueError):
    """Raised when an incoming skill package version is lower than the installed version."""

    def __init__(
        self,
        current_version: str,
        incoming_version: str,
        bump_type: VersionBumpType = VersionBumpType.DOWNGRADE,
    ) -> None:
        self.current_version = current_version
        self.incoming_version = incoming_version
        self.bump_type = bump_type
        super().__init__(
            f"Skill downgrade blocked: incoming version '{incoming_version}' is lower than installed "
            f"version '{current_version}'. Pass allow_downgrade=True to force installation."
        )


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


def classify_version_bump(current: str | None, incoming: str | None) -> VersionBumpType:
    """Classify the semantic version transition from current to incoming.

    Returns:
        - INITIAL: when there is no current version (new installation).
        - SAME: when both versions are identical or equivalent.
        - PATCH: incoming is a patch-level bump (X.Y.Z+1).
        - MINOR: incoming is a minor-level bump (X.Y+1.0).
        - MAJOR: incoming is a major-level bump (X+1.0.0).
        - DOWNGRADE: incoming is lower than current.
    """
    cur = (current or "").strip()
    inc = (incoming or "").strip()

    if not cur:
        return VersionBumpType.INITIAL
    if not inc or cur == inc:
        return VersionBumpType.SAME

    cur_parsed = _parse_semver(cur)
    inc_parsed = _parse_semver(inc)

    if cur_parsed is not None and inc_parsed is not None:
        cur_maj, cur_min, cur_pat = cur_parsed
        inc_maj, inc_min, inc_pat = inc_parsed

        if inc_parsed < cur_parsed:
            return VersionBumpType.DOWNGRADE
        if inc_maj > cur_maj:
            return VersionBumpType.MAJOR
        if inc_min > cur_min:
            return VersionBumpType.MINOR
        if inc_pat > cur_pat:
            return VersionBumpType.PATCH
        return VersionBumpType.SAME

    if inc < cur:
        return VersionBumpType.DOWNGRADE
    return VersionBumpType.MINOR if inc > cur else VersionBumpType.SAME


def validate_version_guard(
    current: str | None,
    incoming: str | None,
    *,
    allow_downgrade: bool = False,
) -> VersionGuardResult:
    """Validate skill version transition before installation promotion.

    Raises:
        SkillDowngradeBlockedError: If incoming is lower than current and allow_downgrade=False.

    Returns:
        VersionGuardResult with detailed bump classification and safety decision.
    """
    bump = classify_version_bump(current, incoming)
    cur_str = (current or "").strip()
    inc_str = (incoming or "").strip()

    if bump == VersionBumpType.DOWNGRADE and not allow_downgrade:
        raise SkillDowngradeBlockedError(
            current_version=cur_str,
            incoming_version=inc_str,
            bump_type=bump,
        )

    reason = ""
    if bump == VersionBumpType.MAJOR:
        reason = f"Major version upgrade detected ({cur_str} -> {inc_str})"
    elif bump == VersionBumpType.DOWNGRADE:
        reason = f"Downgrade explicitly allowed ({cur_str} -> {inc_str})"

    return VersionGuardResult(
        allowed=True,
        bump_type=bump,
        current_version=cur_str,
        incoming_version=inc_str,
        reason=reason,
    )

