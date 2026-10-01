"""Destructive command matching rules, flag normalization, and blast radius estimation.

Provides fine-grained AST and lexical analysis to identify irreversible destructive
actions (e.g. recursive force deletes, git tree wipes, disk formatting, drop databases)
and enforce Hard Stop Line protection.

[INPUT]
- base_cmd: Command executable name.
- args: Command argument sequence.
- redirections: Command I/O redirections.
- workspace_path: Optional workspace base path.

[OUTPUT]
- is_destructive_action: True if command constitutes an irreversible destructive operation.
- evaluate_blast_radius: Structured estimate of impacted files, scopes, and risk factors.
- DestructiveAnalysisResult: Detailed analysis output including reason and blast radius.

[POS]
Harness core execution security: fine-grained destructive command gating.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Destruction Classifications and Constants
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Flag Normalization Helpers
# ---------------------------------------------------------------------------


def normalize_flags(args: Sequence[str]) -> set[str]:
    """Normalize short and long flags into a flattened option set."""
    flags: set[str] = set()
    for arg in args:
        if arg == "--":
            break
        if arg.startswith("--"):
            flags.add(arg.lower())
        elif arg.startswith("-") and len(arg) > 1:
            for char in arg[1:]:
                flags.add(f"-{char}")
    return flags


def extract_non_flag_operands(args: Sequence[str]) -> list[str]:
    """Extract non-option target operands from arguments."""
    operands: list[str] = []
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            operands.extend(args[i + 1 :])
            break
        if arg.startswith("-"):
            # Check for flag options that take values if needed
            continue
        operands.append(arg)
    return operands


# ---------------------------------------------------------------------------
# Core Destructive Matchers
# ---------------------------------------------------------------------------


def check_rm_destruction(args: Sequence[str]) -> DestructiveAnalysisResult | None:
    """Check if 'rm' command executes an irreversible recursive or wildcard deletion."""
    flags = normalize_flags(args)
    has_recursive = bool(flags.intersection({"-r", "-R", "--recursive"}))
    has_force = bool(flags.intersection({"-f", "--force"}))
    operands = extract_non_flag_operands(args)

    if not operands:
        return None

    # Check for root, parent, home, or wildcard targets
    is_root_or_broad = False
    for op in operands:
        normalized = op.strip().rstrip("/")
        if normalized in ROOT_OR_PARENT_PATH_PATTERNS or normalized.endswith("/*"):
            is_root_or_broad = True
            break
        # Check for unquoted environment variable deletions (e.g. rm -rf $DIR/*)
        if "$" in op:
            is_root_or_broad = True
            break

    if has_recursive:
        scope = "workspace_root" if is_root_or_broad else "recursive_dir"
        summary = (
            "Irreversible recursive directory deletion"
            if not is_root_or_broad
            else "High-risk root or broad wildcard recursive deletion"
        )
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="recursive_file_deletion",
            blast_radius=BlastRadiusInfo(
                impact_scope=scope,
                affected_targets=tuple(operands),
                is_high_cardinality=True,
                summary_reason=summary,
            ),
        )

    if has_force and is_root_or_broad:
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="forced_broad_file_deletion",
            blast_radius=BlastRadiusInfo(
                impact_scope="workspace_root",
                affected_targets=tuple(operands),
                is_high_cardinality=True,
                summary_reason="Forced file deletion on broad target or environment variable",
            ),
        )

    return None


def check_git_destruction(args: Sequence[str]) -> DestructiveAnalysisResult | None:
    """Check if 'git' command performs irreversible history reset, branch drop, or clean."""
    if not args:
        return None

    # Find the git subcommand, ignoring global flags
    subcmd: str | None = None
    subcmd_idx = -1
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        subcmd = arg
        subcmd_idx = i
        break

    if not subcmd or subcmd not in GIT_IRREVERSIBLE_SUBCOMMANDS:
        return None

    sub_args = args[subcmd_idx + 1 :]
    flags = normalize_flags(sub_args)

    # 1. git reset --hard
    if subcmd == "reset" and "--hard" in flags:
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="git_hard_reset",
            blast_radius=BlastRadiusInfo(
                impact_scope="git_history",
                affected_targets=("working_tree", "index"),
                is_high_cardinality=True,
                summary_reason="Hard reset permanently discards all uncommitted and unstaged changes",
            ),
        )

    # 2. git clean -f / -fd / -fdx
    if subcmd == "clean" and bool(flags.intersection({"-f", "--force"})):
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="git_untracked_clean",
            blast_radius=BlastRadiusInfo(
                impact_scope="git_history",
                affected_targets=("untracked_files",),
                is_high_cardinality=True,
                summary_reason="Force clean permanently removes untracked working tree files and directories",
            ),
        )

    # 3. git push --force / -f
    if subcmd == "push" and bool(flags.intersection({"-f", "--force", "--force-with-lease"})):
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="git_force_push",
            blast_radius=BlastRadiusInfo(
                impact_scope="git_history",
                affected_targets=("remote_history",),
                is_high_cardinality=True,
                summary_reason="Force push can irrevocably overwrite remote branch history",
            ),
        )

    # 4. git branch -D
    if subcmd == "branch" and bool(flags.intersection({"-D"})):
        operands = extract_non_flag_operands(sub_args)
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="git_force_branch_delete",
            blast_radius=BlastRadiusInfo(
                impact_scope="git_history",
                affected_targets=tuple(operands) if operands else ("branch",),
                is_high_cardinality=False,
                summary_reason="Force deleting branch discards unmerged commits",
            ),
        )

    # 5. git checkout -f
    if subcmd == "checkout" and bool(flags.intersection({"-f", "--force"})):
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason="git_force_checkout",
            blast_radius=BlastRadiusInfo(
                impact_scope="git_history",
                affected_targets=("working_tree",),
                is_high_cardinality=True,
                summary_reason="Forced checkout overwrites modified local working tree files",
            ),
        )

    return None


def check_dd_destruction(args: Sequence[str]) -> DestructiveAnalysisResult | None:
    """Check if 'dd' command overwrites raw block devices or files."""
    for arg in args:
        if arg.startswith("of="):
            target = arg[3:].strip()
            if target.startswith(("/dev/sd", "/dev/nvme", "/dev/hd", "/dev/vd", "/dev/loop")):
                return DestructiveAnalysisResult(
                    is_destructive=True,
                    reason="raw_device_overwrite",
                    blast_radius=BlastRadiusInfo(
                        impact_scope="disk_block",
                        affected_targets=(target,),
                        is_high_cardinality=True,
                        summary_reason=f"Raw disk write directly to block device {target}",
                    ),
                )
    return None


def check_redirection_destruction(
    redirections: Sequence[tuple[str, str]],
) -> DestructiveAnalysisResult | None:
    """Check if redirections overwrite raw disk devices."""
    for op, target in redirections:
        if op in {">", ">>", "&>", ">&"}:
            t = target.strip()
            if t.startswith(("/dev/sd", "/dev/nvme", "/dev/hd", "/dev/vd", "/dev/loop")):
                return DestructiveAnalysisResult(
                    is_destructive=True,
                    reason="raw_device_redirection_overwrite",
                    blast_radius=BlastRadiusInfo(
                        impact_scope="disk_block",
                        affected_targets=(t,),
                        is_high_cardinality=True,
                        summary_reason=f"I/O redirection overwrite directly targeting {t}",
                    ),
                )
    return None


# ---------------------------------------------------------------------------
# Public Facade
# ---------------------------------------------------------------------------


def analyze_destructive_action(
    base_cmd: str,
    args: Sequence[str],
    redirections: Sequence[tuple[str, str]] = (),
) -> DestructiveAnalysisResult:
    """Perform comprehensive multi-vector check for irreversible destructive operations."""
    if not base_cmd:
        return DestructiveAnalysisResult(is_destructive=False, reason=None, blast_radius=None)

    # 1. System-level destruction tools (including mkfs.ext4, mkfs.xfs, etc.)
    if base_cmd in SYSTEM_DESTRUCTIVE_COMMANDS or base_cmd.startswith("mkfs."):
        return DestructiveAnalysisResult(
            is_destructive=True,
            reason=f"system_destructive_utility_{base_cmd}",
            blast_radius=BlastRadiusInfo(
                impact_scope="disk_block",
                affected_targets=tuple(extract_non_flag_operands(args)),
                is_high_cardinality=True,
                summary_reason=f"System utility '{base_cmd}' causes irreversible partition or filesystem destruction",
            ),
        )

    # 2. Recursive or broad rm
    if base_cmd == "rm":
        rm_res = check_rm_destruction(args)
        if rm_res:
            return rm_res

    # 3. Git irreversible subcommands
    if base_cmd == "git":
        git_res = check_git_destruction(args)
        if git_res:
            return git_res

    # 4. Raw block dd writes
    if base_cmd == "dd":
        dd_res = check_dd_destruction(args)
        if dd_res:
            return dd_res

    # 5. Dangerous device redirections
    redir_res = check_redirection_destruction(redirections)
    if redir_res:
        return redir_res

    return DestructiveAnalysisResult(is_destructive=False, reason=None, blast_radius=None)
