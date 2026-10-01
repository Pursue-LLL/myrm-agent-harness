"""Type definitions and constant patterns for destructive action gating.

[INPUT]
- Core models: BlastRadiusInfo, DestructiveAnalysisResult
- System patterns: SYSTEM_DESTRUCTIVE_COMMANDS, GIT_IRREVERSIBLE_SUBCOMMANDS, etc.

[OUTPUT]
- Immutable dataclasses and constants defining the boundary of irreversible actions.

[POS]
Harness core execution security types.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SYSTEM_DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(
    {
        "mkfs",
        "fdisk",
        "sfdisk",
        "parted",
        "wipefs",
        "shred",
        "cryptsetup",
    }
)

GIT_IRREVERSIBLE_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "reset",
        "clean",
        "push",
        "branch",
        "checkout",
    }
)

DANGEROUS_SQL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bDROP\s+(DATABASE|SCHEMA|TABLE)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE(\s+TABLE)?\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\s+\w+\s*(;|$)", re.IGNORECASE),
)

ROOT_OR_PARENT_PATH_PATTERNS: frozenset[str] = frozenset(
    {
        "/",
        "/*",
        ".",
        "./",
        "./*",
        "..",
        "../",
        "~",
        "~/",
        "~/*",
        "$HOME",
        "$HOME/*",
        "${HOME}",
        "${HOME}/*",
    }
)

RAW_DEVICE_PREFIXES: tuple[str, ...] = (
    "/dev/sd",
    "/dev/nvme",
    "/dev/hd",
    "/dev/vd",
    "/dev/loop",
)


@dataclass(frozen=True, slots=True)
class BlastRadiusInfo:
    """Estimated destruction scope and blast radius."""

    impact_scope: str  # "workspace_root", "recursive_dir", "disk_block", "git_history", "database"
    affected_targets: tuple[str, ...]
    is_high_cardinality: bool
    summary_reason: str


@dataclass(frozen=True, slots=True)
class DestructiveAnalysisResult:
    """Structured result of destructive command analysis."""

    is_destructive: bool
    reason: str | None
    blast_radius: BlastRadiusInfo | None
