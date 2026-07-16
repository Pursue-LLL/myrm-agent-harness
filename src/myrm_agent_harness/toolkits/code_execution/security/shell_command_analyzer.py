"""Shell Command Analyzer — unified security analysis for shell commands.

Multi-layer detection with quote-aware preprocessing:

Layer 1 (raw string, always checked):
  Binary injection (embedded newlines, null bytes) and invisible Unicode
  obfuscation (12 categories). Never legitimate in LLM-generated commands.

Layer 1.5 (raw string, BLOCK):
  ANSI-C quoting ($'...') and locale quoting ($"...") that can hide arbitrary
  commands via escape sequences (hex, unicode, octal). Always obfuscation.

Layer 2 (quote-stripped, BLOCK):
  Injection vectors ($(), backticks, ${}, etc.), dangerous commands
  (rm -rf /, sudo, fork bombs, etc.), and encoded/inline execution.
  Runs on quote-stripped input so ``echo "rm -rf /"`` won't false-positive.
  Includes ``find -exec {} \\;`` exemption for the escaped semicolon.

Layer 2.5 (ORIGINAL command, ESCALATE):
  SQL statement guard — detects destructive SQL in DB client commands
  (psql/mysql/sqlite3/sqlcmd/mongosh). Runs on the original command before
  quote stripping to catch SQL inside single quotes.
  See: sql_statement_guard.py

Layer 3 (quote-stripped, ESCALATE):
  Suspicious but potentially legitimate patterns (curl|sh, eval, base64 -d,
  kill/pkill/killall). Forces ASK regardless of permission ruleset.

Layer 4 (recursive, BLOCK/ESCALATE):
  Extracts commands from shell wrappers that hide payloads in single quotes
  (bash -c '...', sh -c '...', trap '...' SIGNAL) and recursively analyzes
  them. Depth-limited to prevent DoS.

Consumers:
- execution/security/validator.validate_command() — defense-in-depth check
- agent/security/engine.evaluate_tool_call() — primary check
- toolkits/cron/runners.ShellJobRunner — pre-execution check

[INPUT]
- (none)

[OUTPUT]
- ThreatLevel: Severity level of a detected command threat.
- CommandThreat: A single security threat detected in a shell command.
- analyze_command: Analyze a shell command for security threats.
- has_block_threat: Quick check: return the first BLOCK-level threat, or None...
- has_escalate_threat: Quick check: return the first ESCALATE-level threat, or N...

[POS]
Shell Command Analyzer — unified security analysis for shell commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ThreatLevel(StrEnum):
    """Severity level of a detected command threat."""

    BLOCK = "block"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class CommandThreat:
    """A single security threat detected in a shell command."""

    level: ThreatLevel
    category: str
    detail: str
    evidence: str


# ---------------------------------------------------------------------------
# Layer 1: BLOCK — binary injection & Unicode obfuscation (raw string)
# ---------------------------------------------------------------------------

_BINARY_INJECTION: tuple[tuple[str, str], ...] = (
    ("\r", "embedded carriage return"),
    ("\x00", "null byte"),
)

_INVISIBLE_UNICODE: tuple[tuple[str, str], ...] = (
    ("\u200b", "zero-width space"),
    ("\u200c", "zero-width non-joiner"),
    ("\u200d", "zero-width joiner"),
    ("\u2060", "word joiner"),
    ("\ufeff", "zero-width no-break space (BOM)"),
    ("\u200e", "left-to-right mark"),
    ("\u200f", "right-to-left mark"),
    ("\u202a", "left-to-right embedding"),
    ("\u202b", "right-to-left embedding"),
    ("\u202c", "pop directional formatting"),
    ("\u202d", "left-to-right override"),
    ("\u202e", "right-to-left override"),
)

# ---------------------------------------------------------------------------
# Layer 1.5: BLOCK — ANSI-C / locale quoting evasion (raw string)
# ---------------------------------------------------------------------------
# ANSI-C quoting ($'...') allows \xHH, \NNN, \uHHHH escape sequences that
# decode at shell level, completely bypassing regex-based command detection.
# Locale quoting ($"...") allows similar evasion. Both are never produced by
# legitimate LLM code generation and always indicate obfuscation attempts.

_ANSI_C_QUOTE_RE = re.compile(r"\$'[^']*'")
_LOCALE_QUOTE_RE = re.compile(r'\$"[^"]*"')

# ---------------------------------------------------------------------------
# Layer 2: BLOCK — injection vectors & dangerous commands (quote-stripped)
# ---------------------------------------------------------------------------

_INJECTION_VECTORS: tuple[tuple[str, str], ...] = (
    (r"\$\(", "$() command substitution"),
    (r"`", "backtick command substitution"),
    (r"\$\{", "${} variable expansion"),
    (r";", "semicolon command chaining"),
    (r"<\(", "process substitution <()"),
    (r">\(", "process substitution >()"),
)

# `find -exec {} \;` and `find -execdir {} \;` use a backslash-escaped
# semicolon as the command terminator. The `\;` must appear at the very end
# of the normalized command to qualify — this prevents exempting chained
# commands like `find ... \; && malicious`.
_FIND_EXEC_TERMINATOR_RE = re.compile(r"\bfind\b.*\s-(?:exec|execdir)\b.*\{\}\s*\\;\s*$")

_INJECTION_VECTORS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), desc) for pattern, desc in _INJECTION_VECTORS
)

_DANGEROUS_COMMANDS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*/\s*$", "Deleting root directory"),
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*/\*", "Deleting all files in root"),
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*~(/|\s|$)", "Deleting home directory"),
    (r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)*\$HOME\b", "Deleting home directory"),
    (r"\brm\s+-rf\s+/(?!\w)", "Recursive force delete from root"),
    # Long-form options: --force, --recursive, --no-preserve-root
    (r"\brm\s+(\S+\s+)*--no-preserve-root\b", "Bypassing rm safety with --no-preserve-root"),
    (r"\brm\s+(\S+\s+)*(--force|--recursive)\s+(\S+\s+)*/\s*$", "Deleting root (long-form options)"),
    (r"\brm\s+(\S+\s+)*(--force|--recursive)\s+(\S+\s+)*/\*", "Deleting root files (long-form options)"),
    (r"\brm\s+(\S+\s+)*(--force|--recursive)\s+(\S+\s+)*~(/|\s|$)", "Deleting home (long-form options)"),
    (r"\brm\s+(\S+\s+)*(--force|--recursive)\s+(\S+\s+)*\$HOME\b", "Deleting home (long-form options)"),
    # Options-after-operand: rm /path -rf, rm ~ -rf
    (r"\brm\s+/\s+-[a-zA-Z]*[rf][a-zA-Z]*", "Deleting root (options after path)"),
    (r"\brm\s+/\*\s+-[a-zA-Z]*[rf][a-zA-Z]*", "Deleting root files (options after path)"),
    (r"\brm\s+~\s+-[a-zA-Z]*[rf][a-zA-Z]*", "Deleting home (options after path)"),
    (r"\brm\s+\$HOME\s+-[a-zA-Z]*[rf][a-zA-Z]*", "Deleting home (options after path)"),
    (r"\bmkfs\.\w+", "Formatting filesystem"),
    (r"\bdd\s+.*\bof=/dev/", "Direct disk write"),
    (r">\s*/dev/sd[a-z]", "Overwriting disk device"),
    (r"\bshred\s+", "Secure file deletion"),
    (r":\(\)\s*\{[^}]*\}\s*;?\s*:", "Fork bomb"),
    (r"\bwhile\s+true\s*;\s*do\s+fork", "Fork loop"),
    (r"\bsudo\s+", "Privilege escalation via sudo"),
    (r"\bsu\s+(-|\w)", "Switch user"),
    (r"\bchmod\s+[0-7]*777\b", "Setting world-writable permissions"),
    (r"\bchmod\s+(-[a-zA-Z]*\s+)?0{1,4}\b", "Stripping all permissions (chmod 0)"),
    (r"\bchown\s+root", "Changing ownership to root"),
    (r"\bsystemctl\s+(stop|disable|mask)\s+", "Stopping system services"),
    (r"\bservice\s+\w+\s+(stop|disable)", "Stopping services"),
    (r"\binit\s+[0156]", "Changing runlevel"),
    (r"\bshutdown\b", "System shutdown"),
    (r"\breboot\b", "System reboot"),
    (r"\bhalt\b", "System halt"),
    (r"\bpoweroff\b", "System poweroff"),
    (r"\bnmap\s+", "Network scanning"),
    (r"\bnetcat\s+.*-e\s+", "Netcat reverse shell"),
    (r"\bnc\s+.*-e\s+", "Netcat reverse shell"),
    (r"\bfind\s+/\s.*-delete\b", "Deleting files from root directory"),
    (r"\bfind\s+~\s*.*-delete\b", "Deleting files from home directory"),
    (r"\bfind\s+\$HOME\s.*-delete\b", "Deleting files from home directory"),
    (r"\bcat\s+/etc/(passwd|shadow)", "Reading sensitive system files"),
    (r">\s*/etc/", "Overwriting system config files"),
    (r"\bhistory\s+-c\b", "Clearing command history"),
    (r"\brm\s+.*\.bash_history", "Deleting bash history"),
    (r">\s*/var/log/", "Clearing system logs"),
    (r"\binsmod\b", "Loading kernel module"),
    (r"\brmmod\b", "Removing kernel module"),
    (r"\bmodprobe\b", "Kernel module operation"),
    (r"\bmount\s+", "Mounting filesystems"),
    (r"\bumount\s+", "Unmounting filesystems"),
    (r"\bchroot\b", "Changing root directory"),
    (r"\bexport\s+LD_PRELOAD=", "LD_PRELOAD injection"),
    (r"\bexport\s+PATH=.*:", "PATH manipulation"),
    # --- encoded execution (piping decoded content to shell) ---
    (r"\becho\s+\S+\s*\|\s*base64\s+-d\s*\|\s*(ba)?sh\b", "Base64-encoded shell execution"),
    (r"\bprintf\s+.*\|\s*(ba)?sh\b", "Printf-piped shell execution"),
    (r"\bxxd\s+-r\s*\|\s*(ba)?sh\b", "Hex-decoded shell execution"),
    # --- interpreter inline execution ---
    (r"\bpython3?\s+-c\s+", "Python inline execution"),
    (r"\bnode\s+(-e|--eval)\s+", "Node.js inline execution"),
    (r"\bperl\s+-e\s+", "Perl inline execution"),
    (r"\bruby\s+-e\s+", "Ruby inline execution"),
    (r"\bphp\s+-r\s+", "PHP inline execution"),
    (r"\blua\s+-e\s+", "Lua inline execution"),
    (r"\bawk\s+'BEGIN\s*\{", "AWK inline program execution"),
    # --- environment variable injection (beyond LD_PRELOAD/PATH) ---
    (r"\bexport\s+NODE_OPTIONS=", "NODE_OPTIONS injection"),
    (r"\bexport\s+PYTHONPATH=", "PYTHONPATH injection"),
    (r"\bexport\s+DYLD_", "DYLD_* injection (macOS)"),
    (r"\bexport\s+PERL5OPT=", "PERL5OPT injection"),
    (r"\bexport\s+RUBYOPT=", "RUBYOPT injection"),
    (r"\bexport\s+LD_LIBRARY_PATH=", "LD_LIBRARY_PATH injection"),
    # --- SQL destructive commands (often piped to sqlite3 or psql) ---
    (r"\bDROP\s+(TABLE|DATABASE)\b", "SQL DROP"),
    (r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", "SQL DELETE without WHERE"),
    (r"\bTRUNCATE\s+(TABLE)?\s*\w", "SQL TRUNCATE"),
    # --- system binary / shell config overwrite ---
    (r">\s*(/usr/bin/|/bin/|/sbin/)\w", "Overwriting system binaries"),
    (r">\s*~/?\.(bashrc|profile|zshrc|bash_profile|zprofile)", "Overwriting shell startup files"),
    # --- process environment leakage ---
    (r"/proc/[^/]+/environ\b", "Reading process environment variables"),
    # --- bash built-in networking (bypasses firewall / tool allowlists) ---
    (r"/dev/tcp/", "Bash built-in networking (bypass)"),
    # --- configuration protection ---
    (r"(?:>|sed\s|awk\s|rm\s|cp\s|mv\s).*?(?:\s|^|/)(eslint\.config\.[a-z]+|\.eslintrc(\.[a-z]+)?|\.prettierrc(\.[a-z]+)?|prettier\.config\.[a-z]+|biome\.jsonc?|\.?ruff\.toml|tsconfig(\..+)?\.json|\.stylelintrc(\.[a-z]+)?|\.markdownlint(rc|\.[a-z]+)|\.shellcheckrc|jest\.config\.[a-z]+|commitlint\.config\.[a-z]+|\.cursorrules|rule\.mdc)(?:\s|$)", "Modifying configuration file via shell"),
    # --- lockfile protection (allows rm/mv for resetting, blocks sed/awk/echo for text manipulation) ---
    (r"(?:>|sed\s|awk\s|echo\s).*?(?:\s|^|/)(package-lock\.json|uv\.lock|poetry\.lock|pnpm-lock\.yaml|bun\.lockb|yarn\.lock|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock)(?:\s|$)", "Modifying lockfile via shell"),
)

_DANGEROUS_COMMANDS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in _DANGEROUS_COMMANDS
)


# ---------------------------------------------------------------------------
# Layer 3: ESCALATE — suspicious but potentially legitimate (quote-stripped)
# ---------------------------------------------------------------------------

_SUSPICIOUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bcurl\s+.*\|\s*(ba)?sh\b", "Remote code execution via curl | sh"),
    (r"\bwget\s+.*\|\s*(ba)?sh\b", "Remote code execution via wget | sh"),
    (r"\bcurl\s+.*\|\s*python", "Remote code execution via curl | python"),
    (r"\bwget\s+.*\|\s*python", "Remote code execution via wget | python"),
    (r"\beval\s+", "Dynamic code execution via eval"),
    (r"\bbase64\s+-d", "Base64 decode (potential encoding bypass)"),
    # --- heredoc execution ---
    (r"<<\s*\w+\s*\n.*\b(ba)?sh\b", "Heredoc shell execution"),
    # --- hex escape in non-ANSI-C context (e.g. printf/echo -e) ---
    (r"\\x[0-9a-fA-F]{2}", "Hex escape sequence (potential obfuscation)"),
    # --- network listening / tunneling tools (dangerous in sandboxes) ---
    (r"\bnc\s+.*-l", "Netcat listen mode (network exposure)"),
    (r"\bnetcat\s+.*-l", "Netcat listen mode (network exposure)"),
    (r"\bncat\s+", "Ncat network utility (potential tunneling)"),
    (r"\bsocat\s+", "Socat bidirectional relay (potential tunneling)"),
    # --- process termination (prevents agent self-destruction) ---
    (r"\bkill\s+", "Process termination"),
    (r"\bpkill\s+", "Process termination by name/pattern"),
    (r"\bkillall\s+", "Process termination by name"),
)

_SUSPICIOUS_PATTERNS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in _SUSPICIOUS_PATTERNS
)


# ---------------------------------------------------------------------------
# Layer 3b: ESCALATE — third-party integration write mutations (quote-stripped)
# Registered at runtime by the business layer via register_integration_write_patterns().
# ---------------------------------------------------------------------------

_EXTRA_INTEGRATION_WRITE_PATTERNS: list[tuple[re.Pattern[str], str]] = []


def register_integration_write_patterns(patterns: tuple[tuple[str, str], ...]) -> None:
    """Register business-layer integration write-detection regex patterns.

    Harness ships with zero vendor-specific rules; myrm-agent-server registers
    patterns (e.g. Google Workspace) at startup. Duplicate pattern strings are ignored.
    """
    existing = {compiled.pattern for compiled, _ in _EXTRA_INTEGRATION_WRITE_PATTERNS}
    for pattern, desc in patterns:
        compiled = re.compile(pattern, re.IGNORECASE)
        if compiled.pattern in existing:
            continue
        _EXTRA_INTEGRATION_WRITE_PATTERNS.append((compiled, desc))
        existing.add(compiled.pattern)


def _integration_write_patterns_compiled() -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple(_EXTRA_INTEGRATION_WRITE_PATTERNS)


# ---------------------------------------------------------------------------
# Quote-aware preprocessing & recursive shell wrapper analysis
# ---------------------------------------------------------------------------

from .shell_command_strip import _strip_quoted_content

_MAX_RECURSIVE_DEPTH = 8

_SHELL_EXEC_SINGLE_QUOTE_RE = re.compile(
    r"\b(?:ba|da|z|k)?sh\s+-[a-zA-Z]*c\s+'([^']+)'"
)
_TRAP_SINGLE_QUOTE_RE = re.compile(
    r"\btrap\s+'([^']+)'\s+\w+"
)


def _extract_embedded_commands(command: str) -> list[str]:
    """Extract commands hidden inside single-quoted shell wrappers."""
    embedded: list[str] = []
    for match in _SHELL_EXEC_SINGLE_QUOTE_RE.finditer(command):
        embedded.append(match.group(1))
    for match in _TRAP_SINGLE_QUOTE_RE.finditer(command):
        embedded.append(match.group(1))
    return embedded


def _analyze_recursive(command: str, depth: int) -> list[CommandThreat]:
    """Recursively analyze embedded commands up to MAX_RECURSIVE_DEPTH."""
    if depth >= _MAX_RECURSIVE_DEPTH:
        return []

    embedded = _extract_embedded_commands(command)
    threats: list[CommandThreat] = []
    for cmd in embedded:
        threats.extend(analyze_command(cmd, _depth=depth + 1))
    return threats


def is_destructive_command(command: str) -> bool:
    """Check if a command is destructive (modifies files/state significantly).

    This is used to trigger auto-snapshots before execution.
    """
    if not command or not command.strip():
        return False

    stripped = _strip_quoted_content(command)
    normalized = " ".join(stripped.split())

    # Common destructive commands
    destructive_patterns = [
        r"\brm\s+",
        r"\bmv\s+",
        r"\bsed\s+-i\b",
        r"\bgit\s+(reset|clean|checkout|restore|apply)\b",
        r"\bcp\s+.*-r\b",
        r"\bfind\s+.*-delete\b",
        r"\bfind\s+.*-exec\s+rm\b",
        r">\s*\S+",  # Redirection overwrite
    ]

    for pattern in destructive_patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True

    return False


def analyze_command(command: str, *, _depth: int = 0) -> tuple[CommandThreat, ...]:
    """Analyze a shell command for security threats.

    Returns all detected threats sorted by severity (BLOCK first, then ESCALATE).
    Pure function — no side effects, no I/O.

    Layer 1 (binary/Unicode) checks run on the raw string.
    Layer 2/3 (injection vectors, dangerous commands, suspicious patterns) run
    on the quote-stripped string so ``echo "rm -rf /"`` won't false-positive.
    Layer 4 (recursive) extracts commands from `bash -c '...'` and `trap '...'`
    wrappers and recursively analyzes them.
    """
    if not command or not command.strip():
        return ()

    threats: list[CommandThreat] = []

    for char, desc in _BINARY_INJECTION:
        if char in command:
            threats.append(
                CommandThreat(
                    level=ThreatLevel.BLOCK,
                    category="injection",
                    detail=desc,
                    evidence=repr(char),
                )
            )

    for char, desc in _INVISIBLE_UNICODE:
        if char in command:
            threats.append(
                CommandThreat(
                    level=ThreatLevel.BLOCK,
                    category="obfuscation",
                    detail=f"Invisible Unicode character: {desc}",
                    evidence=repr(char),
                )
            )

    # Layer 1.5: ANSI-C / locale quoting detection (before quote stripping)
    ansi_c_match = _ANSI_C_QUOTE_RE.search(command)
    if ansi_c_match:
        threats.append(
            CommandThreat(
                level=ThreatLevel.BLOCK,
                category="obfuscation",
                detail="ANSI-C quoting ($'...') can hide arbitrary commands via escape sequences",
                evidence=ansi_c_match.group(0),
            )
        )

    locale_match = _LOCALE_QUOTE_RE.search(command)
    if locale_match:
        threats.append(
            CommandThreat(
                level=ThreatLevel.BLOCK,
                category="obfuscation",
                detail='Locale quoting ($"...") can hide characters via escape sequences',
                evidence=locale_match.group(0),
            )
        )

    stripped = _strip_quoted_content(command)
    normalized = " ".join(stripped.split())

    for pattern, desc in _INJECTION_VECTORS_COMPILED:
        match = pattern.search(normalized)
        if match:
            if desc == "semicolon command chaining" and _FIND_EXEC_TERMINATOR_RE.search(normalized):
                continue
            threats.append(
                CommandThreat(
                    level=ThreatLevel.BLOCK,
                    category="injection",
                    detail=desc,
                    evidence=match.group(0),
                )
            )

    for pattern, desc in _DANGEROUS_COMMANDS_COMPILED:
        match = pattern.search(normalized)
        if match:
            threats.append(
                CommandThreat(
                    level=ThreatLevel.BLOCK,
                    category="dangerous_command",
                    detail=desc,
                    evidence=match.group(0),
                )
            )

    # Layer 2.5: SQL statement guard (uses ORIGINAL command for DB client extraction)
    from myrm_agent_harness.toolkits.code_execution.security.sql_statement_guard import (
        check_sql_threats,
    )

    threats.extend(check_sql_threats(command))

    for pattern, desc in _SUSPICIOUS_PATTERNS_COMPILED:
        match = pattern.search(normalized)
        if match:
            threats.append(
                CommandThreat(
                    level=ThreatLevel.ESCALATE,
                    category="suspicious_pattern",
                    detail=desc,
                    evidence=match.group(0),
                )
            )

    for pattern, desc in _integration_write_patterns_compiled():
        match = pattern.search(normalized)
        if match:
            threats.append(
                CommandThreat(
                    level=ThreatLevel.ESCALATE,
                    category="integration_mutation",
                    detail=desc,
                    evidence=match.group(0),
                )
            )

    # Layer 4: Recursive analysis of embedded commands in shell wrappers
    if _depth < _MAX_RECURSIVE_DEPTH:
        threats.extend(_analyze_recursive(command, _depth))

    threats.sort(key=lambda t: 0 if t.level == ThreatLevel.BLOCK else 1)
    return tuple(threats)


def is_integration_mutation_command(command: str) -> bool:
    """Return True when a shell command performs a third-party integration write."""
    stripped = _strip_quoted_content(command)
    normalized = " ".join(stripped.split())
    for pattern, _desc in _integration_write_patterns_compiled():
        if pattern.search(normalized):
            return True
    return False


def has_block_threat(command: str) -> CommandThreat | None:
    """Quick check: return the first BLOCK-level threat, or None if clean."""
    for threat in analyze_command(command):
        if threat.level == ThreatLevel.BLOCK:
            return threat
    return None


def has_escalate_threat(command: str) -> CommandThreat | None:
    """Quick check: return the first ESCALATE-level threat, or None if clean."""
    for threat in analyze_command(command):
        if threat.level == ThreatLevel.ESCALATE:
            return threat
    return None
