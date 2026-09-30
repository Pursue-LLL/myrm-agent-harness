"""Command safety validator enforcing strict read-only execution on remote hosts.

[INPUT]
- str: raw shell command to validate

[OUTPUT]
- ReadOnlySSHValidator: AST-aware and lexical analyzer for fail-closed read-only validation
- ValidationResult: Dataclass containing safety status, violation reason, and problematic snippet

[POS]
Security gate component in ssh_remote toolkit.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ValidationResult:
    """Result of command safety and read-only validation."""

    is_safe: bool
    reason: str = ""
    violation_snippet: str = ""


# Read-only primary command names allowed by default
_READ_ONLY_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        # Text and file display
        "cat",
        "head",
        "tail",
        "more",
        "less",
        "grep",
        "egrep",
        "fgrep",
        "awk",
        "sed",
        "cut",
        "tr",
        "sort",
        "uniq",
        "wc",
        "diff",
        "cmp",
        "comm",
        "column",
        "paste",
        "fold",
        "nl",
        "pr",
        "od",
        "hexdump",
        "xxd",
        "strings",
        "file",
        "stat",
        "ls",
        "dir",
        "vdir",
        "find",
        "which",
        "whereis",
        "type",
        "locate",
        # System and hardware telemetry
        "du",
        "df",
        "free",
        "vmstat",
        "iostat",
        "mpstat",
        "top",
        "htop",
        "ps",
        "pgrep",
        "pstree",
        "pidof",
        "uptime",
        "dmesg",
        "journalctl",
        "uname",
        "hostname",
        "id",
        "whoami",
        "who",
        "w",
        "last",
        "lastlog",
        "env",
        "printenv",
        "echo",
        "printf",
        "date",
        "cal",
        "lsblk",
        "blkid",
        "lscpu",
        "lsmem",
        "lspci",
        "lsusb",
        "dmidecode",
        "nvidia-smi",
        "rocm-smi",
        # Network state inspection
        "netstat",
        "ss",
        "lsof",
        "ping",
        "traceroute",
        "tracepath",
        "dig",
        "nslookup",
        "host",
        # Checksums and archive inspection
        "md5sum",
        "sha1sum",
        "sha256sum",
        "sha512sum",
        "base64",
        "zcat",
        "zgrep",
        "zless",
        "bzcat",
        "xzcat",
        "zipinfo",
        # Monitored multi-subcommand utilities
        "systemctl",
        "service",
        "docker",
        "kubectl",
        "sysctl",
        "ip",
        "ifconfig",
        "tar",
        "unzip",
        "curl",
        "wget",
        "git",
    }
)

# Subcommand restrictions for dual-use tools
_ALLOWED_SUBCOMMANDS: Final[dict[str, frozenset[str]]] = {
    "systemctl": frozenset(
        {
            "status",
            "is-active",
            "is-failed",
            "is-enabled",
            "list-units",
            "list-unit-files",
            "cat",
            "show",
            "help",
        }
    ),
    "service": frozenset({"status"}),
    "docker": frozenset(
        {
            "ps",
            "logs",
            "inspect",
            "images",
            "stats",
            "top",
            "version",
            "info",
            "diff",
        }
    ),
    "kubectl": frozenset(
        {
            "get",
            "describe",
            "logs",
            "explain",
            "top",
            "cluster-info",
            "version",
            "diff",
        }
    ),
    "git": frozenset(
        {
            "status",
            "log",
            "diff",
            "show",
            "branch",
            "tag",
            "rev-parse",
        }
    ),
}

# Dangerous write pipelines that accept piped input to modify state
_DANGEROUS_PIPE_TARGETS: Final[frozenset[str]] = frozenset(
    {
        "tee",
        "dd",
        "sh",
        "bash",
        "zsh",
        "ksh",
        "csh",
        "sudo",
        "su",
        "doas",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
        "rm",
        "mv",
        "cp",
    }
)

# Redirection operators indicating write/append
_WRITE_REDIRECTION_OPS: Final[frozenset[str]] = frozenset(
    {
        ">",
        ">>",
        ">|",
        "<>",
        ">&",
        "1>",
        "2>",
        "1>>",
        "2>>",
        "&>",
    }
)

# Command substitution patterns: $(...) and `...`
_COMMAND_SUBST_DOLLAR: Final[re.Pattern[str]] = re.compile(r"\$\((.+?)\)")
_COMMAND_SUBST_BACKTICK: Final[re.Pattern[str]] = re.compile(r"`(.+?)`")


class ReadOnlySSHValidator:
    """Validates remote SSH commands using lexical AST splitting and fail-closed policies."""

    def __init__(
        self,
        allowed_commands: frozenset[str] | None = None,
        custom_destructive_patterns: Sequence[re.Pattern[str]] | None = None,
    ) -> None:
        self._allowed_commands = allowed_commands or _READ_ONLY_COMMANDS
        self._custom_destructive_patterns = custom_destructive_patterns or []

    def validate(self, command: str) -> ValidationResult:
        """Validate if the given command is safe and strictly read-only."""
        normalized = command.strip()
        if not normalized:
            return ValidationResult(is_safe=False, reason="Command is empty")

        for pattern in self._custom_destructive_patterns:
            if pattern.search(normalized):
                return ValidationResult(
                    is_safe=False,
                    reason=f"Matched destructive pattern: {pattern.pattern}",
                    violation_snippet=normalized,
                )

        # 1. Check nested substitutions: $(...) and `...`
        nested_error = self._validate_nested_substitutions(normalized)
        if nested_error:
            return nested_error

        # 2. Tokenize using shlex punctuation_chars to correctly preserve quoted strings
        try:
            lexer = shlex.shlex(normalized, punctuation_chars=True)
            lexer.whitespace_split = False
            tokens = list(lexer)
        except ValueError as err:
            return ValidationResult(
                is_safe=False,
                reason=f"Shell syntax lexical parse error: {err}",
                violation_snippet=normalized,
            )

        # 3. Parse token stream by pipelines and redirection operators
        return self._validate_tokens(tokens, normalized)

    def _validate_nested_substitutions(self, command: str) -> ValidationResult | None:
        """Extract and validate nested command substitutions."""
        dollar_matches = _COMMAND_SUBST_DOLLAR.findall(command)
        for sub_cmd in dollar_matches:
            sub_res = self.validate(sub_cmd)
            if not sub_res.is_safe:
                return ValidationResult(
                    is_safe=False,
                    reason=f"Nested substitution '$({sub_cmd})' blocked: {sub_res.reason}",
                    violation_snippet=f"$({sub_cmd})",
                )

        backtick_matches = _COMMAND_SUBST_BACKTICK.findall(command)
        for sub_cmd in backtick_matches:
            sub_res = self.validate(sub_cmd)
            if not sub_res.is_safe:
                return ValidationResult(
                    is_safe=False,
                    reason=f"Nested substitution '`{sub_cmd}`' blocked: {sub_res.reason}",
                    violation_snippet=f"`{sub_cmd}`",
                )
        return None

    def _validate_tokens(self, tokens: list[str], full_command: str) -> ValidationResult:
        """Analyze the token stream for redirection, dangerous pipes, and allowed commands."""
        stages: list[list[str]] = []
        current_stage: list[str] = []
        is_piped_flags: list[bool] = []
        was_pipe = False

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Redirection operator check
            if token in _WRITE_REDIRECTION_OPS or (token.endswith(">") and re.match(r"^\d*&?>{1,2}$", token)):
                target = tokens[i + 1] if i + 1 < len(tokens) else ""
                target_clean = target.strip("'\"")
                if target_clean != "/dev/null":
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Output redirection writing to '{target_clean}' is prohibited in read-only mode",
                        violation_snippet=f"{token} {target}",
                    )
                i += 2
                continue

            if token == "|":
                if current_stage:
                    stages.append(current_stage)
                    is_piped_flags.append(was_pipe)
                current_stage = []
                was_pipe = True
                i += 1
                continue

            if token in (";", "&&", "||", "&", "\n"):
                if current_stage:
                    stages.append(current_stage)
                    is_piped_flags.append(was_pipe)
                current_stage = []
                was_pipe = False
                i += 1
                continue

            current_stage.append(token)
            i += 1

        if current_stage:
            stages.append(current_stage)
            is_piped_flags.append(was_pipe)

        for stage_tokens, is_piped in zip(stages, is_piped_flags, strict=False):
            stage_res = self._validate_stage_tokens(stage_tokens, is_piped, full_command)
            if not stage_res.is_safe:
                return stage_res

        return ValidationResult(is_safe=True)

    def _validate_stage_tokens(self, tokens: list[str], is_piped_target: bool, full_command: str) -> ValidationResult:
        """Validate tokens for an individual command segment in a pipeline."""
        if not tokens:
            return ValidationResult(is_safe=True)

        # Strip quotes and leading env variables
        clean_tokens = [t.strip("'\"") if (t.startswith(("'", '"')) and t.endswith(("'", '"'))) else t for t in tokens]

        idx = 0
        while idx < len(clean_tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*", clean_tokens[idx]):
            idx += 1

        if idx >= len(clean_tokens):
            return ValidationResult(
                is_safe=False,
                reason="Command only contains environment variable assignment",
                violation_snippet=" ".join(tokens),
            )

        cmd_raw = clean_tokens[idx]
        cmd_name = cmd_raw.split("/")[-1]

        if is_piped_target and cmd_name in _DANGEROUS_PIPE_TARGETS:
            return ValidationResult(
                is_safe=False,
                reason=f"Piping into state-modifying target '{cmd_name}' is prohibited",
                violation_snippet=" ".join(tokens),
            )

        if cmd_name not in self._allowed_commands:
            return ValidationResult(
                is_safe=False,
                reason=f"Command '{cmd_name}' is not in the read-only whitelist",
                violation_snippet=" ".join(tokens),
            )

        args = clean_tokens[idx + 1 :]
        stage_str = " ".join(tokens)
        return self._validate_tool_args(cmd_name, args, stage_str)

    def _validate_tool_args(self, cmd_name: str, args: list[str], full_stage: str) -> ValidationResult:
        """Inspect command arguments for flags that perform destructive mutations."""
        if cmd_name == "sed":
            for arg in args:
                if arg == "-i" or arg.startswith("-i") or arg == "--in-place":
                    return ValidationResult(
                        is_safe=False,
                        reason="Option '-i' (in-place write) on 'sed' is prohibited in read-only mode",
                        violation_snippet=full_stage,
                    )
        elif cmd_name == "tar":
            for arg in args:
                if any(flag in arg for flag in ("-x", "-c", "-r", "-u", "-A", "--extract", "--create")):
                    return ValidationResult(
                        is_safe=False,
                        reason="Archive extraction or modification with 'tar' is prohibited in read-only mode",
                        violation_snippet=full_stage,
                    )
        elif cmd_name == "unzip":
            has_read_flag = any(f in args for f in ("-l", "-t", "-v", "-p"))
            if not has_read_flag:
                return ValidationResult(
                    is_safe=False,
                    reason="Extracting files with 'unzip' is prohibited in read-only mode",
                    violation_snippet=full_stage,
                )
        elif cmd_name in ("curl", "wget"):
            for arg in args:
                if arg in ("-O", "-o", "--output") or arg.startswith(("-o", "--output=")):
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Downloading files to disk with '{cmd_name}' is prohibited in read-only mode",
                        violation_snippet=full_stage,
                    )
        elif cmd_name == "sysctl":
            for arg in args:
                if "=" in arg or arg in ("-w", "--write"):
                    return ValidationResult(
                        is_safe=False,
                        reason="Modifying kernel parameters with 'sysctl' is prohibited in read-only mode",
                        violation_snippet=full_stage,
                    )
        elif cmd_name == "ip":
            if any(sub in args for sub in ("add", "del", "delete", "set", "flush", "change", "replace")):
                return ValidationResult(
                    is_safe=False,
                    reason="Modifying network configuration with 'ip' is prohibited in read-only mode",
                    violation_snippet=full_stage,
                )
        elif cmd_name == "service":
            # Syntax: service <service-name> <action>
            non_flags = [a for a in args if not a.startswith("-")]
            if len(non_flags) >= 2:
                action = non_flags[1]
                if action != "status":
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Action '{action}' for 'service' is not in the read-only whitelist (status)",
                        violation_snippet=full_stage,
                    )
            elif len(non_flags) == 1 and non_flags[0] not in ("--status-all", "status"):
                return ValidationResult(
                    is_safe=False,
                    reason="Incomplete service invocation or non-status action",
                    violation_snippet=full_stage,
                )
        elif cmd_name in _ALLOWED_SUBCOMMANDS:
            allowed_sub = _ALLOWED_SUBCOMMANDS[cmd_name]
            sub = next((a for a in args if not a.startswith("-")), None)
            if not sub or sub not in allowed_sub:
                return ValidationResult(
                    is_safe=False,
                    reason=f"Subcommand '{sub}' for '{cmd_name}' is not in the read-only whitelist ({', '.join(sorted(allowed_sub))})",
                    violation_snippet=full_stage,
                )

        return ValidationResult(is_safe=True)
