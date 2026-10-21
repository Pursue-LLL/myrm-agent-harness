"""Filesystem tool safe configurations.

Uses empty-string key ("") for flat commands (no subcommand) to enable
flag-level validation via the standard _resolve_subcommand mechanism.

find: auto-allows read-only search predicates (-name, -type, -size, etc.)
and blocks execution/deletion predicates (-exec, -execdir, -delete, -ok).

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Filesystem tool safe configurations.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)

FIND_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "": SubcommandConfig(
        safe_flags={
            "-name": FlagArgType.STRING,
            "-iname": FlagArgType.STRING,
            "-path": FlagArgType.STRING,
            "-ipath": FlagArgType.STRING,
            "-regex": FlagArgType.STRING,
            "-iregex": FlagArgType.STRING,
            "-type": FlagArgType.STRING,
            "-size": FlagArgType.STRING,
            "-maxdepth": FlagArgType.NUMBER,
            "-mindepth": FlagArgType.NUMBER,
            "-mtime": FlagArgType.STRING,
            "-mmin": FlagArgType.STRING,
            "-ctime": FlagArgType.STRING,
            "-cmin": FlagArgType.STRING,
            "-atime": FlagArgType.STRING,
            "-amin": FlagArgType.STRING,
            "-newer": FlagArgType.STRING,
            "-newermt": FlagArgType.STRING,
            "-user": FlagArgType.STRING,
            "-group": FlagArgType.STRING,
            "-perm": FlagArgType.STRING,
            "-print": FlagArgType.NONE,
            "-print0": FlagArgType.NONE,
            "-ls": FlagArgType.NONE,
            "-empty": FlagArgType.NONE,
            "-readable": FlagArgType.NONE,
            "-writable": FlagArgType.NONE,
            "-executable": FlagArgType.NONE,
            "-not": FlagArgType.NONE,
            "-or": FlagArgType.NONE,
            "-and": FlagArgType.NONE,
            "-o": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "-follow": FlagArgType.NONE,
            "-mount": FlagArgType.NONE,
            "-xdev": FlagArgType.NONE,
            "-depth": FlagArgType.NONE,
            "-daystart": FlagArgType.NONE,
            "-true": FlagArgType.NONE,
            "-false": FlagArgType.NONE,
        },
    ),
}
