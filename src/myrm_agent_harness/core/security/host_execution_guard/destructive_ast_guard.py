"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/destructive_ast_guard.py
[INPUT] re, uuid, typing
[OUTPUT] DestructiveCommandASTGuard

AST and lexical analysis guardrail for preventing catastrophic shell commands on the host machine.
Detects destructive commands (rm -rf /, mkfs, dd, firewall flush) and enforces HITL gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import uuid

from .types import CommandInspectionResult, DestructiveRiskLevel

logger = logging.getLogger(__name__)


class DestructiveCommandASTGuard:
    """Evaluates shell commands prior to execution and enforces static AST/lexical guardrails."""

    BLOCKED_PATTERNS: tuple[tuple[str, str], ...] = (
        (
            r"(?:^|[;&|\s])rm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+(?:/|/\*|~|~\*|\$HOME|\$HOME/\*|\.\.|/etc(?:/.*)?|/usr(?:/.*)?|/bin(?:/.*)?|/sbin(?:/.*)?|/var(?:/.*)?|/System(?:/.*)?|/boot(?:/.*)?)(?:\s|$)",
            "Recursive force deletion of root, home, or critical system directories ('rm -rf /', 'rm -rf ~', 'rm -rf /etc')",
        ),
        (
            r"(?:^|[;&|\s])mkfs(?:\.[a-zA-Z0-9]+)?\s+",
            "Low-level filesystem formatting ('mkfs')",
        ),
        (
            r"(?:^|[;&|\s])dd\s+.*of=/dev/(?:[a-zA-Z0-9_]+)",
            "Direct raw block device overwriting ('dd of=/dev/...')",
        ),
        (
            r"(?:^|[;&|\s])chmod\s+(?:-R\s+)?(?:777|000)\s+(?:/|/etc|/usr|~)(?:\s|$)",
            "Destructive permission manipulation on system root ('chmod -R 777 /')",
        ),
        (
            r"(?:^|[;&|\s])(?:>|>>)\s*/dev/(?:[a-zA-Z0-9_]+)",
            "Direct redirection to hardware or block device",
        ),
        (
            r"(?:^|[;&|\s])mv\s+(?:/etc|/usr|/bin|/sbin|/System|/Library)(?:\s|$)",
            "Moving critical system directories",
        ),
    )

    HITL_REQUIRED_PATTERNS: tuple[tuple[str, str], ...] = (
        (
            r"(?:^|[;&|\s])rm\s+(?:-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\s+",
            "Recursive force file deletion ('rm -rf')",
        ),
        (
            r"(?:^|[;&|\s])(?:iptables\s+-[FZX]|ufw\s+(?:disable|reset)|nft\s+flush\s+ruleset)",
            "Host network firewall manipulation or rule flush",
        ),
        (
            r"(?:^|[;&|\s])systemctl\s+(?:stop|disable|mask)\s+",
            "Stopping or masking system services",
        ),
        (
            r"(?:^|[;&|\s])(?:reboot|shutdown|poweroff|init\s+0)(?:\s|$)",
            "Host machine reboot or shutdown instruction",
        ),
        (
            r"(?:^|[;&|\s])(?:killall|pkill)\s+-9\s+",
            "Forceful mass-process termination",
        ),
        (
            r"(?:^|[;&|\s])(?:cat|echo|tee)\s+.*(?:>|>>)\s*/etc/(?:hosts|resolv\.conf|fstab)",
            "Host network name resolution or mount table modification",
        ),
    )

    def __init__(self) -> None:
        self._compiled_blocked: list[tuple[re.Pattern[str], str]] = [
            (re.compile(p, re.IGNORECASE), exp) for p, exp in self.BLOCKED_PATTERNS
        ]
        self._compiled_hitl: list[tuple[re.Pattern[str], str]] = [
            (re.compile(p, re.IGNORECASE), exp) for p, exp in self.HITL_REQUIRED_PATTERNS
        ]
        self._pending_approvals: dict[str, CommandInspectionResult] = {}

    def inspect_command(self, command: str) -> CommandInspectionResult:
        """Inspect shell command string for catastrophic or high-risk execution patterns."""
        inspection_id = f"cmd-insp-{uuid.uuid4().hex[:12]}"
        normalized = command.strip()

        # 1. Check unconditionally blocked destructive patterns
        for pattern, explanation in self._compiled_blocked:
            if pattern.search(normalized):
                res = CommandInspectionResult(
                    inspection_id=inspection_id,
                    command=command,
                    risk_level=DestructiveRiskLevel.BLOCKED_DESTRUCTIVE,
                    matched_patterns=(pattern.pattern,),
                    explanation=f"Command strictly blocked: {explanation}",
                    requires_hitl=False,
                    is_blocked=True,
                )
                logger.warning("Blocked destructive command: %s (pattern: %s)", command, pattern.pattern)
                return res

        # 2. Check patterns requiring human operator confirmation (HITL)
        for pattern, explanation in self._compiled_hitl:
            if pattern.search(normalized):
                res = CommandInspectionResult(
                    inspection_id=inspection_id,
                    command=command,
                    risk_level=DestructiveRiskLevel.REQUIRE_HITL,
                    matched_patterns=(pattern.pattern,),
                    explanation=f"High-risk operation detected: {explanation}. Operator confirmation required.",
                    requires_hitl=True,
                    is_blocked=False,
                )
                self._pending_approvals[inspection_id] = res
                logger.info("Command requires HITL approval: %s (inspection_id: %s)", command, inspection_id)
                return res

        # 3. Safe command
        return CommandInspectionResult(
            inspection_id=inspection_id,
            command=command,
            risk_level=DestructiveRiskLevel.SAFE,
            matched_patterns=(),
            explanation="Command evaluated safe for local host execution.",
            requires_hitl=False,
            is_blocked=False,
        )

    def approve_command(self, inspection_id: str) -> CommandInspectionResult:
        """User confirms and approves a pending high-risk command execution ticket."""
        pending = self._pending_approvals.pop(inspection_id, None)
        if pending is None:
            raise KeyError(f"Pending command inspection '{inspection_id}' not found.")

        approved_res = CommandInspectionResult(
            inspection_id=pending.inspection_id,
            command=pending.command,
            risk_level=DestructiveRiskLevel.SAFE,
            matched_patterns=pending.matched_patterns,
            explanation=f"Command approved by user operator (originally: {pending.explanation}).",
            requires_hitl=False,
            is_blocked=False,
        )
        logger.info("Approved high-risk command inspection %s", inspection_id)
        return approved_res

    def reject_command(self, inspection_id: str) -> CommandInspectionResult:
        """User explicitly rejects a pending high-risk command ticket."""
        pending = self._pending_approvals.pop(inspection_id, None)
        if pending is None:
            raise KeyError(f"Pending command inspection '{inspection_id}' not found.")

        rejected_res = CommandInspectionResult(
            inspection_id=pending.inspection_id,
            command=pending.command,
            risk_level=DestructiveRiskLevel.BLOCKED_DESTRUCTIVE,
            matched_patterns=pending.matched_patterns,
            explanation="Command rejected by human operator.",
            requires_hitl=False,
            is_blocked=True,
        )
        return rejected_res

    def list_pending_approvals(self) -> list[CommandInspectionResult]:
        """List all commands currently awaiting operator approval."""
        return list(self._pending_approvals.values())
