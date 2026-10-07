"""Quiet command rewriter, output spill, and Subagent context firewall types.

Defines command quiet-rewrite contracts, output disk spill receipts,
and Subagent firewall model downgrade and isolation results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CommandCategory(StrEnum):
    """Categorization of shell commands for targeted quiet optimization."""

    TEST_RUNNER = "test_runner"  # pytest, npm test, cargo test
    BUILD_TOOL = "build_tool"  # cargo build, tsc, mvn
    VCS = "vcs"  # git status, git log
    PACKAGE_MANAGER = "package_manager"  # pip, npm install


@dataclass(frozen=True)
class CommandRewriteResult:
    """Artifact of quiet command rewrite check."""

    original_command: str
    rewritten_command: str
    is_rewritten: bool
    category: CommandCategory | None
    injected_flag: str
    reason: str


@dataclass(frozen=True)
class OutputSpillReceipt:
    """Receipt tracking large tool output persisted to disk with compact context snippet."""

    is_spilled: bool
    exit_code: int
    original_char_count: int
    spilled_file_path: str | None
    context_snippet: str
    saved_tokens: int
    checksum_sha256: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SubagentFirewallConfig:
    """Configuration for isolating noisy background tasks to downgraded Subagents."""

    enable_firewall: bool = True
    default_isolated_model: str = "flash"
    max_delivered_summary_chars: int = 1500
    noisy_task_indicators: tuple[str, ...] = (
        "log_analysis",
        "wide_repo_search",
        "full_lint_scan",
        "test_suite_sweep",
    )


@dataclass(frozen=True)
class SubagentFirewallResult:
    """Outcome of running a noisy sub-task behind the context firewall."""

    task_name: str
    assigned_model: str
    raw_intermediate_chars: int
    delivered_summary_chars: int
    blocked_intermediate_tokens: int
    delivered_summary_tokens: int
    net_saved_main_session_tokens: int
    summary_text: str
