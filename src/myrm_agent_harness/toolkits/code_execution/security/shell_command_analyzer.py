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

Layer 3 (quote-stripped, ESCALATE):
  Suspicious but potentially legitimate patterns (curl|sh, eval, base64 -d,
  kill/pkill/killall). Forces ASK regardless of permission ruleset.

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
    (r"\bmkfs\.\w+", "Formatting filesystem"),
    (r"\bdd\s+.*\bof=/dev/", "Direct disk write"),
    (r">\s*/dev/sd[a-z]", "Overwriting disk device"),
    (r"\bshred\s+", "Secure file deletion"),
    (r":\(\)\s*\{[^}]*\}\s*;?\s*:", "Fork bomb"),
    (r"\bwhile\s+true\s*;\s*do\s+fork", "Fork loop"),
    (r"\bsudo\s+", "Privilege escalation via sudo"),
    (r"\bsu\s+(-|\w)", "Switch user"),
    (r"\bchmod\s+[0-7]*777\b", "Setting world-writable permissions"),
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
    # --- process termination (prevents agent self-destruction) ---
    (r"\bkill\s+", "Process termination"),
    (r"\bpkill\s+", "Process termination by name/pattern"),
    (r"\bkillall\s+", "Process termination by name"),
)

_SUSPICIOUS_PATTERNS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in _SUSPICIOUS_PATTERNS
)


# ---------------------------------------------------------------------------
# Quote-aware preprocessing — character-level state machine
# ---------------------------------------------------------------------------

_PLACEHOLDER = "\x01"


def _strip_quoted_content(command: str) -> str:
    """Replace single-quoted string content with placeholders using a state machine.

    Character-level parsing correctly distinguishes:
    - Regular single quotes ('...'): content replaced with placeholders
    - ANSI-C quoting ($'...'): treated as opaque (already BLOCKED by Layer 1.5),
      entire span replaced with placeholders to prevent false positives in Layer 2/3
    - Double quotes ("..."): NOT stripped (allow command substitution detection)

    CRITICAL SECURITY DESIGN:
    We ONLY strip single quotes and ANSI-C quote content. Double quotes allow
    command substitution (e.g., `echo "$(rm -rf /)"`) so their content MUST remain
    visible to downstream pattern matching.

    The state machine approach (consistent with risk_classifier._split_shell_operators)
    correctly handles edge cases like `'it'\\''s'` nested quoting that regex cannot.
    """
    result: list[str] = []
    i = 0
    n = len(command)

    while i < n:
        ch = command[i]

        # Detect ANSI-C quoting: $'...'
        if ch == "$" and i + 1 < n and command[i + 1] == "'":
            result.append(_PLACEHOLDER)  # replace $
            result.append(_PLACEHOLDER)  # replace '
            i += 2
            # Consume until closing unescaped single quote
            while i < n:
                if command[i] == "\\" and i + 1 < n:
                    result.append(_PLACEHOLDER)
                    result.append(_PLACEHOLDER)
                    i += 2
                elif command[i] == "'":
                    result.append(_PLACEHOLDER)
                    i += 1
                    break
                else:
                    result.append(_PLACEHOLDER)
                    i += 1

        # Detect locale quoting: $"..."
        elif ch == "$" and i + 1 < n and command[i + 1] == '"':
            result.append(_PLACEHOLDER)  # replace $
            result.append(_PLACEHOLDER)  # replace "
            i += 2
            while i < n:
                if command[i] == "\\" and i + 1 < n:
                    result.append(_PLACEHOLDER)
                    result.append(_PLACEHOLDER)
                    i += 2
                elif command[i] == '"':
                    result.append(_PLACEHOLDER)
                    i += 1
                    break
                else:
                    result.append(_PLACEHOLDER)
                    i += 1

        # Regular single quote
        elif ch == "'":
            result.append(ch)  # preserve opening quote
            i += 1
            while i < n and command[i] != "'":
                result.append(_PLACEHOLDER)
                i += 1
            if i < n:
                result.append(ch)  # preserve closing quote
                i += 1

        else:
            result.append(ch)
            i += 1

    return "".join(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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


def analyze_command(command: str) -> tuple[CommandThreat, ...]:
    """Analyze a shell command for security threats.

    Returns all detected threats sorted by severity (BLOCK first, then ESCALATE).
    Pure function — no side effects, no I/O.

    Layer 1 (binary/Unicode) checks run on the raw string.
    Layer 2/3 (injection vectors, dangerous commands, suspicious patterns) run
    on the quote-stripped string so ``echo "rm -rf /"`` won't false-positive.
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

    threats.sort(key=lambda t: 0 if t.level == ThreatLevel.BLOCK else 1)
    return tuple(threats)


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
