"""Compound Shell Command AST Firewall.

Implements strict inspection for shell compound operators (| && ; > $()) to prevent
pseudo-whitelist bypass attacks (e.g. `echo 'ok' | rm -rf /`).
"""

from __future__ import annotations

import re

from .types import CommandRiskLevel, CompoundCheckResult, FirewallVerdict

# Operators that transform a command into a compound structure
_OPERATOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PIPE", re.compile(r"\|&?")),
    ("AND", re.compile(r"&&")),
    ("OR", re.compile(r"\|\|")),
    ("SEMICOLON", re.compile(r";+")),
    ("REDIRECT_OUT", re.compile(r">&?|>>")),
    ("REDIRECT_IN", re.compile(r"<")),
    ("CMD_SUBST_DOLLAR", re.compile(r"\$\([^\)]*\)")),
    ("CMD_SUBST_BACKTICK", re.compile(r"`[^`]*`")),
    ("BACKGROUND", re.compile(r"(?<!&)&(?!&)")),
]

# Patterns representing high-risk or destructive actions
_CRITICAL_DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ROOT_RM_RF", re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*)\s+(/|/\*|~|~/\*|\.\.)", re.IGNORECASE)),
    ("FORMAT_DISK", re.compile(r"\bmkfs(\.[a-zA-Z0-9]+)?\s+", re.IGNORECASE)),
    ("RAW_DD_WRITE", re.compile(r"\bdd\s+.*of=/dev/(sd[a-z]|nvme[0-9]n[0-9]|null|zero)", re.IGNORECASE)),
    ("FORK_BOMB", re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:", re.IGNORECASE)),
    ("DROP_DATABASE", re.compile(r"\bdrop\s+(database|schema|table)\s+", re.IGNORECASE)),
    ("MASS_PERM_CHMOD", re.compile(r"\bchmod\s+(-R\s+)?777\s+(/|/\*|~)", re.IGNORECASE)),
    ("SHUTDOWN_SYSTEM", re.compile(r"\b(shutdown|reboot|init\s+0|halt)\b", re.IGNORECASE)),
]


class CompoundCommandFirewall:
    """Firewall inspecting and enforcing boundaries against compound shell commands."""

    def __init__(
        self,
        safe_single_whitelist: list[str] | None = None,
    ) -> None:
        self.safe_single_whitelist = safe_single_whitelist or [
            "ls", "dir", "pwd", "whoami", "date", "echo", "cat", "grep", "head", "tail"
        ]

    def split_sub_commands(self, command: str) -> list[str]:
        """Split a command by structural operators (;, &&, ||, |) while preserving readability."""
        delimiters = re.compile(r";|&&|\|\||\|")
        parts = delimiters.split(command)
        return [p.strip() for p in parts if p.strip()]

    def inspect(self, raw_command: str) -> CompoundCheckResult:
        """Inspect a raw command string for compound control operators and destructive payloads.

        Iron Rule: Compound commands NEVER bypass into auto-allow; they strictly require
        human-in-the-loop approval or security auditing.
        """
        trimmed = raw_command.strip()
        if not trimmed:
            return CompoundCheckResult(
                raw_command=raw_command,
                is_compound=False,
                operators_found=[],
                sub_commands=[],
                verdict=FirewallVerdict.ALLOW,
                risk_level=CommandRiskLevel.LOW,
                reason="Empty command",
            )

        # 1. Scan for critical destructive signatures across entire raw command
        for rule_name, crit_regex in _CRITICAL_DESTRUCTIVE_PATTERNS:
            if crit_regex.search(trimmed):
                return CompoundCheckResult(
                    raw_command=raw_command,
                    is_compound=True,
                    operators_found=[rule_name],
                    sub_commands=self.split_sub_commands(trimmed),
                    verdict=FirewallVerdict.BLOCK,
                    risk_level=CommandRiskLevel.CRITICAL,
                    reason=f"Hard blocked by critical destructive rule '{rule_name}'",
                )

        # 2. Scan for compound control operators
        operators_found: list[str] = []
        for op_name, op_regex in _OPERATOR_PATTERNS:
            if op_regex.search(trimmed):
                operators_found.append(op_name)

        is_compound = len(operators_found) > 0
        sub_commands = self.split_sub_commands(trimmed)

        # 3. Check sub-commands for hidden destructive commands
        for sub in sub_commands:
            for rule_name, crit_regex in _CRITICAL_DESTRUCTIVE_PATTERNS:
                if crit_regex.search(sub):
                    return CompoundCheckResult(
                        raw_command=raw_command,
                        is_compound=True,
                        operators_found=[*operators_found, rule_name],
                        sub_commands=sub_commands,
                        verdict=FirewallVerdict.BLOCK,
                        risk_level=CommandRiskLevel.CRITICAL,
                        reason=f"Sub-command '{sub}' triggered destructive rule '{rule_name}'",
                    )

        # 4. Enforce compound baseline: compound commands CANNOT be auto-allowed
        if is_compound:
            return CompoundCheckResult(
                raw_command=raw_command,
                is_compound=True,
                operators_found=operators_found,
                sub_commands=sub_commands,
                verdict=FirewallVerdict.AUDIT_REQUIRED,
                risk_level=CommandRiskLevel.MEDIUM,
                reason=f"Compound command detected with operators {operators_found}; auto-whitelist bypass blocked",
            )

        # 5. Simple single command check against whitelist
        first_token = trimmed.split()[0] if trimmed.split() else ""
        if first_token in self.safe_single_whitelist:
            return CompoundCheckResult(
                raw_command=raw_command,
                is_compound=False,
                operators_found=[],
                sub_commands=[trimmed],
                verdict=FirewallVerdict.ALLOW,
                risk_level=CommandRiskLevel.LOW,
                reason=f"Single command '{first_token}' verified in safe whitelist",
            )

        # Single command outside whitelist -> audit required
        return CompoundCheckResult(
            raw_command=raw_command,
            is_compound=False,
            operators_found=[],
            sub_commands=[trimmed],
            verdict=FirewallVerdict.AUDIT_REQUIRED,
            risk_level=CommandRiskLevel.LOW,
            reason=f"Single command '{first_token}' is not in safe whitelist",
        )
