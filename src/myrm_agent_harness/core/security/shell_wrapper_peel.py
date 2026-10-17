"""The prefixes a shell accepts in front of a command, read through for deny, ask and destructive verdicts.

A rule written for ``rm -rf /`` has to fire on ``timeout 30 rm -rf /``, ``sudo rm -rf /``,
``env FOO=1 rm -rf /`` and ``bash -c 'rm -rf /'``: wrapping a command does not change what runs. This module
is that reading. It owns both wrapper tables so they cannot drift apart:

- ``TRANSPARENT_WRAPPERS`` (``command``, ``time``, ``timeout``) and ``unwrap_transparent_wrapper`` are read in
  *both* directions, since they run the command after them and nothing else;
- ``peel_deny_wrapper`` reads the prefixes that only the deny, ask and destructive directions may look
  through. Letting those widen an allow rule is precisely how a deny rule gets lifted: ``timeout 30 *`` would
  vouch for ``timeout 30 rm -rf /``, and ``sudo *`` for ``sudo rm -rf /``.

[INPUT]
- The resolved words of one command (``core.security.shell_command_lexer.shell_words``), or its raw text.

[OUTPUT]
- TRANSPARENT_WRAPPERS / unwrap_transparent_wrapper: the allow-direction reading of ``command``, ``time``, ``timeout``.
- peel_deny_wrapper: the words the deny-direction prefix in front of a command hands control to.
- shell_script_of: the script text a shell ``-c`` form or ``eval`` runs as its own command line.
- substitution_bodies: the command text inside each ``$(...)`` and backtick the shell would run.
- nested_command_readings: every command a prefix, a ``-c`` script or a substitution hands control to.
- deny_readings: the same, for a whole string, with transparant wrappers read through as well.
- DENY_WRAPPER_DEPTH: recursion bound for callers that re-enter on a nested script.

[POS]
Shared reading of shell prefixes, the single home of the transparent-wrapper table. Pure functions over
``shell_command_lexer``, so ``agent/`` and ``toolkits/`` read a command identically without importing each
other.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from myrm_agent_harness.core.security.shell_command_lexer import (
    shell_words,
    split_command_spans,
)

# A prefix chain deeper than this is not read further: the bound keeps a pathological line from recursing
# without end while covering every nesting a real command line has.
DENY_WRAPPER_DEPTH: Final = 8

_ASSIGNMENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh"})

# Commands whose only job is to run the command they are given; they are read through in both directions.
TRANSPARENT_WRAPPERS: Final[frozenset[str]] = frozenset({"command", "time", "timeout"})

_DURATION: Final = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_TIMEOUT_VALUE_FLAGS: Final = frozenset({"-k", "-s"})
_TIMEOUT_PLAIN_FLAGS: Final = frozenset({"-f", "-p", "-v", "--foreground", "--preserve-status", "--verbose"})
_TIMEOUT_ATTACHED_FLAGS: Final = ("--signal=", "--kill-after=")


def unwrap_transparent_wrapper(base: str, args: Sequence[str]) -> list[str] | None:
    """Return the words of the command the wrapper *base* runs.

    ``[]`` means it runs nothing (``command -v git``, a bare ``time``); None means the form is not understood
    (an option that is not listed, a missing duration) and the caller must not vouch for it.
    """
    if base == "timeout":
        return _unwrap_timeout(args)
    rest = list(args)
    if base == "command" and rest[:1] in (["-v"], ["-V"]):
        return []
    if rest[:1] == ["-p"]:
        rest = rest[1:]
    if rest[:1] == ["--"]:
        rest = rest[1:]
    return None if rest and rest[0].startswith("-") else rest


def _unwrap_timeout(args: Sequence[str]) -> list[str] | None:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        flag = args[index]
        if flag in _TIMEOUT_VALUE_FLAGS:
            index += 2
        elif flag in _TIMEOUT_PLAIN_FLAGS or flag.startswith(_TIMEOUT_ATTACHED_FLAGS):
            index += 1
        else:
            return None
    if index >= len(args) or not _DURATION.fullmatch(args[index]):
        return None
    return list(args[index + 1 :])


@dataclass(frozen=True, slots=True)
class _Prefix:
    """How one prefix swallows the words in front of the command it hands control to."""

    # A flag whose value is glued to it (``-o0``, ``--user=me``). Matching requires the token to be longer
    # than the prefix, so ``-o`` alone falls through to ``skips_next``.
    attached: tuple[str, ...] = ()
    # A flag whose value is the word after it.
    skips_next: frozenset[str] = frozenset()
    # A flag after which the prefix runs no command at all (``sudo -v``).
    stops: frozenset[str] = frozenset()
    # Same as ``stops``, for a flag carrying its value glued on (``ionice -p123``).
    stops_glued: tuple[str, ...] = ()


_PREFIXES: Final[Mapping[str, _Prefix]] = MappingProxyType(
    {
        "sudo": _Prefix(
            attached=(
                "-u",
                "-g",
                "-p",
                "-C",
                "-r",
                "-t",
                "-U",
                "-T",
                "-R",
                "--user=",
                "--group=",
                "--prompt=",
                "--close-from=",
                "--chroot=",
                "--host=",
                "--role=",
                "--type=",
                "--other-user=",
                "--command-timeout=",
            ),
            skips_next=frozenset(
                {
                    "-u",
                    "-g",
                    "-p",
                    "-C",
                    "-r",
                    "-t",
                    "-U",
                    "-T",
                    "-R",
                    "--user",
                    "--group",
                    "--prompt",
                    "--close-from",
                    "--chroot",
                    "--host",
                    "--role",
                    "--type",
                    "--other-user",
                    "--command-timeout",
                }
            ),
            stops=frozenset(
                {"-v", "-k", "-l", "-V", "-h", "--validate", "--reset-timestamp", "--list", "--version", "--help"}
            ),
        ),
        "doas": _Prefix(
            attached=("-u",),
            skips_next=frozenset({"-u", "-C"}),
            stops=frozenset({"-V", "-h", "--version", "--help"}),
        ),
        "nohup": _Prefix(stops=frozenset({"--help", "--version"})),
        "nice": _Prefix(
            attached=("-n",),
            skips_next=frozenset({"-n", "--adjustment"}),
            stops=frozenset({"--help", "--version"}),
        ),
        "env": _Prefix(
            attached=("--unset=", "--chdir=", "--split-string="),
            skips_next=frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
            stops=frozenset({"--help", "--version"}),
        ),
        "setsid": _Prefix(stops=frozenset({"--help", "--version"})),
        "stdbuf": _Prefix(
            attached=("-i", "-o", "-e", "--input=", "--output=", "--error="),
            skips_next=frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}),
            stops=frozenset({"--help", "--version"}),
        ),
        "ionice": _Prefix(
            attached=("-c", "-n", "--class=", "--classdata="),
            skips_next=frozenset({"-c", "-n", "--class", "--classdata"}),
            stops=frozenset({"-p", "-P", "--help", "--version"}),
            stops_glued=("-p", "-P"),
        ),
        "xargs": _Prefix(
            attached=("-I", "-i", "-L", "-l", "-n", "-P", "-s", "-d", "-E", "-a"),
            skips_next=frozenset(
                {
                    "-I",
                    "-i",
                    "-L",
                    "-l",
                    "-n",
                    "-P",
                    "-s",
                    "-d",
                    "-E",
                    "-a",
                    "--arg-file",
                    "--delimiter",
                    "--eof",
                    "--replace",
                    "--max-lines",
                    "--max-args",
                    "--max-procs",
                    "--max-chars",
                }
            ),
            stops=frozenset({"--help", "--version"}),
        ),
        "watch": _Prefix(
            attached=("-n",),
            skips_next=frozenset({"-n", "--interval"}),
            stops=frozenset({"-h", "--help", "-v", "--version"}),
        ),
    }
)

# Every word that can stand in front of the command that really runs, for callers that want a cheap check
# before doing the full reading.
PRECEDING_WORDS: Final[frozenset[str]] = frozenset(_PREFIXES) | _SHELLS | {"eval"}


def _strip_assignments(words: Sequence[str]) -> list[str]:
    """Drop the leading ``NAME=value`` words a prefix leaves in front of its command (``env FOO=1 rm``)."""
    index = 0
    while index < len(words) and _ASSIGNMENT_RE.match(words[index]):
        index += 1
    return list(words[index:])


def _after_prefix(args: Sequence[str], prefix: _Prefix) -> list[str] | None:
    """The words a prefix's own flags leave behind, or None when the prefix runs no command."""
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            return list(args[index + 1 :])
        if not token.startswith("-") or token == "-":
            return list(args[index:])
        if any(token.startswith(glued) for glued in prefix.stops_glued):
            return None
        if any(len(token) > len(glued) and token.startswith(glued) for glued in prefix.attached):
            index += 1
            continue
        if token in prefix.skips_next:
            index += 2
            continue
        if token in prefix.stops:
            return None
        index += 1
    return []


