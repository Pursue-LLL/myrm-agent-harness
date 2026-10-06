"""Shell command rule tables — the pattern catalogue behind the analyzer layers.

Pure data: literal and regex rules grouped by analyzer layer. Detection logic,
quote-aware preprocessing and threat classification live in
``shell_command_analyzer``; keeping the catalogue separate lets rules be added
without growing the engine module.

Layers served:
- Layer 1 (raw string): ``BINARY_INJECTION`` (CR/NUL) and ``INVISIBLE_UNICODE``.
- Layer 1.5 (raw string): ``ANSI_C_QUOTE_RE`` / ``LOCALE_QUOTE_RE`` quoting evasion.
- Layer 2 (quote-stripped, BLOCK): ``INJECTION_VECTORS_COMPILED`` (shell syntax),
  ``FIND_EXEC_TERMINATOR_RE`` (the ``find -exec ... \\;`` exemption) and
  ``DANGEROUS_COMMANDS_COMPILED``.
- Layer 3 (quote-stripped, ESCALATE): ``SUSPICIOUS_PATTERNS_COMPILED``.

[INPUT]
- None (stdlib ``re`` only; no dependency on analyzer types)

[OUTPUT]
- BINARY_INJECTION / INVISIBLE_UNICODE: (literal, description) pairs checked on the raw string.
- ANSI_C_QUOTE_RE / LOCALE_QUOTE_RE: compiled quoting-evasion detectors.
- INJECTION_VECTORS_COMPILED / FIND_EXEC_TERMINATOR_RE: syntax-injection vectors and the find -exec exemption.
- DANGEROUS_COMMANDS_COMPILED: BLOCK-level dangerous command patterns (case-insensitive).
- SUSPICIOUS_PATTERNS_COMPILED: ESCALATE-level suspicious patterns (case-insensitive).

[POS]
Data tier of the shell command analyzer; consumed only by ``shell_command_analyzer``.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Layer 1: BLOCK — binary injection & Unicode obfuscation (raw string)
# ---------------------------------------------------------------------------

BINARY_INJECTION: tuple[tuple[str, str], ...] = (
    ("\r", "embedded carriage return"),
    ("\x00", "null byte"),
)

INVISIBLE_UNICODE: tuple[tuple[str, str], ...] = (
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

ANSI_C_QUOTE_RE = re.compile(r"\$'[^']*'")
LOCALE_QUOTE_RE = re.compile(r'\$"[^"]*"')

# ---------------------------------------------------------------------------
# Layer 2: BLOCK — injection vectors & dangerous commands (quote-stripped)
# ---------------------------------------------------------------------------

# Category ``injection`` is reserved for these shell-syntax vectors: a style policy
# for LLM-generated one-liners that callers vetting human-authored commands (the
# hook gate) may waive. Control-character smuggling (``BINARY_INJECTION``) is
# categorised ``binary_injection`` so such a waiver can never cover it.
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
FIND_EXEC_TERMINATOR_RE = re.compile(r"\bfind\b.*\s-(?:exec|execdir)\b.*\{\}\s*\\;\s*$")

INJECTION_VECTORS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
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
    # --- SSH access persistence (key planting / client config hijack) ---
    (r"(?:>|\btee\b)[^|;&]*\.ssh/(?:authorized_keys2?|config)\b", "Modifying SSH access files"),
    # --- process environment leakage ---
    (r"/proc/[^/]+/environ\b", "Reading process environment variables"),
    # --- bash built-in networking (bypasses firewall / tool allowlists) ---
    (r"/dev/tcp/", "Bash built-in networking (bypass)"),
    # --- configuration protection ---
    (
        r"(?:>|sed\s|awk\s|rm\s|cp\s|mv\s).*?(?:\s|^|/)(eslint\.config\.[a-z]+|\.eslintrc(\.[a-z]+)?|\.prettierrc(\.[a-z]+)?|prettier\.config\.[a-z]+|biome\.jsonc?|\.?ruff\.toml|tsconfig(\..+)?\.json|\.stylelintrc(\.[a-z]+)?|\.markdownlint(rc|\.[a-z]+)|\.shellcheckrc|jest\.config\.[a-z]+|commitlint\.config\.[a-z]+|\.cursorrules|rule\.mdc)(?:\s|$)",
        "Modifying configuration file via shell",
    ),
    # --- lockfile protection (allows rm/mv for resetting, blocks sed/awk/echo for text manipulation) ---
    (
        r"(?:>|sed\s|awk\s|echo\s).*?(?:\s|^|/)(package-lock\.json|uv\.lock|poetry\.lock|pnpm-lock\.yaml|bun\.lockb|yarn\.lock|go\.sum|Cargo\.lock|Gemfile\.lock|composer\.lock)(?:\s|$)",
        "Modifying lockfile via shell",
    ),
)

DANGEROUS_COMMANDS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
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
    # --- scheduled-task persistence: install/edit/remove (``crontab -l`` listing stays clean) ---
    (r"\bcrontab\s+(?:-[eri]\b|-(?:\s|$)|[^-\s])", "Cron table modification (persistence)"),
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

SUSPICIOUS_PATTERNS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), desc) for pattern, desc in _SUSPICIOUS_PATTERNS
)
