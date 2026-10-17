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
- TRANSPARENT_WRAPPERS / unwrap_transparent_wrapper: the allow-direction reading of ``command``, ``time``,
  ``timeout``.
- peel_deny_wrapper: the words the deny-direction prefix in front of a command hands control to.
- shell_script_of: the script text a shell ``-c`` form or ``eval`` runs as its own command line.
- substitution_bodies: the command text inside each ``$(...)`` and backtick the shell would run.
- direct_command_readings: the commands one line hands control to in one step — the command at the bottom of
  the prefix chain, a ``-c`` script or ``eval``, a substitution body. The chain is peeled with an index, so
  its length never hides the command it runs nor costs more than the text to read.
- deny_readings: every command a whole string hands control to, with prefix chains peeled to their bottom and
  only branching (substitutions, ``-c`` scripts) capped by ``DENY_WRAPPER_DEPTH`` / ``MAX_COMMAND_READINGS``.

[POS]
Shared reading of shell prefixes, the single home of the transparent-wrapper table. Pure functions over
``shell_command_lexer``, so ``agent/`` and ``toolkits/`` read a command identically without importing each
other.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from myrm_agent_harness.core.security.shell_command_lexer import (
    shell_words,
    split_command_spans,
)

# How many *branching* levels (a substitution or ``-c`` script nested inside one) the walk expands. A linear
# chain of prefixes does not spend this budget: it is peeled to the command at its bottom in one pass, so no
# number of ``sudo``/``timeout``/``time`` wrappers can hide the inner command from the deny or destructive
# direction. The bound stops a line built out of deeply nested substitutions from recursing without end, and
# sits well above any nesting a real command line has.
DENY_WRAPPER_DEPTH: Final = 64

# The most commands one line may expand to. A command whose every word is its own substitution is what makes
# this necessary: the readings branch at each level, so depth alone would still let a short line ask for a
# huge tree. The cap is far above any line a person or an agent writes, and past it the extra commands are
# simply not read (the command itself is still judged).
MAX_COMMAND_READINGS: Final = 256

_ASSIGNMENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS: Final = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "mksh"})

# Commands whose only job is to run the command they are given; they are read through in both directions.
TRANSPARENT_WRAPPERS: Final[frozenset[str]] = frozenset({"command", "time", "timeout"})

_DURATION: Final = re.compile(r"\d+(?:\.\d+)?[smhd]?")
_TIMEOUT_VALUE_FLAGS: Final = frozenset({"-k", "-s"})
_TIMEOUT_PLAIN_FLAGS: Final = frozenset({"-f", "-p", "-v", "--foreground", "--preserve-status", "--verbose"})
_TIMEOUT_ATTACHED_FLAGS: Final = ("--signal=", "--kill-after=")


def _transparent_inner(words: Sequence[str], start: int, base: str) -> int | None:
    """Index of the command transparent wrapper *base* runs, ``len(words)`` when it runs nothing.

    None means the form is not understood (an option that is not listed, a missing duration) and the caller
    must not vouch for it. An index rather than a slice is what keeps a chain of wrappers linear to read.
    """
    if base == "timeout":
        index = start
        while index < len(words) and words[index].startswith("-"):
            flag = words[index]
            if flag in _TIMEOUT_VALUE_FLAGS:
                index += 2
            elif flag in _TIMEOUT_PLAIN_FLAGS or flag.startswith(_TIMEOUT_ATTACHED_FLAGS):
                index += 1
            else:
                return None
        if index >= len(words) or not _DURATION.fullmatch(words[index]):
            return None
        return index + 1
    if base == "command" and words[start : start + 1] in (["-v"], ["-V"]):
        return len(words)
    index = start
    if words[index : index + 1] == ["-p"]:
        index += 1
    if words[index : index + 1] == ["--"]:
        index += 1
    return None if index < len(words) and words[index].startswith("-") else index


def unwrap_transparent_wrapper(base: str, args: Sequence[str]) -> list[str] | None:
    """Return the words of the command the wrapper *base* runs.

    ``[]`` means it runs nothing (``command -v git``, a bare ``time``); None means the form is not understood
    (an option that is not listed, a missing duration) and the caller must not vouch for it.
    """
    index = _transparent_inner(args, 0, base)
    return None if index is None else list(args[index:])


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


def _assignment_end(words: Sequence[str], start: int) -> int:
    """Index after the leading ``NAME=value`` words a prefix leaves in front of its command (``env FOO=1 rm``)."""
    index = start
    while index < len(words) and _ASSIGNMENT_RE.match(words[index]):
        index += 1
    return index


def _prefix_end(words: Sequence[str], start: int, prefix: _Prefix) -> int | None:
    """Index of the command after *prefix*'s own flags, ``len(words)`` when the prefix runs no command.

    None means the form is not understood. An index rather than the words that follow is what keeps a chain of
    any length linear to read: peeling the chain never copies its tail at each step.
    """
    index = start
    while index < len(words):
        token = words[index]
        if token == "--":
            return index + 1
        if not token.startswith("-") or token == "-":
            return index
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
    return len(words)


def _peel_deny_index(words: Sequence[str], start: int) -> int | None:
    """Index of the command the deny-direction prefix at *start* hands control to, ``len(words)`` when none.

    None means the command is already read as written: no prefix, no leading assignment, or a form that is not
    understood.
    """
    rest = _assignment_end(words, start)
    if rest >= len(words):
        return None
    prefix = _PREFIXES.get(words[rest].rsplit("/", 1)[-1])
    if prefix is None:
        return rest if rest != start else None
    after = _prefix_end(words, rest + 1, prefix)
    return None if after is None else _assignment_end(words, after)