def peel_deny_wrapper(words: Sequence[str]) -> list[str] | None:
    """The words the deny-direction prefix in *words* hands control to.

    ``[]`` means the prefix runs no command (``env -0``, a bare ``sudo``). None means the command is already
    read as written: no prefix, no leading assignment, or a form that is not understood. Leading
    ``NAME=value`` words are read through as well, since ``A=1 rm -rf /`` runs ``rm -rf /``.
    """
    rest = _strip_assignments(words)
    if not rest:
        return None
    prefix = _PREFIXES.get(rest[0].rsplit("/", 1)[-1])
    if prefix is None:
        return rest if len(rest) != len(words) else None
    after = _after_prefix(rest[1:], prefix)
    return None if after is None else _strip_assignments(after)


def shell_script_of(words: Sequence[str]) -> str | None:
    """The script text a shell ``-c`` form or ``eval`` runs as its own command line.

    None means *words* is not such a form, or names a script file whose text this layer cannot read. A shell
    that gets no ``-c`` reads a file or a standard input stream, and ``eval`` joins its arguments, so the
    returned text is what the shell itself would parse next.
    """
    rest = _strip_assignments(words)
    if not rest:
        return None
    base = rest[0].rsplit("/", 1)[-1]
    args = list(rest[1:])
    if base == "eval":
        while args and args[0] == "--":
            args = args[1:]
        return " ".join(args) if args else None
    if base not in _SHELLS:
        return None
    for index, token in enumerate(args):
        if token == "--" or not token.startswith("-") or token == "-":
            return None
        if token.startswith("--"):
            continue
        if "c" in token[1:]:
            return args[index + 1] if index + 1 < len(args) else None
    return None


