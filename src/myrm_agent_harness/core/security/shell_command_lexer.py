"""Quote- and comment-aware reading of a shell command line.

One scanner decides where a command ends, which words it has and which characters the shell interprets, so
the risk classifier, the approval-card span extractor, the destructive-action parser and the allow-always
matcher cannot disagree about what a command line contains.

[INPUT]
- A raw shell command string, possibly several lines

[OUTPUT]
- UNTERMINATED: Sentinel reported when the text ends inside a quote or after a dangling backslash.
- iter_syntax_chars: Characters the shell interprets (outside quotes, escapes and comments; ``$`` and the backtick also inside double quotes) with their index.
- split_command_spans: Trimmed (start, end) spans of the commands separated by ``;`` ``|`` ``||`` ``|&`` ``&`` ``&&`` or a line break.
- shell_words: The words of one command with quotes and escapes resolved, or None when the text is unparseable.
- has_word_expansion: Whether ``$``, a backtick or brace expansion can rewrite the words before the command runs.
- strip_comments: The command without comments and backslash-newline continuations, for tokenizers that do not know the shell's comment rule.

[POS]
Shared lexical layer of the shell command security checks. Pure functions without dependencies on the rest of the harness,
so that agent/ and toolkits/ read a command identically without importing each other.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from enum import Enum, auto
from typing import Final

UNTERMINATED: Final = "\0"

_BLANKS: Final = " \t\n\r"
_LINE_BREAKS: Final = "\n\r"
_OPERATORS: Final = "|;&"
_SEPARATORS: Final = _LINE_BREAKS + _OPERATORS
_DOUBLED_OPERATORS: Final = frozenset({"&&", "||", "|&"})
# A comment starts only at the beginning of a word: after a blank or an operator.
_WORD_BREAKS: Final = _BLANKS + _OPERATORS
_ESCAPABLE_IN_DOUBLE_QUOTES: Final = '$`"\\\n'
_EXPANDING_IN_DOUBLE_QUOTES: Final = "$`"
_EXPANSIONS: Final = frozenset("${`" + UNTERMINATED)

# Text without these characters has nothing the character-by-character scan could find, so the common plain
# command is read with C-level string operations instead.
_QUOTING_OR_COMMENT: Final = re.compile(r"[\\'\"#$`]")  # shell_words: quotes, escapes, comments, expansions
_EXPANSION_HINT: Final = re.compile(r"[\\'\"#${`]")  # has_word_expansion: also an unterminated quote
_COMMAND_CUT: Final = re.compile(r"[\\'\"#;&|\n\r]")  # split_command_spans: separators, quoting, comments
_BLANK_RUN: Final = re.compile(r"[ \t\n\r]+")


class _Kind(Enum):
    SYNTAX = auto()  # outside quotes: the shell interprets it (operators, blanks, expansions, plain word characters)
    LITERAL = auto()  # quoted or escaped: text of a word, never interpreted
    IGNORED = auto()  # a comment or a backslash-newline: the shell discards it
    QUOTE = auto()  # an opening quote: no text, but it makes a word exist (``""``)


def _atoms(command: str) -> Iterator[tuple[int, str, _Kind]]:
    """Walk *command* once and classify every character the way bash reads it."""
    # The opener of the quote being read: ``'``, ``"`` or ``$'`` (ANSI-C, where a backslash escapes the closing ``'``).
    quote = ""
    at_word_start = True
    dollar_end = -1  # index right after an unquoted ``$`` that no ``$$`` has taken for the process id
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        if char == "\\" and quote != "'":
            following = command[index + 1 : index + 2]
            if not following:
                yield length, UNTERMINATED, _Kind.SYNTAX
                return
            if following == "\n":
                yield index, "\\\n", _Kind.IGNORED
                index += 2
                continue
            if quote == '"' and following not in _ESCAPABLE_IN_DOUBLE_QUOTES:
                yield index, char, _Kind.LITERAL
                index += 1
            else:
                yield index + 1, following, _Kind.LITERAL
                index += 2
            at_word_start = False
        elif quote:
            if char == quote[-1]:
                quote = ""
            elif quote == '"' and char in _EXPANDING_IN_DOUBLE_QUOTES:
                yield index, char, _Kind.SYNTAX
            else:
                yield index, char, _Kind.LITERAL
            index += 1
        elif char in "'\"":
            quote = "$'" if char == "'" and dollar_end == index else char
            yield index, "", _Kind.QUOTE
            at_word_start = False
            index += 1
        elif char == "#" and at_word_start:
            end = command.find("\n", index)
            end = length if end < 0 else end
            yield index, command[index:end], _Kind.IGNORED
            index = end
        else:
            yield index, char, _Kind.SYNTAX
            at_word_start = char in _WORD_BREAKS
            if char != "$":
                dollar_end = -1
            else:
                # ``$$`` is the process id, so a quote opens ANSI-C only after an odd number of dollars.
                dollar_end = -1 if dollar_end == index else index + 1
            index += 1
    if quote:
        yield length, UNTERMINATED, _Kind.SYNTAX


def iter_syntax_chars(command: str) -> Iterator[tuple[int, str]]:
    """Yield ``(index, char)`` for every character the shell interprets.

    That is everything outside quotes, escapes and comments, plus the ``$`` and backtick that still expand
    inside double quotes. A quote that never closes, or a trailing backslash, yields ``UNTERMINATED`` last.
    """
    for index, char, kind in _atoms(command):
        if kind is _Kind.SYNTAX:
            yield index, char


def split_command_spans(command: str) -> list[tuple[int, int]]:
    """Return the trimmed ``(start, end)`` spans of the commands in *command*.

    Commands are separated by ``;``, ``|``, ``||``, ``|&``, ``&``, ``&&`` and line breaks; the ``&`` of a
    redirect (``2>&1``, ``&>``) is not a separator. Blank lines and comment-only lines are not commands, and
    an operator without a command on one side yields an empty span so callers can treat it conservatively.
    """
    if not _COMMAND_CUT.search(command):
        span = _trimmed_span(command, 0, len(command))
        return [span] if span else []
    return _scan_command_spans(command)


def _scan_command_spans(command: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    resume = 0
    after_line_break = True
    for index, char in iter_syntax_chars(command):
        if index < resume or char not in _SEPARATORS:
            continue
        if char in _LINE_BREAKS:
            span = _trimmed_span(command, start, index)
            if span:
                spans.append(span)
            start, after_line_break = index + 1, True
        elif not (char == "&" and _is_redirect_ampersand(command, index)):
            spans.append(_trimmed_span(command, start, index) or (index, index))
            resume = index + (2 if command[index : index + 2] in _DOUBLED_OPERATORS else 1)
            start, after_line_break = resume, False
    tail = _trimmed_span(command, start, len(command))
    if tail:
        spans.append(tail)
    elif not after_line_break:
        spans.append((len(command), len(command)))
    return spans


def _trimmed_span(command: str, start: int, end: int) -> tuple[int, int] | None:
    """Span of the text between *start* and *end* without blanks, or None if it is blank or a comment."""
    piece = command[start:end]
    text = piece.strip()
    if not text or text.startswith("#"):
        return None
    lead = len(piece) - len(piece.lstrip())
    return start + lead, start + lead + len(text)


def _is_redirect_ampersand(command: str, index: int) -> bool:
    """``>&``, ``<&`` and ``&>`` redirect a stream; their ``&`` does not end a command."""
    return command[index - 1 : index] in ("<", ">") or command[index + 1 : index + 2] == ">"


def shell_words(command: str) -> list[str] | None:
    """Split one command into the words the shell passes on, or None if it cannot be parsed.

    Quotes and backslash escapes are resolved and a comment is dropped, so ``rg "--pre"`` yields the word
    ``--pre`` exactly as the shell sees it. Operators are not interpreted: callers pass a single command.
    """
    if not _QUOTING_OR_COMMENT.search(command):
        return [word for word in _BLANK_RUN.split(command) if word]
    return _scan_words(command)


def _scan_words(command: str) -> list[str] | None:
    words: list[str] = []
    word: list[str] = []
    in_word = False
    for _, char, kind in _atoms(command):
        if kind is _Kind.IGNORED:
            continue
        if kind is _Kind.SYNTAX:
            if char == UNTERMINATED:
                return None
            if char in _BLANKS:
                if in_word:
                    words.append("".join(word))
                    word.clear()
                    in_word = False
                continue
        word.append(char)
        in_word = True
    if in_word:
        words.append("".join(word))
    return words


def has_word_expansion(command: str) -> bool:
    """True when ``$``, a backtick or an unquoted ``{`` can rewrite the words before the command runs.

    Word-by-word checks (flag lists, subcommand lists) cannot see a flag that variable or brace expansion
    builds at run time (``rg {--pre,x}``), so such a command is not judged by its text. Unparseable text counts.
    """
    if not _EXPANSION_HINT.search(command):
        return False
    return any(char in _EXPANSIONS for _, char in iter_syntax_chars(command))


def strip_comments(command: str) -> str:
    """Return *command* without comments and backslash-newline continuations.

    Only a ``#`` at the beginning of a word starts a comment, so ``a#b`` is untouched, and quoted text is
    never altered. Indices of the result do not correspond to indices of *command*.
    """
    if "#" not in command and "\\" not in command:
        return command
    pieces: list[str] = []
    cursor = 0
    for index, text, kind in _atoms(command):
        if kind is _Kind.IGNORED:
            pieces.append(command[cursor:index])
            cursor = index + len(text)
    pieces.append(command[cursor:])
    return "".join(pieces)
