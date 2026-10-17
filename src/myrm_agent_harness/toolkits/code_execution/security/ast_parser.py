"""Lightweight Bash AST Semantic Parser and Capability Boundary Classifier.

Parses shell commands into structured atomic actions and classifies their
security capability boundary (safe readonly/test vs capability escalation vs
irreversible destructive hard stop line).

[INPUT]
- command: Shell command string, possibly several lines.
- workspace_path: Optional path to current workspace for boundary checks.
- core.security.shell_command_lexer: Where commands end and which text is a comment (same reading as the risk classifier).
- capability_tables: Command tables of the capability gate.

[OUTPUT]
- CapabilityLevel: Enum representing the security boundary level.
- Redirection: Struct capturing I/O redirection operator and target.
- AtomicCommandAction: Structured representation of a single atomic shell action.
- BashASTParser: Parser and classifier engine for Bash compound commands.

[POS]
Shell execution security: AST semantic parsing and capability boundary gating.
"""

from __future__ import annotations

import io
import os
import re
import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.core.security.shell_command_lexer import (
    split_command_spans,
    strip_comments,
)
from myrm_agent_harness.toolkits.code_execution.security.capability_tables import (
    CRITICAL_ESCALATION_COMMANDS,
    GIT_GLOBAL_OPTS_WITH_ARG,
    GIT_MUTATION_SUBCOMMANDS,
    GIT_SAFE_READONLY_SUBCOMMANDS,
    PROTECTED_STARTUP_FILES,
    SAFE_READONLY_COMMANDS,
    SAFE_TEST_COMMANDS,
    SYSTEM_SENSITIVE_PREFIXES,
)
from myrm_agent_harness.toolkits.code_execution.security.destructive_rules import (
    analyze_destructive_action,
)
from myrm_agent_harness.toolkits.code_execution.security.safe_commands import (
    TRANSPARENT_WRAPPERS,
    unwrap_transparent_wrapper,
)

# ---------------------------------------------------------------------------
# Capability Boundary Enums and Types
# ---------------------------------------------------------------------------


class CapabilityLevel(StrEnum):
    """Security capability boundary levels for shell actions."""

    SAFE_READONLY = "safe_readonly"
    SAFE_TEST = "safe_test"
    WORKSPACE_MUTATION = "workspace_mutation"
    CAPABILITY_ESCALATION = "capability_escalation"
    IRREVERSIBLE_DESTRUCTIVE = "irreversible_destructive"


@dataclass(frozen=True, slots=True)
class Redirection:
    """I/O redirection in a shell command."""

    operator: str
    target: str


@dataclass(frozen=True, slots=True)
class AtomicCommandAction:
    """A single atomic command action within a compound shell execution."""

    command_text: str
    base_cmd: str
    args: tuple[str, ...]
    redirections: tuple[Redirection, ...]
    capability_level: CapabilityLevel
    escalation_reason: str | None
    raw_tokens: tuple[str, ...]


_REDIRECT_OPERATORS: frozenset[str] = frozenset({">", ">>", "<", ">&", "<&", "&>", "2>", "2>>", "1>", "1>>"})


def _is_env_assignment(word: str) -> bool:
    """``NAME=value`` in front of a command sets a variable for it; the command is the word after the assignments."""
    return "=" in word and not word.startswith("-")


# ---------------------------------------------------------------------------
# AST Parser Engine
# ---------------------------------------------------------------------------