def _peel_transparent_index(words: Sequence[str], start: int) -> int | None:
    """Index behind ``command`` / ``time`` / ``timeout``, ``len(words)`` when it runs nothing, None when unknown."""
    rest = _assignment_end(words, start)
    if rest >= len(words):
        return None
    base = words[rest].rsplit("/", 1)[-1]
    if base not in TRANSPARENT_WRAPPERS:
        return None
    return _transparent_inner(words, rest + 1, base)


def peel_deny_wrapper(words: Sequence[str]) -> list[str] | None:
    """The words the deny-direction prefix in *words* hands control to.

    ``[]`` means the prefix runs no command (``env -0``, a bare ``sudo``). None means the command is already
    read as written: no prefix, no leading assignment, or a form that is not understood. Leading
    ``NAME=value`` words are read through as well, since ``A=1 rm -rf /`` runs ``rm -rf /``.
    """
    index = _peel_deny_index(words, 0)
    return None if index is None else list(words[index:])


def shell_script_of(words: Sequence[str]) -> str | None:
    """The script text a shell ``-c`` form or ``eval`` runs as its own command line.

    None means *words* is not such a form, or names a script file whose text this layer cannot read. A shell
    that gets no ``-c`` reads a file or a standard input stream, and ``eval`` joins its arguments, so the
    returned text is what the shell itself would parse next.
    """
    return _shell_script_index(words, 0)


def _shell_script_index(words: Sequence[str], start: int) -> str | None:
    """The script text the ``-c`` form or ``eval`` at *start* runs, by the same rules as :func:`shell_script_of`."""
    rest = _assignment_end(words, start)
    if rest >= len(words):
        return None
    base = words[rest].rsplit("/", 1)[-1]
    if base == "eval":
        index = rest + 1
        while index < len(words) and words[index] == "--":
            index += 1
        return " ".join(words[index:]) if index < len(words) else None
    if base not in _SHELLS:
        return None
    index = rest + 1
    while index < len(words):
        token = words[index]
        if token == "--" or not token.startswith("-") or token == "-":
            return None
        if token.startswith("--"):
            index += 1
            continue
        if "c" in token[1:]:
            return words[index + 1] if index + 1 < len(words) else None
        index += 1
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


def direct_command_readings(command: str) -> tuple[str, ...]:
    """The commands *command* hands control to in one step, outer command first out.

    One step means: the command at the bottom of the wrapper chain in front of the text, the script each
    shell ``-c`` or ``eval`` parses, and the body of each ``$(...)`` and backtick. The chain is peeled with an
    index into the same word list, so a line built out of any number of ``sudo``/``timeout``/``time`` prefixes
    still reaches the command it runs, in time proportional to the text and without copying its tail at each
    step. A wrapper that runs nothing (``sudo command -v git``, ``sudo time``) leaves the peel at that wrapper,
    so its own invocation is the reading. Callers that want the whole chain walk through :func:`deny_readings`;
    callers building a tree recurse through this one, so the tree is bounded by their own depth rather than by
    the text.
    """
    outer = command.strip()
    found: list[str] = []
    for start, end in split_command_spans(command):
        part = command[start:end]
        # A substitution body keeps the spaces around the command it runs (``$( id )``); they are not part of
        # the command text a rule matches, so every reading is trimmed before it is judged.
        found.extend(body.strip() for body in substitution_bodies(part))
        words = shell_words(part)
        if not words:
            continue
        index = 0
        peeled = False
        while index < len(words):
            script = _shell_script_index(words, index)
            if script is not None:
                found.append(script.strip())
                break
            inner = _peel_deny_index(words, index)
            if inner is None:
                inner = _peel_transparent_index(words, index)
            if inner is None or inner >= len(words):
                break
            index = inner
            peeled = True
        if peeled:
            found.append(" ".join(words[index:]))
    return tuple(text for text in dict.fromkeys(found) if text and text != outer)


def deny_readings(command: str) -> tuple[str, ...]:
    """The command lines to judge alongside *command* itself, bounded, deduplicated and capped.

    A line such as ``sudo kubectl delete ns prod`` is read as ``kubectl delete ns prod`` (and, for a wrapped
    read, whatever that command runs), which is what a deny list or a ruleset pattern has to see. The command
    itself is not repeated, so callers can judge it first and still match on any of these.

    Only *branching* consumes the ``DENY_WRAPPER_DEPTH`` budget: a chain of prefixes is peeled to the command
    at its bottom in one step by :func:`direct_command_readings`, so no number of ``sudo``/``timeout``/``time``
    wrappers can push the inner command past the bound. What the bound does cap is how many substitutions and
    ``-c`` scripts deep the walk expands, and ``MAX_COMMAND_READINGS`` caps how many commands it ever returns,
    so a line whose every word is a substitution cannot make a caller do unbounded work. The command itself is
    always the caller's own reading and is never dropped.
    """
    outer = command.strip()
    readings: list[str] = []
    seen = {outer}
    pending: list[tuple[str, int]] = [(outer, 0)]
    while pending and len(readings) < MAX_COMMAND_READINGS:
        text, depth = pending.pop()
        if depth >= DENY_WRAPPER_DEPTH:
            continue
        for child in direct_command_readings(text):
            if child in seen:
                continue
            seen.add(child)
            readings.append(child)
            if len(readings) >= MAX_COMMAND_READINGS:
                break
            pending.append((child, depth + 1))
    return tuple(readings)