def substitution_bodies(text: str) -> list[str]:
    """The command text inside each ``$(...)`` and backtick substitution the shell would run.

    Text the shell does not expand is not read: a single-quoted ``$(`` is literal. The scan is deliberately
    approximate about quoting inside the substitution body, which can only make a caller look at more text.
    """
    bodies: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "'":
            closing = text.find("'", index + 1)
            index = length if closing < 0 else closing + 1
            continue
        if char == "$" and text[index + 1 : index + 2] == "(":
            closing = _matching_paren(text, index + 1)
            if closing < 0:
                break
            bodies.append(text[index + 2 : closing])
            index = closing + 1
            continue
        if char == "`":
            closing = _next_backtick(text, index + 1)
            if closing < 0:
                break
            bodies.append(text[index + 1 : closing])
            index = closing + 1
            continue
        index += 1
    return bodies


def _matching_paren(text: str, open_index: int) -> int:
    """Index of the ``)`` closing the ``(`` at *open_index*, or -1 when it never closes."""
    depth = 0
    index = open_index
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "'":
            closing = text.find("'", index + 1)
            if closing < 0:
                return -1
            index = closing + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _next_backtick(text: str, start: int) -> int:
    """Index of the backtick closing a substitution opened before *start*, or -1 when it never closes."""
    index = start
    length = len(text)
    while index < length:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            return index
        index += 1
    return -1


def nested_command_readings(command: str) -> Iterator[str]:
    """Yield the text of every command *command* hands control to, at any depth.

    The outer command is not yielded: it is the caller's own reading. What is yielded is the command behind a
    prefix (``sudo ls`` → ``ls``), the script a shell ``-c`` or ``eval`` parses next, and the body of every
    ``$(...)`` and backtick. Each is a command line in its own right and is expanded in turn, so a prefix
    inside a substitution is read the same way.
    """
    for text in _children(command):
        yield text
        yield from nested_command_readings(text)


def deny_readings(command: str) -> tuple[str, ...]:
    """The command lines to judge alongside *command* itself, one reading deep and no deeper.

    A line such as ``sudo kubectl delete ns prod`` is read as ``kubectl delete ns prod`` (and, for a wrapped
    read, whatever that command runs), which is what a deny list or a ruleset pattern has to see. The command
    itself is not repeated, so callers can judge it first and still match on any of these.
    """
    outer = command.strip()
    return tuple(text for text in dict.fromkeys(nested_command_readings(outer)) if text and text != outer)


def _children(command: str) -> Iterator[str]:
    """The commands one step below *command*: a peeled prefix, a shell script, and each substitution body."""
    for start, end in split_command_spans(command):
        part = command[start:end]
        yield from substitution_bodies(part)
        words = shell_words(part)
        if not words:
            continue
        script = shell_script_of(words)
        if script is not None:
            yield script
        peeled = peel_deny_wrapper(words)
        if peeled is None:
            peeled = _peel_transparent_deny(words)
        if peeled:
            yield " ".join(peeled)


def _peel_transparent_deny(words: Sequence[str]) -> list[str] | None:
    """The words behind ``command`` / ``time`` / ``timeout``, or None when the form is not understood."""
    rest = _strip_assignments(words)
    if not rest:
        return None
    base = rest[0].rsplit("/", 1)[-1]
    if base not in TRANSPARENT_WRAPPERS:
        return None
    inner = unwrap_transparent_wrapper(base, rest[1:])
    return inner if inner else None
