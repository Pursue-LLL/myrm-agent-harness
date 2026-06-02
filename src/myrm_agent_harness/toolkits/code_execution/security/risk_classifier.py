"""Command risk classifier for shell_exec auto-allow decisions.

Classifies shell commands into SAFE (read-only / informational, auto-allow)
or UNKNOWN (requires human confirmation).

Designed as the **final fallback** in ``engine.evaluate_tool_call()``:
only invoked when all prior security layers (capability fence, threat analysis,
URL/domain checks, path policy, user ruleset) yield a default ASK.

Safety guarantees:
1. Shell-operator-aware — splits on ``|``, ``&&``, ``||`` (quote-aware)
   and checks every segment independently.
2. Redirect-aware — any I/O redirect (``>``, ``<``, ``>>``) → UNKNOWN.
3. Conservative inclusion — only pure read-only commands are classified SAFE.
4. Flag-level validation — commands with subcommand configs (e.g. git) are
   validated at the flag granularity: unknown flags → UNKNOWN.

[INPUT]
- (none)

[OUTPUT]
- CommandRiskLevel: Risk classification for a shell command.
- classify_command_risk: Classify a shell command's risk level.

[POS]
Command risk classifier for shell_exec auto-allow decisions.
"""

from __future__ import annotations

import re
from enum import StrEnum

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
    SUBCOMMAND_CONFIGS,
    FlagArgType,
    SubcommandConfig,
)


class CommandRiskLevel(StrEnum):
    """Risk classification for a shell command."""

    SAFE = "safe"
    UNKNOWN = "unknown"


SAFE_COMMANDS: frozenset[str] = frozenset(
    {
        # Filesystem read-only
        "ls",
        "dir",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "file",
        "wc",
        "du",
        "df",
        "stat",
        "tree",
        "realpath",
        "basename",
        "dirname",
        "readlink",
        "pwd",
        # Search / filter / text-processing read-only
        "grep",
        "rg",
        "ag",
        "fd",
        "fzf",
        "sort",
        "uniq",
        "diff",
        "comm",
        "cut",
        "tr",
        "fmt",
        "fold",
        "nl",
        "paste",
        "join",
        "column",
        "expand",
        "unexpand",
        "rev",
        "tac",
        # Simple output
        "echo",
        "printf",
        "true",
        "false",
        "yes",
        # System info read-only
        "uname",
        "arch",
        "id",
        "whoami",
        "groups",
        "uptime",
        "nproc",
        "lscpu",
        "lsb_release",
        "sw_vers",
        "which",
        "where",
        "type",
        "command",
        "locale",
        # Terminal / misc safe
        "cd",
        "clear",
        "reset",
        "tput",
        # Checksum read-only
        "md5sum",
        "sha256sum",
        "sha1sum",
        "shasum",
        "cksum",
        "b2sum",
        # Binary inspection read-only
        "od",
        "hexdump",
        "strings",
        # Test runners (workspace-scoped, read-only analysis)
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "phpunit",
        # Linters / type checkers (read-only static analysis)
        "eslint",
        "ruff",
        "mypy",
        "pyright",
        "tsc",
        "biome",
        "flake8",
        "pylint",
        "black",
        "isort",
        "prettier",
        "stylelint",
        "shellcheck",
        # Build tools (workspace-scoped compilation)
        "make",
        "cmake",
        "gradle",
        "mvn",
        "ant",
        # Version managers (read-only)
        "nvm",
        "rbenv",
        "pyenv",
        "fnm",
        "volta",
        # Misc development tools (read-only or workspace-safe only)
        "jq",
        "yq",
        "envsubst",
        "date",
        "cal",
        "bc",
        "expr",
        "seq",
        "sleep",
        "timeout",
        "time",
        "touch",
        "mkdir",
        "locate",
        "pbcopy",
        "pbpaste",
    }
)

_REDIRECT_CHARS: frozenset[str] = frozenset({"<", ">"})

_FLAG_RE = re.compile(r"^--?[a-zA-Z0-9]")
_GIT_NUMERIC_SHORTHAND = re.compile(r"^-\d+$")
_NUMERIC_VALUE_RE = re.compile(r"^[+-]?\d+[a-zA-Z]?$")


