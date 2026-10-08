"""Cross-host OS-level runtime security scanner and safe operator matrix.

[INPUT]
- Shell command strings or raw payloads

[OUTPUT]
- OsOperatorScanResult: AST and pattern scan verdict with detected vulnerability signatures.

[POS]
Harness core security module inspired by ECC (Hermes safe operator matrix).
Blocks destructive terminal commands, unauthenticated network egress, and credential sniffing.
"""

from __future__ import annotations

import re
import shlex
import time

from myrm_agent_harness.core.security.risk_evaluator.types import OsOperatorScanResult

# 1. Destructive system wipe patterns
_DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+-(?:r[fF]|f[rR]|rf)\s+(?:/|\*/|\$HOME|~)", "Root or home directory recursive wipe"),
    (r"\bmkfs(?:\.\w+)?\s+/dev/", "Direct filesystem format"),
    (r"\bdd\s+if=.*of=/dev/(?:sd|nvme|disk)", "Direct block device overwrite"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "Fork bomb payload"),
    (r"\bshutdown\s+-\w+", "System shutdown command"),
    (r"\breboot\b", "System reboot command"),
)

# 2. Credential and system state sniffing
_SNIFFING_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcat\s+/etc/(?:shadow|gshadow|master\.passwd)", "Direct shadow password read"),
    (r"\bcat\s+~?/\.ssh/id_(?:rsa|ed25519|dsa)", "SSH private key exposure"),
    (r"\bprintenv\b.*\|\s*(?:curl|wget|nc)", "Environment variable exfiltration via network pipe"),
    (r"\benv\b.*\|\s*(?:curl|wget|nc)", "Environment exfiltration via network pipe"),
)

# 3. Remote execution and pipe-to-shell injections
_REMOTE_EXEC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?:curl|wget)\s+[^\n|]+\|\s*(?:ba)?sh\b", "Piped remote script direct execution"),
    (r"\bnc\s+(?:-e|--exec)\s+/bin/(?:ba)?sh", "Netcat reverse shell spawn"),
    (r"\bbash\s+-i\s+>&?\s+/dev/tcp/", "Bash TCP reverse shell"),
)

# 4. Privilege escalation attempts
_PRIV_ESC_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsudo\s+su\b", "Unattended root switch via sudo su"),
    (r"\bchmod\s+[0-7]?[4-7][0-7]{2}\s+/bin/", "SUID bit manipulation on system binaries"),
)


class OsSecurityGuard:
    """Evaluates shell commands and executable scripts against OS-level threat models."""

    @classmethod
    def scan_command(cls, command: str) -> OsOperatorScanResult:
        """Scan command string against destructive, sniffing, and reverse shell rules."""
        if not command or not command.strip():
            return OsOperatorScanResult(
                safe=True,
                command_signature="empty_command",
                detected_vulnerabilities=(),
                blocked_patterns=(),
                scanned_at=time.time(),
            )

        cmd_stripped = command.strip()
        vulnerabilities: list[str] = []
        blocked: list[str] = []

        # 1. Pattern checks
        all_rules = (
            _DESTRUCTIVE_PATTERNS
            + _SNIFFING_PATTERNS
            + _REMOTE_EXEC_PATTERNS
            + _PRIV_ESC_PATTERNS
        )

        for pattern, desc in all_rules:
            if re.search(pattern, cmd_stripped, re.IGNORECASE):
                vulnerabilities.append(desc)
                blocked.append(pattern)

        # 2. Extract normalized command signature
        signature = "unknown"
        try:
            tokens = shlex.split(cmd_stripped)
            if tokens:
                signature = tokens[0]
        except ValueError:
            signature = cmd_stripped.split()[0] if cmd_stripped.split() else "malformed"

        is_safe = len(vulnerabilities) == 0
        return OsOperatorScanResult(
            safe=is_safe,
            command_signature=signature,
            detected_vulnerabilities=tuple(vulnerabilities),
            blocked_patterns=tuple(blocked),
            scanned_at=time.time(),
        )
