"""Lightweight Bash AST Semantic Parser and Capability Boundary Classifier.

Parses shell commands into structured atomic actions and classifies their
security capability boundary (safe readonly/test vs capability escalation vs
irreversible destructive hard stop line).

[INPUT]
- command: Shell command string.
- workspace_path: Optional path to current workspace for boundary checks.

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

from myrm_agent_harness.toolkits.code_execution.security.destructive_rules import (
    analyze_destructive_action,
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
    chain_operator: str | None
    capability_level: CapabilityLevel
    escalation_reason: str | None
    raw_tokens: tuple[str, ...]


# ---------------------------------------------------------------------------
# Whitelists and Blacklists for Capability Classification
# ---------------------------------------------------------------------------

SAFE_READONLY_COMMANDS: frozenset[str] = frozenset({
    "ls", "dir", "cat", "head", "tail", "less", "more", "file", "wc", "du", "df", "stat",
    "tree", "realpath", "basename", "dirname", "readlink", "pwd", "grep", "rg", "ag", "fd",
    "fzf", "sort", "uniq", "diff", "comm", "cut", "tr", "echo", "printf", "uname", "arch",
    "id", "whoami", "groups", "uptime", "which", "where", "type", "command", "date", "cd",
    "env", "md5sum", "sha256sum", "hexdump", "strings",
})

SAFE_TEST_COMMANDS: frozenset[str] = frozenset({
    "pytest", "jest", "vitest", "mocha", "cargo", "go", "bun", "npm", "yarn", "pnpm",
    "mypy", "pyright", "tsc", "ruff", "eslint", "biome", "flake8", "shellcheck", "black", "isort",
})

_GIT_SAFE_READONLY_SUBCOMMANDS: frozenset[str] = frozenset({
    "status", "log", "diff", "show", "branch", "tag", "describe", "rev-parse", "rev-list",
    "ls-files", "ls-tree", "ls-remote", "remote", "config", "version", "help",
})

_GIT_MUTATION_SUBCOMMANDS: frozenset[str] = frozenset({
    "commit", "add", "stash", "restore", "switch", "fetch", "merge",
})

_GIT_GLOBAL_OPTS_WITH_ARG: frozenset[str] = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path",
})

CRITICAL_ESCALATION_COMMANDS: dict[str, str] = {
    "curl": "network_egress", "wget": "network_egress", "nc": "network_egress",
    "netcat": "network_egress", "nmap": "network_egress", "ssh": "network_egress",
    "scp": "network_egress", "rsync": "network_egress", "telnet": "network_egress",
    "sudo": "privilege_escalation", "su": "privilege_escalation",
    "chown": "privilege_escalation", "chmod": "permission_alteration",
    "kill": "process_termination", "pkill": "process_termination",
    "killall": "process_termination", "reboot": "system_administration",
    "shutdown": "system_administration", "poweroff": "system_administration",
    "systemctl": "system_administration", "service": "system_administration",
    "mount": "system_administration", "umount": "system_administration",
}

_SYSTEM_SENSITIVE_PREFIXES: tuple[str, ...] = ("/etc", "/usr", "/bin", "/sbin", "/var", "/opt", "/root", "/proc", "/sys", "/dev")
_PROTECTED_STARTUP_FILES: frozenset[str] = frozenset({".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile", "shadow", "passwd", "authorized_keys"})

_CHAIN_OPERATORS: frozenset[str] = frozenset({";", "&&", "||", "|", "&"})
_REDIRECT_OPERATORS: frozenset[str] = frozenset(
    {">", ">>", "<", ">&", "<&", "&>", "2>", "2>>", "1>", "1>>"}
)


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
        """Parse a compound shell command into individual atomic actions with capability classifications."""
        stripped = command.strip()
        if not stripped:
            return []

        tokens = cls._tokenize(stripped)
        if not tokens:
            return []

        statements = cls._split_into_statements(tokens)
        actions: list[AtomicCommandAction] = []

        for statement_tokens, chain_op in statements:
            if not statement_tokens:
                continue
            actions.append(cls._parse_single_statement(statement_tokens, chain_op, workspace_path))

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
            a for a in actions
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

    @classmethod
    def _tokenize(cls, command: str) -> list[str]:
        """Tokenize shell command with quote and operator awareness."""
        lexer = shlex.shlex(io.StringIO(command), posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens: list[str] = []
        try:
            for tok in lexer:
                tokens.append(tok)
        except ValueError:
            return command.split()
        return tokens

    @classmethod
    def _split_into_statements(
        cls,
        tokens: list[str],
    ) -> list[tuple[list[str], str | None]]:
        """Split token stream on chain operators (;, &&, ||, |, &)."""
        statements: list[tuple[list[str], str | None]] = []
        current_tokens: list[str] = []

        for tok in tokens:
            if tok in _CHAIN_OPERATORS:
                statements.append((current_tokens, tok))
                current_tokens = []
            else:
                current_tokens.append(tok)

        if current_tokens:
            statements.append((current_tokens, None))

        return statements

    @classmethod
    def _parse_single_statement(
        cls,
        tokens: list[str],
        chain_op: str | None,
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
            words.append(tok)
            i += 1

        cmd_words: list[str] = []
        for w in words:
            if not cmd_words and "=" in w and not w.startswith("-"):
                continue
            cmd_words.append(w)

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
            chain_operator=chain_op,
            capability_level=cap_level,
            escalation_reason=reason,
            raw_tokens=tuple(tokens),
        )

    @staticmethod
    def _extract_git_subcommand(args: tuple[str, ...]) -> str | None:
        """Extract the actual git subcommand, skipping global flags and flag arguments."""
        i = 0
        n = len(args)
        while i < n:
            arg = args[i]
            if arg in _GIT_GLOBAL_OPTS_WITH_ARG:
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
        if not base_cmd:
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
            for prefix in _SYSTEM_SENSITIVE_PREFIXES:
                if target_norm == prefix or target_norm.startswith(prefix + "/"):
                    return CapabilityLevel.CAPABILITY_ESCALATION, "system_file_write"
            base_name = os.path.basename(target_norm)
            if base_name in _PROTECTED_STARTUP_FILES:
                return CapabilityLevel.CAPABILITY_ESCALATION, "system_file_write"

        # 5. Git fine-grained subcommand boundary
        if base_cmd == "git":
            subcmd = cls._extract_git_subcommand(args)
            if not subcmd or subcmd in _GIT_SAFE_READONLY_SUBCOMMANDS:
                if any(r.operator in (">", ">>", "&>") for r in redirections):
                    return CapabilityLevel.WORKSPACE_MUTATION, None
                return CapabilityLevel.SAFE_READONLY, None
            if subcmd in _GIT_MUTATION_SUBCOMMANDS:
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