def _has_redirect(segment: str) -> bool:
    """Check if a pipeline segment contains I/O redirection operators."""
    return any(ch in segment for ch in _REDIRECT_CHARS)


def _is_numeric_value(token: str) -> bool:
    """Check if a token is a numeric value (e.g. -7, +30, -10M) rather than a flag.

    Handles find-style numeric arguments: ``-mtime -7``, ``-size +10M``.
    """
    return bool(_NUMERIC_VALUE_RE.match(token))


# ---------------------------------------------------------------------------
# Flag-level validation engine
# ---------------------------------------------------------------------------


def _resolve_subcommand(
    base_cmd: str,
    tokens: list[str],
    start: int,
    configs: dict[str, SubcommandConfig],
) -> tuple[SubcommandConfig | None, int]:
    """Find the longest matching subcommand config for tokens starting at *start*.

    Returns (config, index_after_subcommand) or (None, start) if no match.
    Longer subcommand keys are tried first (e.g. "stash list" before "stash").
    """
    sorted_keys = sorted(configs.keys(), key=lambda k: -len(k.split()))
    remaining = tokens[start:]

    for key in sorted_keys:
        parts = key.split()
        if len(parts) > len(remaining):
            continue
        if [t.lower() for t in remaining[: len(parts)]] == [p.lower() for p in parts]:
            return configs[key], start + len(parts)

    return None, start


def _validate_flags(
    tokens: list[str],
    start: int,
    config: SubcommandConfig,
    *,
    base_cmd: str = "",
) -> bool:
    """Walk tokens from *start*, validating each flag against *config*.

    Returns True only when every flag is in the whitelist with correct arg type.
    Unknown flags → False (conservative). Positional args are collected and
    passed to ``config.is_positional_dangerous`` if provided.
    """
    i = start
    positionals: list[str] = []
    seen_flags: set[str] = set()
    past_double_dash = False

    while i < len(tokens):
        token = tokens[i]

        if token == "--" and not past_double_dash:
            if config.respects_double_dash:
                past_double_dash = True
                i += 1
                continue
            i += 1
            continue

        if past_double_dash or not token.startswith("-") or len(token) <= 1:
            positionals.append(token)
            i += 1
            continue

        if not _FLAG_RE.match(token):
            return False

        has_equals = "=" in token
        if has_equals:
            eq_idx = token.index("=")
            flag = token[:eq_idx]
            inline_value = token[eq_idx + 1 :]
        else:
            flag = token
            inline_value = ""

        arg_type = config.safe_flags.get(flag)

        if arg_type is None:
            if base_cmd == "git" and _GIT_NUMERIC_SHORTHAND.match(flag):
                i += 1
                continue

            if flag.startswith("-") and not flag.startswith("--") and len(flag) > 2:
                if not _validate_short_flag_bundle(flag, config):
                    return False
                for ch in flag[1:]:
                    seen_flags.add(f"-{ch}")
                i += 1
                continue

            return False

        seen_flags.add(flag)

        if arg_type == FlagArgType.NONE:
            if has_equals:
                return False
            i += 1
        else:
            if has_equals:
                if not _validate_flag_value(inline_value, arg_type):
                    return False
                i += 1
            else:
                if i + 1 >= len(tokens):
                    return False
                next_token = tokens[i + 1]
                if (
                    next_token.startswith("-")
                    and len(next_token) > 1
                    and _FLAG_RE.match(next_token)
                    and not _is_numeric_value(next_token)
                ):
                    return False
                if not _validate_flag_value(next_token, arg_type):
                    return False
                i += 2

    return not (
        config.is_positional_dangerous is not None
        and config.is_positional_dangerous(positionals, frozenset(seen_flags))
    )


def _validate_short_flag_bundle(bundle: str, config: SubcommandConfig) -> bool:
    """Validate a bundled short-flag token like ``-abc``.

    All bundled characters must be known NONE-type safe flags. Arg-taking flags
    in bundles create parser differentials (GNU getopt consumes the next token),
    so they are rejected.
    """
    for ch in bundle[1:]:
        single = f"-{ch}"
        flag_type = config.safe_flags.get(single)
        if not flag_type:
            return False
        if flag_type != FlagArgType.NONE:
            return False
    return True


