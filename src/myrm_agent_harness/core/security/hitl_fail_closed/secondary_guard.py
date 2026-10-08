"""Non-Bypassable Secondary Guard enforcing physical and invariant security boundaries.

[INPUT]
- Tool names and argument key-value mappings.

[OUTPUT]
- SecondaryGuardVerdict indicating whether fundamental physical safety invariants are respected.

[POS]
- Harness core security barrier that cannot be relaxed or bypassed by human approval or prompts.
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.core.security.hitl_fail_closed.types import (
    SecondaryGuardVerdict,
)

_DESTRUCTIVE_COMMAND_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f*|-f[a-zA-Z]*r[a-zA-Z]*)\s+/\s*$", re.IGNORECASE),
    re.compile(r"\bmkfs(\.[a-zA-Z0-9]+)?\s+", re.IGNORECASE),
    re.compile(r"\bdd\s+if=/dev/zero\s+of=/dev/[a-zA-Z0-9]+", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.IGNORECASE),
    re.compile(r">\s*/dev/sd[a-z]", re.IGNORECASE),
)

_CRITICAL_INVARIANT_PATHS: Final[tuple[str, ...]] = (
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/master.passwd",
    "~/.ssh/id_rsa",
    "~/.ssh/id_ed25519",
    "/proc/kcore",
)


class NonBypassableSecondaryGuard:
    """Secondary security invariant guard evaluated strictly after human approval."""

    @classmethod
    def evaluate(cls, tool_name: str, arguments: dict[str, str]) -> tuple[SecondaryGuardVerdict, str]:
        """Verify that tool parameters do not violate fundamental system integrity invariants."""
        # Check command executions for system annihilation commands
        command_str = arguments.get("command", "") or arguments.get("cmd", "")
        if command_str:
            for pattern in _DESTRUCTIVE_COMMAND_PATTERNS:
                if pattern.search(command_str):
                    return (
                        SecondaryGuardVerdict.BLOCKED_PHYSICAL_INVARIANT,
                        f"Non-bypassable guard blocked destructive pattern in command: '{command_str}'.",
                    )

        # Check file targets for critical OS credential and configuration files
        target_path = (
            arguments.get("path", "")
            or arguments.get("file_path", "")
            or arguments.get("target", "")
            or arguments.get("destination", "")
        )
        if target_path:
            norm_path = target_path.strip().lower()
            for crit_path in _CRITICAL_INVARIANT_PATHS:
                if crit_path in norm_path or norm_path.endswith(crit_path.lstrip("~")):
                    return (
                        SecondaryGuardVerdict.BLOCKED_HIGH_RISK_PATTERN,
                        f"Non-bypassable guard blocked access to protected system invariant file: '{target_path}'.",
                    )

        return (
            SecondaryGuardVerdict.PASSED,
            "Tool execution passed non-bypassable secondary invariant security checks.",
        )
