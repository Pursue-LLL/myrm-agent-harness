"""JavaScript ecosystem safe subcommand configurations (npm, yarn, bun, pnpm).

Read-only subcommands are unconditionally SAFE. Install/add subcommands
use ``is_positional_dangerous`` to distinguish between installing from
an existing lockfile (SAFE) vs adding new packages (UNKNOWN → ASK).
Run/test/build subcommands use ``_SAFE_SCRIPT_NAMES`` whitelist to
auto-allow common scripts while blocking arbitrary script names.

[INPUT]
- (none)

[OUTPUT]
- (none)

[POS]
JavaScript ecosystem safe subcommand configurations (npm, yarn, bun, pnpm).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import (
    FlagArgType,
    SubcommandConfig,
)


def _install_positional_dangerous(positionals: list[str], _seen: frozenset[str]) -> bool:
    """Block ``npm install <pkg>`` but allow bare ``npm install``."""
    return len(positionals) > 0


_SAFE_SCRIPT_NAMES: frozenset[str] = frozenset(
    {
        "test",
        "build",
        "lint",
        "start",
        "dev",
        "serve",
        "format",
        "typecheck",
        "check",
        "clean",
        "watch",
        "preview",
        "generate",
        "e2e",
        "unit",
        "coverage",
        "ci",
    }
)


def _run_positional_dangerous(positionals: list[str], _seen: frozenset[str]) -> bool:
    """Allow ``npm run test/build/lint/...`` but block arbitrary script names."""
    if not positionals:
        return True
    return positionals[0].lower() not in _SAFE_SCRIPT_NAMES


# ---------------------------------------------------------------------------
# npm
# ---------------------------------------------------------------------------

NPM_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "list": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--json": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "-p": FlagArgType.NONE,
            "--depth": FlagArgType.NUMBER,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--dev": FlagArgType.NONE,
            "--link": FlagArgType.NONE,
            "--unicode": FlagArgType.NONE,
            "--omit": FlagArgType.STRING,
        },
    ),
    "ls": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--json": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "-p": FlagArgType.NONE,
            "--depth": FlagArgType.NUMBER,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--dev": FlagArgType.NONE,
            "--link": FlagArgType.NONE,
            "--unicode": FlagArgType.NONE,
            "--omit": FlagArgType.STRING,
        },
    ),
    "outdated": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
            "-a": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--json": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "-p": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
        },
    ),
    "view": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
        },
    ),
    "info": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
    "show": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
    "explain": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
    "why": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
    "search": SubcommandConfig(
        safe_flags={
            "--long": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--json": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "-p": FlagArgType.NONE,
        },
    ),
    "audit": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--omit": FlagArgType.STRING,
            "--audit-level": FlagArgType.STRING,
        },
    ),
    "config list": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "-l": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
        },
    ),
    "config get": SubcommandConfig(
        safe_flags={
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
        },
    ),
    "install": SubcommandConfig(
        safe_flags={
            "--save-dev": FlagArgType.NONE,
            "-D": FlagArgType.NONE,
            "--save-exact": FlagArgType.NONE,
            "-E": FlagArgType.NONE,
            "--save-optional": FlagArgType.NONE,
            "-O": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "-g": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--legacy-peer-deps": FlagArgType.NONE,
            "--no-optional": FlagArgType.NONE,
            "--ignore-scripts": FlagArgType.NONE,
            "--no-audit": FlagArgType.NONE,
            "--no-fund": FlagArgType.NONE,
            "--prefer-offline": FlagArgType.NONE,
        },
        is_positional_dangerous=_install_positional_dangerous,
    ),
    "ci": SubcommandConfig(
        safe_flags={
            "--ignore-scripts": FlagArgType.NONE,
            "--no-audit": FlagArgType.NONE,
            "--no-fund": FlagArgType.NONE,
            "--prefer-offline": FlagArgType.NONE,
        },
    ),
    "run": SubcommandConfig(
        safe_flags={
            "--if-present": FlagArgType.NONE,
            "--silent": FlagArgType.NONE,
            "--ignore-scripts": FlagArgType.NONE,
        },
        is_positional_dangerous=_run_positional_dangerous,
    ),
    "test": SubcommandConfig(
        safe_flags={
            "--": FlagArgType.NONE,
        },
    ),
    "run-script": SubcommandConfig(
        safe_flags={
            "--if-present": FlagArgType.NONE,
            "--silent": FlagArgType.NONE,
        },
        is_positional_dangerous=_run_positional_dangerous,
    ),
}

# ---------------------------------------------------------------------------
# bun
# ---------------------------------------------------------------------------

BUN_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "pm ls": SubcommandConfig(
        safe_flags={
            "--all": FlagArgType.NONE,
        },
    ),
    "pm cache": SubcommandConfig(safe_flags={}),
    "pm hash": SubcommandConfig(safe_flags={}),
    "pm hash-string": SubcommandConfig(safe_flags={}),
    "install": SubcommandConfig(
        safe_flags={
            "--frozen-lockfile": FlagArgType.NONE,
            "--no-save": FlagArgType.NONE,
            "--dry-run": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--verbose": FlagArgType.NONE,
            "--ignore-scripts": FlagArgType.NONE,
        },
        is_positional_dangerous=_install_positional_dangerous,
    ),
    "test": SubcommandConfig(
        safe_flags={
            "--timeout": FlagArgType.NUMBER,
            "--bail": FlagArgType.NONE,
        },
    ),
    "outdated": SubcommandConfig(safe_flags={}),
    "run": SubcommandConfig(
        safe_flags={},
        is_positional_dangerous=_run_positional_dangerous,
    ),
}

# ---------------------------------------------------------------------------
# pnpm
# ---------------------------------------------------------------------------

PNPM_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "list": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "--depth": FlagArgType.NUMBER,
            "--dev": FlagArgType.NONE,
            "--prod": FlagArgType.NONE,
            "--no-optional": FlagArgType.NONE,
        },
    ),
    "ls": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "--depth": FlagArgType.NUMBER,
            "--dev": FlagArgType.NONE,
            "--prod": FlagArgType.NONE,
            "--no-optional": FlagArgType.NONE,
        },
    ),
    "outdated": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "--recursive": FlagArgType.NONE,
            "-r": FlagArgType.NONE,
        },
    ),
    "audit": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--dev": FlagArgType.NONE,
            "--no-optional": FlagArgType.NONE,
            "--audit-level": FlagArgType.STRING,
        },
    ),
    "why": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--long": FlagArgType.NONE,
            "--parseable": FlagArgType.NONE,
            "--global": FlagArgType.NONE,
            "--recursive": FlagArgType.NONE,
            "-r": FlagArgType.NONE,
        },
    ),
    "install": SubcommandConfig(
        safe_flags={
            "--frozen-lockfile": FlagArgType.NONE,
            "--prefer-offline": FlagArgType.NONE,
            "--no-optional": FlagArgType.NONE,
            "--prod": FlagArgType.NONE,
            "--dev": FlagArgType.NONE,
            "--ignore-scripts": FlagArgType.NONE,
        },
        is_positional_dangerous=_install_positional_dangerous,
    ),
    "run": SubcommandConfig(
        safe_flags={
            "--recursive": FlagArgType.NONE,
            "-r": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
        },
        is_positional_dangerous=_run_positional_dangerous,
    ),
    "test": SubcommandConfig(
        safe_flags={
            "--recursive": FlagArgType.NONE,
            "-r": FlagArgType.NONE,
            "--filter": FlagArgType.STRING,
        },
    ),
}

# ---------------------------------------------------------------------------
# yarn
# ---------------------------------------------------------------------------

YARN_SAFE_SUBCOMMANDS: dict[str, SubcommandConfig] = {
    "install": SubcommandConfig(
        safe_flags={
            "--frozen-lockfile": FlagArgType.NONE,
            "--immutable": FlagArgType.NONE,
            "--check-files": FlagArgType.NONE,
            "--production": FlagArgType.NONE,
            "--ignore-scripts": FlagArgType.NONE,
            "--no-lockfile": FlagArgType.NONE,
            "--prefer-offline": FlagArgType.NONE,
            "--silent": FlagArgType.NONE,
            "--non-interactive": FlagArgType.NONE,
        },
        is_positional_dangerous=_install_positional_dangerous,
    ),
    "list": SubcommandConfig(
        safe_flags={
            "--depth": FlagArgType.NUMBER,
            "--json": FlagArgType.NONE,
            "--pattern": FlagArgType.STRING,
        },
    ),
    "info": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
    "why": SubcommandConfig(safe_flags={}),
    "outdated": SubcommandConfig(safe_flags={}),
    "audit": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
            "--level": FlagArgType.STRING,
            "--groups": FlagArgType.STRING,
        },
    ),
    "run": SubcommandConfig(
        safe_flags={
            "--silent": FlagArgType.NONE,
        },
        is_positional_dangerous=_run_positional_dangerous,
    ),
    "test": SubcommandConfig(safe_flags={}),
    "build": SubcommandConfig(safe_flags={}),
    "workspaces info": SubcommandConfig(
        safe_flags={
            "--json": FlagArgType.NONE,
        },
    ),
}
