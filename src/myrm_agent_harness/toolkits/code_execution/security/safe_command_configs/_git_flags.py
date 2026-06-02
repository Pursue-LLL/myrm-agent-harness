"""Git shared flag groups and positional-arg danger callbacks.

Reusable flag dictionaries shared across git subcommand configs.

[INPUT]
- (none)

[OUTPUT]
- reflog_positional_dangerous: Block `git reflog expire/delete/exists` — only `show` and...
- tag_positional_dangerous: Block `git tag <name>` (creation) unless -l/--list was seen.
- branch_positional_dangerous: Block `git branch <name>` (creation) unless --list/-l was...
- remote_positional_dangerous: Block bare positionals after `git remote` — only -v/--ver...
- remote_show_positional_dangerous: Allow exactly one alphanumeric remote name after `git rem...

[POS]
Git shared flag groups and positional-arg danger callbacks.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.code_execution.security.safe_command_configs.types import FlagArgType

# ---------------------------------------------------------------------------
# Shared flag groups (reused across subcommands)
# ---------------------------------------------------------------------------

REF_SELECTION: dict[str, FlagArgType] = {
    "--all": FlagArgType.NONE,
    "--branches": FlagArgType.NONE,
    "--tags": FlagArgType.NONE,
    "--remotes": FlagArgType.NONE,
}

DATE_FILTER: dict[str, FlagArgType] = {
    "--since": FlagArgType.STRING,
    "--after": FlagArgType.STRING,
    "--until": FlagArgType.STRING,
    "--before": FlagArgType.STRING,
}

LOG_DISPLAY: dict[str, FlagArgType] = {
    "--oneline": FlagArgType.NONE,
    "--graph": FlagArgType.NONE,
    "--decorate": FlagArgType.NONE,
    "--no-decorate": FlagArgType.NONE,
    "--date": FlagArgType.STRING,
    "--relative-date": FlagArgType.NONE,
}

COUNT: dict[str, FlagArgType] = {
    "--max-count": FlagArgType.NUMBER,
    "-n": FlagArgType.NUMBER,
}

STAT: dict[str, FlagArgType] = {
    "--stat": FlagArgType.NONE,
    "--numstat": FlagArgType.NONE,
    "--shortstat": FlagArgType.NONE,
    "--name-only": FlagArgType.NONE,
    "--name-status": FlagArgType.NONE,
}

COLOR: dict[str, FlagArgType] = {
    "--color": FlagArgType.NONE,
    "--no-color": FlagArgType.NONE,
}

PATCH: dict[str, FlagArgType] = {
    "--patch": FlagArgType.NONE,
    "-p": FlagArgType.NONE,
    "--no-patch": FlagArgType.NONE,
    "--no-ext-diff": FlagArgType.NONE,
    "-s": FlagArgType.NONE,
}

AUTHOR_FILTER: dict[str, FlagArgType] = {
    "--author": FlagArgType.STRING,
    "--committer": FlagArgType.STRING,
    "--grep": FlagArgType.STRING,
}


# ---------------------------------------------------------------------------
# Positional-arg danger callbacks
# ---------------------------------------------------------------------------


def reflog_positional_dangerous(positionals: list[str], _seen: frozenset[str]) -> bool:
    """Block `git reflog expire/delete/exists` — only `show` and ref names are safe."""
    _dangerous_subs = {"expire", "delete", "exists"}
    for token in positionals:
        return token in _dangerous_subs
    return False


def tag_positional_dangerous(positionals: list[str], seen_flags: frozenset[str]) -> bool:
    """Block `git tag <name>` (creation) unless -l/--list was seen."""
    if not positionals:
        return False
    return not ("-l" in seen_flags or "--list" in seen_flags)


def branch_positional_dangerous(positionals: list[str], seen_flags: frozenset[str]) -> bool:
    """Block `git branch <name>` (creation) unless --list/-l was seen."""
    if not positionals:
        return False
    if "-l" in seen_flags or "--list" in seen_flags:
        return False
    if "--contains" in seen_flags or "--no-contains" in seen_flags:
        return False
    if "--merged" in seen_flags or "--no-merged" in seen_flags:
        return False
    if "--points-at" in seen_flags:
        return False
    return "--show-current" not in seen_flags


def remote_positional_dangerous(positionals: list[str], _seen: frozenset[str]) -> bool:
    """Block bare positionals after `git remote` — only -v/--verbose is safe."""
    return len(positionals) > 0


def remote_show_positional_dangerous(positionals: list[str], _seen: frozenset[str]) -> bool:
    """Allow exactly one alphanumeric remote name after `git remote show`."""
    if len(positionals) != 1:
        return len(positionals) > 1
    return not all(c.isalnum() or c in "-_" for c in positionals[0])