class BashASTParser:
    """Lightweight POSIX-compliant Bash syntax and capability boundary parser."""

    @classmethod
    def parse(
        cls,
        command: str,
        workspace_path: Path | None = None,
    ) -> list[AtomicCommandAction]:
        """Parse a compound shell command into individual atomic actions with capability classifications.

        Commands are cut where the shell cuts them (``split_command_spans``), so every command bash runs is seen
        and text it ignores (comments) is not.
        """
        stripped = command.strip()
        actions: list[AtomicCommandAction] = []
        for start, end in split_command_spans(stripped):
            for tokens in cls._tokenize(stripped[start:end]):
                if tokens:
                    actions.append(cls._parse_single_statement(tokens, workspace_path))
        return actions

    @classmethod
    def has_escalation(cls, actions: list[AtomicCommandAction]) -> bool:
        """Check if any atomic action requires capability escalation or destructive confirmation."""
        return any(
            a.capability_level in (CapabilityLevel.CAPABILITY_ESCALATION, CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE)
            for a in actions
        )

    @classmethod
    def has_destructive(cls, actions: list[AtomicCommandAction]) -> bool:
        """Check if any atomic action constitutes an irreversible destructive operation."""
        return any(a.capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE for a in actions)

    @classmethod
    def get_escalation_actions(cls, actions: list[AtomicCommandAction]) -> list[AtomicCommandAction]:
        """Filter actions that require explicit human approval (escalation or destructive)."""
        return [
            a
            for a in actions
            if a.capability_level in (CapabilityLevel.CAPABILITY_ESCALATION, CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE)
        ]

    @classmethod
    def summarize_escalations(cls, actions: list[AtomicCommandAction]) -> list[dict[str, str]]:
        """Generate structured metadata dicts for HITL approval UI."""
        summaries: list[dict[str, str]] = []
        for a in cls.get_escalation_actions(actions):
            summaries.append(
                {
                    "command": a.command_text,
                    "base_cmd": a.base_cmd,
                    "reason": a.escalation_reason or a.capability_level.value,
                    "details": " ".join(a.args[:4]),
                    "capability_level": a.capability_level.value,
                }
            )
        return summaries

    @staticmethod
    def _tokenize(command: str) -> list[list[str]]:
        """Split the text of one command into words and redirect tokens: one token list, or one per line.

        Comments are removed by the shell's own rule first: shlex would also end a word at a ``#`` inside it
        (``echo a#b && rm -rf x``). Text shlex cannot parse is an unclosed quote that swallows the lines after
        it, such as the apostrophe in a heredoc body or one inside backticks; bash may still run those lines, so
        each one is named by its own words instead of hiding behind the first.
        """
        text = strip_comments(command)
        lexer = shlex.shlex(io.StringIO(text), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            return [list(lexer)]
        except ValueError:
            return [line.split() for line in text.splitlines()]

    @classmethod
    def _parse_single_statement(
        cls,
        tokens: list[str],
        workspace_path: Path | None,
    ) -> AtomicCommandAction:
        """Parse words, flags, and redirections from a single statement's tokens."""
        words: list[str] = []
        redirections: list[Redirection] = []

        i = 0
        total = len(tokens)
        while i < total:
            tok = tokens[i]
            if tok in _REDIRECT_OPERATORS or re.match(r"^\d+>$", tok) or tok == "&>":
                target = tokens[i + 1] if i + 1 < total else ""
                redirections.append(Redirection(operator=tok, target=target))
                i += 2
                continue
            if (
                tok.isascii()
                and tok.isdigit()
                and i + 1 < total
                and tokens[i + 1] in _REDIRECT_OPERATORS
                and all(map(_is_env_assignment, words))
            ):
                # ``2>log rm -rf x``: shlex cuts the file descriptor off its operator, so in front of the command
                # a bare number belongs to the redirect that follows and is no command word.
                i += 1
                continue
            words.append(tok)
            i += 1

        cmd_words: list[str] = []
        for w in words:
            if not cmd_words and _is_env_assignment(w):
                continue
            cmd_words.append(w)
        cmd_words = cls._peel_wrappers(cmd_words)

        if not cmd_words:
            base_cmd = ""
            args: tuple[str, ...] = ()
        else:
            base_cmd = os.path.basename(cmd_words[0])
            args = tuple(cmd_words[1:])

        cap_level, reason = cls._classify_capability(
            base_cmd,
            args,
            tuple(redirections),
            workspace_path,
        )

        return AtomicCommandAction(
            command_text=" ".join(tokens),
            base_cmd=base_cmd,
            args=args,
            redirections=tuple(redirections),
            capability_level=cap_level,
            escalation_reason=reason,
            raw_tokens=tuple(tokens),
        )

    @staticmethod
    def _peel_wrappers(words: list[str]) -> list[str]:
        """Return the words of the command that really runs: ``time``, ``command`` and ``timeout`` only run what follows."""
        while words:
            base = os.path.basename(words[0])
            inner = unwrap_transparent_wrapper(base, words[1:]) if base in TRANSPARENT_WRAPPERS else None
            if not inner:  # not a wrapper, a form that is not understood, or a wrapper that runs nothing
                break
            words = inner
        return words

    @staticmethod
    def _extract_git_subcommand(args: tuple[str, ...]) -> str | None:
        """Extract the actual git subcommand, skipping global flags and flag arguments."""
        i = 0
        n = len(args)
        while i < n:
            arg = args[i]
            if arg in GIT_GLOBAL_OPTS_WITH_ARG:
                i += 2
                continue
            if arg.startswith("-"):
                i += 1
                continue
            return arg
        return None

    @classmethod
    def _classify_capability(
        cls,
        base_cmd: str,
        args: tuple[str, ...],
        redirections: tuple[Redirection, ...],
        workspace_path: Path | None,
    ) -> tuple[CapabilityLevel, str | None]:
        """Classify single atomic command against capability boundaries."""
        if not base_cmd and not redirections:
            return CapabilityLevel.SAFE_READONLY, None

        # 1. Hard Stop Line: Irreversible Destructive Actions
        redir_pairs = [(r.operator, r.target) for r in redirections]
        destructive_res = analyze_destructive_action(base_cmd, args, redir_pairs)
        if destructive_res.is_destructive:
            return CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE, destructive_res.reason

        # 2. Critical Escalation Commands (network egress, privilege, kill)
        if base_cmd in CRITICAL_ESCALATION_COMMANDS:
            return CapabilityLevel.CAPABILITY_ESCALATION, CRITICAL_ESCALATION_COMMANDS[base_cmd]

        # 3. Symlink creation boundary (ln -s / --symbolic)
        if base_cmd == "ln" and any(
            arg in ("-s", "-sf", "-sfn", "--symbolic") or (arg.startswith("-") and "s" in arg) for arg in args
        ):
            return CapabilityLevel.CAPABILITY_ESCALATION, "symlink_creation"

        # 4. Redirections targeting system/sensitive paths
        for redir in redirections:
            target = redir.target.strip()
            if not target:
                continue
            target_norm = os.path.normpath(os.path.expanduser(target))
            for prefix in SYSTEM_SENSITIVE_PREFIXES:
                if target_norm == prefix or target_norm.startswith(prefix + "/"):
                    return CapabilityLevel.CAPABILITY_ESCALATION, "system_file_write"
            base_name = os.path.basename(target_norm)
            if base_name in PROTECTED_STARTUP_FILES:
                return CapabilityLevel.CAPABILITY_ESCALATION, "system_file_write"

        # 5. Git fine-grained subcommand boundary
        if base_cmd == "git":
            subcmd = cls._extract_git_subcommand(args)
            if not subcmd or subcmd in GIT_SAFE_READONLY_SUBCOMMANDS:
                if any(r.operator in (">", ">>", "&>") for r in redirections):
                    return CapabilityLevel.WORKSPACE_MUTATION, None
                return CapabilityLevel.SAFE_READONLY, None
            if subcmd in GIT_MUTATION_SUBCOMMANDS:
                return CapabilityLevel.WORKSPACE_MUTATION, None
            reason = "git_remote_sync" if subcmd == "push" else (f"git_{subcmd}" if subcmd else "git_action")
            return CapabilityLevel.CAPABILITY_ESCALATION, reason

        # 6. Safe Read-Only commands
        if base_cmd in SAFE_READONLY_COMMANDS:
            if any(r.operator in (">", ">>", "&>") for r in redirections):
                return CapabilityLevel.WORKSPACE_MUTATION, None
            return CapabilityLevel.SAFE_READONLY, None

        # 7. Safe Test & Build commands
        if base_cmd in SAFE_TEST_COMMANDS:
            return CapabilityLevel.SAFE_TEST, None

        # 8. Default workspace mutation (touch, mkdir, cp, mv, python script, single-file rm, etc.)
        return CapabilityLevel.WORKSPACE_MUTATION, None


def classify_command_boundary(
    command: str,
    workspace_path: Path | None = None,
) -> list[AtomicCommandAction]:
    """Parse and classify command capability boundaries using BashASTParser."""
    return BashASTParser.parse(command, workspace_path)


def is_destructive_shell_tool_call(
    tool_name: str,
    args: dict[str, object] | None = None,
    workspace_path: Path | str | None = None,
) -> tuple[bool, str | None, dict[str, object] | None]:
    """Check if a tool call executes an irreversible destructive shell command."""
    if not args or not isinstance(args, dict):
        return False, None, None
    normalized_name = tool_name.lower().replace("-", "_")
    if any(k in normalized_name for k in ("bash", "shell", "terminal", "command_execute")):
        cmd = str(args.get("command", "") or args.get("code", "")).strip()
        if cmd:
            wpath = Path(workspace_path) if workspace_path else None
            actions = BashASTParser.parse(cmd, wpath)
            if BashASTParser.has_destructive(actions):
                destr_actions = [a for a in actions if a.capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE]
                first = destr_actions[0] if destr_actions else actions[0]
                return (
                    True,
                    first.escalation_reason,
                    {
                        "command": cmd,
                        "reason": first.escalation_reason,
                        "destructiveCount": len(destr_actions),
                    },
                )
    return False, None, None
