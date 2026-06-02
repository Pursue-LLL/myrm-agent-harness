"""Go ecosystem safe subcommand configurations.

Includes read-only subcommands and workspace-safe build/test operations.
Go tools operate within the module's directory and do not modify system state.

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Go ecosystem safe subcommand configurations.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)

_GO_COMMON_FLAGS: dict[str, FlagArgType] = {
    "-v": FlagArgType.NONE,
    "-x": FlagArgType.NONE,
    "-race": FlagArgType.NONE,
    "-count": FlagArgType.NUMBER,
    "-timeout": FlagArgType.STRING,
    "-tags": FlagArgType.STRING,
    "-ldflags": FlagArgType.STRING,
    "-gcflags": FlagArgType.STRING,
    "-p": FlagArgType.NUMBER,
    "-json": FlagArgType.NONE,
    "-trimpath": FlagArgType.NONE,
    "-work": FlagArgType.NONE,
}

GO_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "build": SubcommandConfig(
        safe_flags={
            **_GO_COMMON_FLAGS,
            "-o": FlagArgType.STRING,
            "-mod": FlagArgType.STRING,
            "-modfile": FlagArgType.STRING,
        },
    ),
    "test": SubcommandConfig(
        safe_flags={
            **_GO_COMMON_FLAGS,
            "-run": FlagArgType.STRING,
            "-bench": FlagArgType.STRING,
            "-benchmem": FlagArgType.NONE,
            "-benchtime": FlagArgType.STRING,
            "-cover": FlagArgType.NONE,
            "-covermode": FlagArgType.STRING,
            "-coverprofile": FlagArgType.STRING,
            "-cpuprofile": FlagArgType.STRING,
            "-memprofile": FlagArgType.STRING,
            "-short": FlagArgType.NONE,
            "-failfast": FlagArgType.NONE,
            "-parallel": FlagArgType.NUMBER,
            "-mod": FlagArgType.STRING,
        },
    ),
    "vet": SubcommandConfig(
        safe_flags={
            "-v": FlagArgType.NONE,
            "-json": FlagArgType.NONE,
            "-tags": FlagArgType.STRING,
            "-mod": FlagArgType.STRING,
        },
    ),
    "fmt": SubcommandConfig(
        safe_flags={
            "-n": FlagArgType.NONE,
            "-x": FlagArgType.NONE,
            "-mod": FlagArgType.STRING,
        },
    ),
    "mod tidy": SubcommandConfig(
        safe_flags={
            "-v": FlagArgType.NONE,
            "-go": FlagArgType.STRING,
            "-compat": FlagArgType.STRING,
        },
    ),
    "mod download": SubcommandConfig(
        safe_flags={
            "-json": FlagArgType.NONE,
            "-x": FlagArgType.NONE,
        },
    ),
    "mod verify": SubcommandConfig(safe_flags={}),
    "mod graph": SubcommandConfig(
        safe_flags={
            "-go": FlagArgType.STRING,
        },
    ),
    "mod why": SubcommandConfig(
        safe_flags={
            "-m": FlagArgType.NONE,
            "-vendor": FlagArgType.NONE,
        },
    ),
    "list": SubcommandConfig(
        safe_flags={
            "-m": FlagArgType.NONE,
            "-json": FlagArgType.NONE,
            "-u": FlagArgType.NONE,
            "-f": FlagArgType.STRING,
            "-mod": FlagArgType.STRING,
            "-versions": FlagArgType.NONE,
        },
    ),
    "version": SubcommandConfig(
        safe_flags={
            "-m": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
    ),
    "env": SubcommandConfig(
        safe_flags={
            "-json": FlagArgType.NONE,
        },
    ),
    "doc": SubcommandConfig(
        safe_flags={
            "-all": FlagArgType.NONE,
            "-c": FlagArgType.NONE,
            "-cmd": FlagArgType.NONE,
            "-short": FlagArgType.NONE,
            "-src": FlagArgType.NONE,
            "-u": FlagArgType.NONE,
        },
    ),
    "clean": SubcommandConfig(
        safe_flags={
            "-cache": FlagArgType.NONE,
            "-testcache": FlagArgType.NONE,
            "-n": FlagArgType.NONE,
            "-x": FlagArgType.NONE,
        },
    ),
}
