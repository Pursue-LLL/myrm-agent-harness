"""Command tables behind the capability-boundary classification of ``ast_parser``.

[INPUT]
- (none)

[OUTPUT]
- SAFE_READONLY_COMMANDS: Commands that only read.
- SAFE_TEST_COMMANDS: Test, lint and build runners confined to the workspace.
- GIT_SAFE_READONLY_SUBCOMMANDS / GIT_MUTATION_SUBCOMMANDS: Git subcommands by effect.
- GIT_GLOBAL_OPTS_WITH_ARG: Git global options that consume the next word.
- CRITICAL_ESCALATION_COMMANDS: Commands that always need a human, with the reason code.
- SYSTEM_SENSITIVE_PREFIXES / PROTECTED_STARTUP_FILES: Redirect targets that escalate.

[POS]
Policy data of the capability gate. Pure data without logic.
"""

from __future__ import annotations

SAFE_READONLY_COMMANDS: frozenset[str] = frozenset(
    {
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
        "grep",
        "rg",
        "ag",
        "fd",
        "find",
        "fzf",
        "sort",
        "uniq",
        "diff",
        "comm",
        "cut",
        "tr",
        "echo",
        "printf",
        "uname",
        "arch",
        "id",
        "whoami",
        "groups",
        "uptime",
        "which",
        "where",
        "type",
        "command",
        "date",
        "cd",
        "env",
        "md5sum",
        "sha256sum",
        "hexdump",
        "strings",
    }
)

SAFE_TEST_COMMANDS: frozenset[str] = frozenset(
    {
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "cargo",
        "go",
        "bun",
        "npm",
        "yarn",
        "pnpm",
        "mypy",
        "pyright",
        "tsc",
        "ruff",
        "eslint",
        "biome",
        "flake8",
        "shellcheck",
        "black",
        "isort",
    }
)

GIT_SAFE_READONLY_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "branch",
        "tag",
        "describe",
        "rev-parse",
        "rev-list",
        "ls-files",
        "ls-tree",
        "ls-remote",
        "remote",
        "config",
        "version",
        "help",
    }
)

GIT_MUTATION_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "commit",
        "add",
        "stash",
        "restore",
        "switch",
        "fetch",
        "merge",
    }
)

GIT_GLOBAL_OPTS_WITH_ARG: frozenset[str] = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--super-prefix",
        "--exec-path",
    }
)

CRITICAL_ESCALATION_COMMANDS: dict[str, str] = {
    "curl": "network_egress",
    "wget": "network_egress",
    "nc": "network_egress",
    "netcat": "network_egress",
    "nmap": "network_egress",
    "ssh": "network_egress",
    "scp": "network_egress",
    "rsync": "network_egress",
    "telnet": "network_egress",
    "sudo": "privilege_escalation",
    "su": "privilege_escalation",
    "chown": "privilege_escalation",
    "chmod": "permission_alteration",
    "kill": "process_termination",
    "pkill": "process_termination",
    "killall": "process_termination",
    "reboot": "system_administration",
    "shutdown": "system_administration",
    "poweroff": "system_administration",
    "systemctl": "system_administration",
    "service": "system_administration",
    "mount": "system_administration",
    "umount": "system_administration",
}

SYSTEM_SENSITIVE_PREFIXES: tuple[str, ...] = (
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/opt",
    "/root",
    "/proc",
    "/sys",
    "/dev",
)
PROTECTED_STARTUP_FILES: frozenset[str] = frozenset(
    {".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile", "shadow", "passwd", "authorized_keys"}
)