def _validate_flag_value(value: str, arg_type: FlagArgType) -> bool:
    """Validate a flag argument value against the expected type."""
    if arg_type == FlagArgType.NUMBER:
        return value.isdigit()
    return arg_type == FlagArgType.STRING


# ---------------------------------------------------------------------------
# Segment-level classification
# ---------------------------------------------------------------------------


def _classify_segment(segment: str) -> CommandRiskLevel:
    """Classify a single pipeline segment."""
    stripped = segment.strip()
    if not stripped:
        return CommandRiskLevel.UNKNOWN

    if _has_redirect(stripped):
        return CommandRiskLevel.UNKNOWN

    tokens = stripped.split()
    cmd_idx = 0
    for t in tokens:
        if "=" in t and not t.startswith("-"):
            cmd_idx += 1
        else:
            break

    if cmd_idx >= len(tokens):
        return CommandRiskLevel.UNKNOWN

    base = tokens[cmd_idx].rsplit("/", 1)[-1]
    if not base:
        return CommandRiskLevel.UNKNOWN

    subcmd_configs = SUBCOMMAND_CONFIGS.get(base)
    if subcmd_configs is not None:
        config, args_start = _resolve_subcommand(base, tokens, cmd_idx + 1, subcmd_configs)
        if config is None:
            return CommandRiskLevel.UNKNOWN
        if _validate_flags(tokens, args_start, config, base_cmd=base):
            return CommandRiskLevel.SAFE
        return CommandRiskLevel.UNKNOWN

    if base in SAFE_COMMANDS:
        return CommandRiskLevel.SAFE

    return CommandRiskLevel.UNKNOWN


def _split_shell_operators(command: str) -> list[str]:
    """Split a command string on unquoted shell operators (``|``, ``&&``, ``||``).

    Quote-aware: operators inside single or double quotes are ignored.
    Backslash escapes inside double quotes are respected.

    Each returned segment is a single command that the shell would execute
    independently. All three operator types are treated equally for safety
    classification: every segment must be SAFE for the whole command to be SAFE.
    """
    segments: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command)

    while i < n:
        ch = command[i]

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
        elif ch == "\\" and in_double and i + 1 < n:
            current.append(ch)
            current.append(command[i + 1])
            i += 2
        elif not in_single and not in_double:
            if (ch == "&" and i + 1 < n and command[i + 1] == "&") or (ch == "|" and i + 1 < n and command[i + 1] == "|"):
                segments.append("".join(current))
                current = []
                i += 2
            elif ch == "|":
                segments.append("".join(current))
                current = []
                i += 1
            else:
                current.append(ch)
                i += 1
        else:
            current.append(ch)
            i += 1

    segments.append("".join(current))
    return segments


def classify_command_risk(command: str) -> CommandRiskLevel:
    """Classify a shell command's risk level.

    A command is SAFE only when **every** segment is classified SAFE.
    Segments are split on shell operators ``|``, ``&&``, ``||`` with
    quote-awareness (operators inside quotes are not treated as separators).

    Per-segment checks:
    - Simple commands: base command must be in ``SAFE_COMMANDS``.
    - Subcommand tools (e.g. git): subcommand must have a config entry and
      all flags must pass the flag-level whitelist validation.
    - No I/O redirection operators (``>``, ``<``, ``>>``) in any segment.

    Commands containing shell metacharacters that survive upstream
    ``shell_command_analyzer`` checks (e.g. ``$``, `` ` ``, ``;``)
    are already blocked/escalated before reaching this function.
    """
    if not command or not command.strip():
        return CommandRiskLevel.UNKNOWN

    segments = _split_shell_operators(command)

    for segment in segments:
        if _classify_segment(segment) != CommandRiskLevel.SAFE:
            return CommandRiskLevel.UNKNOWN

    return CommandRiskLevel.SAFE
