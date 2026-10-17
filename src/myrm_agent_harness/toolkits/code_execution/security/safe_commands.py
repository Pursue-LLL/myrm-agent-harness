"""Which commands the approval layer treats as read-only, and which arguments or wrappers revoke that.

SAFE is decided by the command that really runs, not by its first word: ``timeout 30 rm -rf x`` runs ``rm`` and
``rg --pre ./x`` makes a read-only search execute a program.

[INPUT]
- The shell words of one command (quotes and escapes already resolved by ``shell_command_lexer``)

[OUTPUT]
- SAFE_COMMANDS: Names of commands that need no approval unless a guarded argument is present.
- TRANSPARENT_WRAPPERS: Commands that only run another command (``command``, ``time``, ``timeout``); re-exported
  from ``core.security.shell_wrapper_peel``, their one home.
- unwrap_transparent_wrapper: The words of the command a wrapper runs, ``[]`` when it runs nothing, None when the form is not understood.
- is_guarded: Whether a SAFE command has arguments that can run a program or write a file.
- has_unsafe_arguments: Whether such an argument is present.

[POS]
Allow-list data and argument guards of the shell risk classifier. Pure data and functions without I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from myrm_agent_harness.core.security.shell_wrapper_peel import (
    TRANSPARENT_WRAPPERS as _TRANSPARENT_WRAPPERS,
)
from myrm_agent_harness.core.security.shell_wrapper_peel import (
    unwrap_transparent_wrapper as _unwrap_transparent_wrapper,
)

SAFE_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        # Filesystem read-only
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
        # Search / filter / text-processing read-only
        "grep",
        "rg",
        "ag",
        "fd",
        "fzf",
        "sort",
        "uniq",
        "diff",
        "comm",
        "cut",
        "tr",
        "fmt",
        "fold",
        "nl",
        "paste",
        "join",
        "column",
        "expand",
        "unexpand",
        "rev",
        "tac",
        # Simple output
        "echo",
        "printf",
        "true",
        "false",
        "yes",
        # System info read-only
        "uname",
        "arch",
        "id",
        "whoami",
        "groups",
        "uptime",
        "nproc",
        "lscpu",
        "lsb_release",
        "sw_vers",
        "which",
        "where",
        "type",
        "locale",
        # Terminal / misc safe
        "cd",
        "clear",
        "reset",
        "tput",
        # Checksum read-only
        "md5sum",
        "sha256sum",
        "sha1sum",
        "shasum",
        "cksum",
        "b2sum",
        # Binary inspection read-only
        "od",
        "hexdump",
        "strings",
        # Test runners (workspace-scoped, read-only analysis)
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "phpunit",
        # Linters / type checkers (read-only static analysis)
        "eslint",
        "ruff",
        "mypy",
        "pyright",
        "tsc",
        "biome",
        "flake8",
        "pylint",
        "black",
        "isort",
        "prettier",
        "stylelint",
        "shellcheck",
        # Build tools (workspace-scoped compilation)
        "make",
        "cmake",
        "gradle",
        "mvn",
        "ant",
        # Version managers (read-only unless asked to run something)
        "nvm",
        "rbenv",
        "pyenv",
        "fnm",
        "volta",
        # Misc development tools (read-only or workspace-safe only)
        "jq",
        "yq",
        "envsubst",
        "date",
        "cal",
        "bc",
        "expr",
        "seq",
        "sleep",
        "touch",
        "mkdir",
        "locate",
        "pbcopy",
        "pbpaste",
    }
)

# Commands whose only job is to run the command they are given; they are SAFE only if that command is.
# The table and its unwrapping live in ``core.security.shell_wrapper_peel``, their one home, together with the
# deny-direction reading, so the two directions cannot drift apart.
TRANSPARENT_WRAPPERS: Final[frozenset[str]] = _TRANSPARENT_WRAPPERS


def unwrap_transparent_wrapper(base: str, args: Sequence[str]) -> list[str] | None:
    """Return the words of the command the wrapper *base* runs.

    ``[]`` means it runs nothing (``command -v git``, a bare ``time``); None means the form is not understood
    (an option that is not listed, a missing duration) and the caller must not vouch for it.
    """
    return _unwrap_transparent_wrapper(base, args)


@dataclass(frozen=True, slots=True)
class _Guard:
    """Arguments that turn a read-only tool into one that runs a program or writes a file."""

    # Without the leading ``--``. A GNU tool accepts any unambiguous prefix of a long option, so ``--out`` counts
    # as ``--output``; the guard flags every prefix, which also covers the ambiguous ones.
    long_flags: frozenset[str] = frozenset()
    # Single characters, matched anywhere in a short-option bundle (``-nosorted`` is ``-n -o sorted``).
    short_flags: frozenset[str] = frozenset()
    # Operands that make the tool run something (``pyenv exec``).
    words: frozenset[str] = frozenset()
    # More operands than this means the last one is written to (``uniq INPUT OUTPUT``).
    max_operands: int | None = None

    def matches(self, args: Sequence[str]) -> bool:
        """True when *args* contain a guarded flag, a guarded word, or too many operands."""
        operands = 0
        options_ended = False
        for arg in args:
            if options_ended or arg == "-" or not arg.startswith("-"):
                if arg in self.words:
                    return True
                operands += 1
            elif arg == "--":
                options_ended = True
            elif arg.startswith("--"):
                name = arg[2:].split("=", 1)[0]
                if any(flag.startswith(name) for flag in self.long_flags):
                    return True
            elif any(char in self.short_flags for char in arg[1:]):
                return True
        return self.max_operands is not None and operands > self.max_operands


_RUNS_COMMANDS: Final = _Guard(words=frozenset({"exec", "run"}))

_GUARDS: Final[Mapping[str, _Guard]] = MappingProxyType(
    {
        # Flags that run a program
        "rg": _Guard(long_flags=frozenset({"pre", "hostname-bin"})),
        "fd": _Guard(long_flags=frozenset({"exec", "exec-batch"}), short_flags=frozenset("xX")),
        "ag": _Guard(long_flags=frozenset({"pager"})),
        "fzf": _Guard(
            long_flags=frozenset({"bind", "preview", "with-shell", "listen", "listen-unsafe", "history"}),
        ),
        # Flags and operands that write a file
        "sort": _Guard(long_flags=frozenset({"output", "compress-program"}), short_flags=frozenset("o")),
        "uniq": _Guard(max_operands=1),
        "tree": _Guard(short_flags=frozenset("o")),
        "yq": _Guard(long_flags=frozenset({"inplace", "in-place"}), short_flags=frozenset("i")),
        # Version managers run any command through ``exec`` / ``run``
        "nvm": _RUNS_COMMANDS,
        "rbenv": _RUNS_COMMANDS,
        "pyenv": _RUNS_COMMANDS,
        "fnm": _RUNS_COMMANDS,
        "volta": _RUNS_COMMANDS,
    }
)


def is_guarded(base: str) -> bool:
    """True when *base* is a SAFE command whose arguments decide whether it stays read-only."""
    return base in _GUARDS


def has_unsafe_arguments(base: str, args: Sequence[str]) -> bool:
    """True when *args* make the SAFE command *base* run a program or write a file."""
    guard = _GUARDS.get(base)
    return guard is not None and guard.matches(args)
