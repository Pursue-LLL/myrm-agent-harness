"""Compiler converting high-level Hard Redline Rules into deterministic Sandbox Execution Policies.

[INPUT]
- HardRedlineRule collections and custom rule registration specs.

[OUTPUT]
- CompiledSandboxFirewallPolicy ready for physical execution boundary enforcement.

[POS]
- Harness core security engine translating organizational redlines into machine-enforced policies.
"""

from __future__ import annotations

import fnmatch
import re
import time
from typing import Final

from myrm_agent_harness.core.security.dual_track_sandbox_guard.types import (
    CompiledSandboxFirewallPolicy,
    HardRedlineRule,
    RedlineCategory,
)

# Built-in immutable baseline file protection patterns
_BASELINE_FILE_RULES: Final[tuple[HardRedlineRule, ...]] = (
    HardRedlineRule(
        rule_id="RL-FILE-001",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="**/.env*",
        description="Prevent reading or tampering with environment configuration files containing secrets",
    ),
    HardRedlineRule(
        rule_id="RL-FILE-002",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="**/*.pem",
        description="Prevent reading private certificates and TLS credentials",
    ),
    HardRedlineRule(
        rule_id="RL-FILE-003",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="**/*.key",
        description="Prevent access to private cryptographic key files",
    ),
    HardRedlineRule(
        rule_id="RL-FILE-004",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="**/id_rsa*",
        description="Prevent access to SSH private keys",
    ),
    HardRedlineRule(
        rule_id="RL-FILE-005",
        category=RedlineCategory.FILE_PROTECTION,
        pattern="/etc/shadow",
        description="Prevent host/container shadow password file exfiltration",
    ),
)

# Built-in immutable baseline command protection patterns
_BASELINE_COMMAND_RULES: Final[tuple[HardRedlineRule, ...]] = (
    HardRedlineRule(
        rule_id="RL-CMD-001",
        category=RedlineCategory.COMMAND_PROTECTION,
        pattern=r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-f[a-zA-Z]*r[a-zA-Z]*)\s+/\s*$",
        description="Block catastrophic recursive root filesystem deletion",
    ),
    HardRedlineRule(
        rule_id="RL-CMD-002",
        category=RedlineCategory.COMMAND_PROTECTION,
        pattern=r"\bmkfs(\.[a-zA-Z0-9]+)?\s+",
        description="Block filesystem formatting commands",
    ),
    HardRedlineRule(
        rule_id="RL-CMD-003",
        category=RedlineCategory.COMMAND_PROTECTION,
        pattern=r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
        description="Block bash fork bomb denial-of-service patterns",
    ),
    HardRedlineRule(
        rule_id="RL-CMD-004",
        category=RedlineCategory.COMMAND_PROTECTION,
        pattern=r">\s*/dev/sd[a-z]",
        description="Block raw block device wiping overwrites",
    ),
    HardRedlineRule(
        rule_id="RL-CMD-005",
        category=RedlineCategory.COMMAND_PROTECTION,
        pattern=r"\bchmod\s+(-R\s+)?777\s+/\s*$",
        description="Block root filesystem global permission widening",
    ),
)


class RedlinePolicyCompiler:
    """Compiles registered hard redline rules into executable sandbox firewall policies."""

    def __init__(self) -> None:
        self._rules: dict[str, HardRedlineRule] = {}
        for rule in _BASELINE_FILE_RULES:
            self._rules[rule.rule_id] = rule
        for rule in _BASELINE_COMMAND_RULES:
            self._rules[rule.rule_id] = rule

    def register_rule(self, rule: HardRedlineRule) -> None:
        """Register a new immutable redline rule."""
        self._rules[rule.rule_id] = rule

    def get_all_rules(self) -> list[HardRedlineRule]:
        """Retrieve all active hard redline rules."""
        return list(self._rules.values())

    def get_rule_by_id(self, rule_id: str) -> HardRedlineRule | None:
        """Find rule by its unique ID."""
        return self._rules.get(rule_id)

    def compile(self) -> CompiledSandboxFirewallPolicy:
        """Compile rules into optimized runtime patterns."""
        file_patterns: list[str] = []
        command_patterns: list[str] = []

        for rule in self._rules.values():
            if rule.category == RedlineCategory.FILE_PROTECTION:
                file_patterns.append(rule.pattern)
            elif rule.category == RedlineCategory.COMMAND_PROTECTION:
                command_patterns.append(rule.pattern)

        return CompiledSandboxFirewallPolicy(
            blocked_file_patterns=tuple(file_patterns),
            blocked_command_regexes=tuple(command_patterns),
            rule_count=len(self._rules),
            enforced_at=time.time(),
        )

    @classmethod
    def matches_file_pattern(cls, path: str, pattern: str) -> bool:
        """Evaluate if normalized path matches a file pattern."""
        norm = path.strip().replace("\\", "/")
        norm_name = norm.split("/")[-1]
        clean_pat = pattern.strip().replace("\\", "/")

        if clean_pat.startswith("**/"):
            suffix = clean_pat[3:]
            return fnmatch.fnmatch(norm_name, suffix) or fnmatch.fnmatch(norm, f"*/{suffix}")
        return fnmatch.fnmatch(norm, clean_pat) or fnmatch.fnmatch(norm_name, clean_pat)

    @classmethod
    def matches_command_pattern(cls, command: str, regex_pattern: str) -> bool:
        """Evaluate if command string triggers regex pattern."""
        return bool(re.search(regex_pattern, command, re.IGNORECASE))
