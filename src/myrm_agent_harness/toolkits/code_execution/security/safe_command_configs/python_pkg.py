"""Python ecosystem safe subcommand configurations (pip, uv).

Read-only subcommands are unconditionally SAFE. Install subcommands
use ``is_positional_dangerous`` to allow lockfile-based installs while
requiring confirmation for new package additions.

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
Python ecosystem safe subcommand configurations (pip, uv).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)


def _pip_install_positional_dangerous(positionals: list[str], seen_flags: frozenset[str]) -> bool:
    """Allow ``pip install -r requirements.txt`` but block ``pip install <pkg>``."""
    if "-r" in seen_flags or "--requirement" in seen_flags:
        return False
    return len(positionals) > 0


# ---------------------------------------------------------------------------
# pip
# ---------------------------------------------------------------------------

PIP_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "list": SubcommandConfig(
        safe_flags={
            "--outdated": FlagArgType.NONE,
            "-o": FlagArgType.NONE,
            "--uptodate": FlagArgType.NONE,
            "-u": FlagArgType.NONE,
            "--editable": FlagArgType.NONE,
            "-e": FlagArgType.NONE,
            "--local": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--not-required": FlagArgType.NONE,
            "--pre": FlagArgType.NONE,
            "--format": FlagArgType.STRING,
            "--path": FlagArgType.STRING,
            "--exclude-editable": FlagArgType.NONE,
            "--include-editable": FlagArgType.NONE,
            "--exclude": FlagArgType.STRING,
        },
    ),
    "show": SubcommandConfig(
        safe_flags={
            "--files": FlagArgType.NONE,
            "-f": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
    ),
    "freeze": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "--local": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--exclude-editable": FlagArgType.NONE,
            "--exclude": FlagArgType.STRING,
            "--path": FlagArgType.STRING,
        },
    ),
    "check": SubcommandConfig(safe_flags={}),
    "config list": SubcommandConfig(
        safe_flags={
            "--global": FlagArgType.NONE,
            "--user": FlagArgType.NONE,
            "--site": FlagArgType.NONE,
        },
    ),
    "config get": SubcommandConfig(
        safe_flags={
            "--global": FlagArgType.NONE,
            "--user": FlagArgType.NONE,
            "--site": FlagArgType.NONE,
        },
    ),
    "cache list": SubcommandConfig(safe_flags={}),
    "cache info": SubcommandConfig(safe_flags={}),
    "install": SubcommandConfig(
        safe_flags={
            "-r": FlagArgType.STRING,
            "--requirement": FlagArgType.STRING,
            "--upgrade": FlagArgType.NONE,
            "-U": FlagArgType.NONE,
            "--no-deps": FlagArgType.NONE,
            "--pre": FlagArgType.NONE,
            "--user": FlagArgType.NONE,
            "--target": FlagArgType.STRING,
            "-t": FlagArgType.STRING,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
        is_positional_dangerous=_pip_install_positional_dangerous,
    ),
}

# ---------------------------------------------------------------------------
# uv
# ---------------------------------------------------------------------------

UV_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "pip list": SubcommandConfig(
        safe_flags={
            "--format": FlagArgType.STRING,
            "--editable": FlagArgType.NONE,
            "--exclude-editable": FlagArgType.NONE,
            "--strict": FlagArgType.NONE,
        },
    ),
    "pip show": SubcommandConfig(
        safe_flags={
            "--files": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
        },
    ),
    "pip freeze": SubcommandConfig(
        safe_flags={
            "--strict": FlagArgType.NONE,
            "--exclude-editable": FlagArgType.NONE,
        },
    ),
    "pip check": SubcommandConfig(safe_flags={}),
    "pip tree": SubcommandConfig(
        safe_flags={
            "--depth": FlagArgType.NUMBER,
            "--invert": FlagArgType.NONE,
            "--strict": FlagArgType.NONE,
        },
    ),
    "cache list": SubcommandConfig(safe_flags={}),
    "cache info": SubcommandConfig(safe_flags={}),
    "version": SubcommandConfig(safe_flags={}),
    "sync": SubcommandConfig(
        safe_flags={
            "--frozen": FlagArgType.NONE,
            "--locked": FlagArgType.NONE,
            "--no-install-project": FlagArgType.NONE,
            "--all-extras": FlagArgType.NONE,
            "--extra": FlagArgType.STRING,
            "--no-dev": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
    ),
    "lock": SubcommandConfig(
        safe_flags={
            "--frozen": FlagArgType.NONE,
            "--check": FlagArgType.NONE,
            "--quiet": FlagArgType.NONE,
            "-q": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
            "-v": FlagArgType.NONE,
        },
    ),
}
