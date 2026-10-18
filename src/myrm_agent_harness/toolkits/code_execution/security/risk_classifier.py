"""Command risk classifier for approval auto-allow decisions.

Classifies a shell command line into SAFE (read-only / informational, auto-allow)
or UNKNOWN (requires human confirmation).

Designed as the **final fallback** in ``engine.evaluate_tool_call()``:
only invoked when all prior security layers (capability fence, threat analysis,
URL/domain checks, path policy, user ruleset) yield a default ASK.

Safety guarantees:
1. Read the way the shell reads it — every command of the line (separated by ``;`` ``|`` ``||`` ``&``
   ``&&`` or a line break; quotes, escapes and comments respected) is judged on its own, and each must be SAFE.
2. Judge the command that really runs — ``time``, ``timeout`` and ``command`` are SAFE only when the
   command they wrap is, and quotes are resolved first so ``rg "--pre"`` is the flag ``--pre``.
3. Redirect-aware — any I/O redirect (``>``, ``<``, ``>>``) → UNKNOWN.
4. Conservative inclusion — only pure read-only commands are classified SAFE; arguments that make one run a
   program or write a file (``rg --pre``, ``sort -o``) → UNKNOWN, and so is a flag list that ``$``, a backtick
   or brace expansion keeps from being read as text.
5. Flag-level validation — commands with subcommand configs (e.g. git) are validated at the flag
   granularity: unknown flags → UNKNOWN.

[INPUT]
- core.security.shell_command_lexer: Command boundaries, shell words and expansion detection.
- safe_commands: Allow-list, wrapper unwrapping and argument guards.
- safe_command_configs: Per-subcommand flag whitelists.

[OUTPUT]
- CommandRiskLevel: Risk classification for a shell command.
- SpanRiskReason: Stable i18n reason code for a pipeline segment.
- classify_command_risk: Classify a shell command line's risk level.
- classify_segment_risk_detail: Level + reason code of one command.

[POS]
Command risk classifier for approval auto-allow decisions.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from myrm_agent_harness.core.security.shell_command_lexer import (
    has_word_expansion,
    shell_words,
    split_command_spans,
)
from myrm_agent_harness.core.security.shell_wrapper_peel import (
    DENY_WRAPPER_DEPTH,
    substitution_bodies,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs import (
    SUBCOMMAND_CONFIGS,
    FlagArgType,
    SubcommandConfig,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_commands import (
    SAFE_COMMANDS,
    TRANSPARENT_WRAPPERS,
    has_unsafe_arguments,
    is_guarded,
    unwrap_transparent_wrapper,
)

SpanRiskReason = Literal[
    "safe",
    "empty_segment",
    "redirect",
    "unknown_command",
    "unknown_subcommand",
    "invalid_flags",
]


class CommandRiskLevel(StrEnum):
    """Risk classification for a shell command."""

    SAFE = "safe"
    UNKNOWN = "unknown"


type _Verdict = tuple[CommandRiskLevel, SpanRiskReason]


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
# Command-level classification
# ---------------------------------------------------------------------------

_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
# ``time time time ls`` is valid shell; the bound keeps a long chain from recursing without limit.
_MAX_WRAPPER_DEPTH = 4


def _classify_command(words: list[str], *, expands: bool, depth: int) -> _Verdict:
    """Judge the command that *words* run.

    *expands* tells whether ``$``, a backtick or ``{`` in the source text can rewrite the words at run time,
    which makes any flag or subcommand check on them meaningless.
    """
    base = words[0].rsplit("/", 1)[-1] if words else ""
    if not base:
        return CommandRiskLevel.UNKNOWN, "unknown_command"

    if base in TRANSPARENT_WRAPPERS:
        inner = unwrap_transparent_wrapper(base, words[1:])
        if inner is None or depth >= _MAX_WRAPPER_DEPTH:
            return CommandRiskLevel.UNKNOWN, "unknown_command"
        if not inner:
            return CommandRiskLevel.SAFE, "safe"
        return _classify_command(inner, expands=expands, depth=depth + 1)

    subcmd_configs = SUBCOMMAND_CONFIGS.get(base)
    if subcmd_configs is not None:
        if expands:
            return CommandRiskLevel.UNKNOWN, "invalid_flags"
        config, args_start = _resolve_subcommand(base, words, 1, subcmd_configs)
        if config is None:
            return CommandRiskLevel.UNKNOWN, "unknown_subcommand"
        if _validate_flags(words, args_start, config, base_cmd=base):
            return CommandRiskLevel.SAFE, "safe"
        return CommandRiskLevel.UNKNOWN, "invalid_flags"

    if base in SAFE_COMMANDS:
        if has_unsafe_arguments(base, words[1:]) or (expands and is_guarded(base)):
            return CommandRiskLevel.UNKNOWN, "invalid_flags"
        return CommandRiskLevel.SAFE, "safe"

    return CommandRiskLevel.UNKNOWN, "unknown_command"


def _classify_segment(segment: str) -> _Verdict:
    """Classify one command, as separated by ``split_command_spans``."""
    text = segment.strip()
    if not text:
        return CommandRiskLevel.UNKNOWN, "empty_segment"

    if _has_redirect(text):
        return CommandRiskLevel.UNKNOWN, "redirect"

    words = shell_words(text)
    if words is None:
        return CommandRiskLevel.UNKNOWN, "unknown_command"

    # Leading ``NAME=value`` words only set variables for the command that follows. After a wrapper the same
    # word would be the program to run, so assignments are skipped here and nowhere else.
    start = 0
    while start < len(words) and _ASSIGNMENT_RE.match(words[start]):
        start += 1
    return _classify_command(words[start:], expands=has_word_expansion(text), depth=0)


def classify_segment_risk_detail(segment: str) -> tuple[CommandRiskLevel, SpanRiskReason]:
    """Classify a single command with a stable i18n reason code.

    Text that holds more than one command is never vouched for: callers split a command line with
    ``split_command_spans`` first.
    """
    if len(split_command_spans(segment)) > 1:
        return CommandRiskLevel.UNKNOWN, "unknown_command"
    return _classify_segment(segment)


def classify_command_risk(command: str) -> CommandRiskLevel:
    """Classify a shell command line's risk level.

    The line is SAFE only when **every** command in it is SAFE. Commands are separated the way the shell
    separates them: ``;``, ``|``, ``||``, ``|&``, ``&``, ``&&`` and line breaks, outside quotes, escapes
    and comments. An operator without a command on one side, or text that cannot be parsed (an unclosed
    quote), is UNKNOWN.

    Per-command checks:
    - Simple commands: the command that runs must be in ``SAFE_COMMANDS``, and none of its arguments may run
      a program or write a file (``rg --pre``, ``sort -o``).
    - ``time`` / ``timeout`` / ``command``: the wrapped command is judged instead.
    - Subcommand tools (e.g. git): the subcommand must have a config entry and all flags must pass the
      flag-level whitelist; ``$``, a backtick or brace expansion in the line makes the flags unreadable → UNKNOWN.
    - Command substitution: the command each ``$(...)`` and backtick runs is judged the same way, so
      ``echo $(curl ...)`` is UNKNOWN because ``curl`` is, not SAFE because ``echo`` is. Arithmetic expansion
      (``$((...))``) runs no command and is not read as one. A substitution tree nested past
      ``DENY_WRAPPER_DEPTH`` is UNKNOWN: a line the walk cannot finish reading is not vouched for.
    - No I/O redirection operators (``>``, ``<``, ``>>``).
    """
    return _classify_line(command, depth=0)


def _classify_line(command: str, depth: int) -> CommandRiskLevel:
    """Judge one command line and every command its substitutions run, ``depth`` levels down."""
    if depth >= DENY_WRAPPER_DEPTH:
        return CommandRiskLevel.UNKNOWN

    spans = split_command_spans(command)
    if not spans:
        return CommandRiskLevel.UNKNOWN

    for start, end in spans:
        level, _ = _classify_segment(command[start:end])
        if level != CommandRiskLevel.SAFE:
            return CommandRiskLevel.UNKNOWN

    for body in substitution_bodies(command):
        if _classify_line(body, depth + 1) != CommandRiskLevel.SAFE:
            return CommandRiskLevel.UNKNOWN

    return CommandRiskLevel.SAFE
