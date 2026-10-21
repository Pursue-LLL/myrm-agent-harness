"""A vendor-key pattern that counts only where a token starts.

A vendor key prefix such as ``sk-`` also ends ordinary words ("task", "risk", "disk"), so it identifies a key only where
a token starts. That is after anything but a letter or digit, and also after a JSON-escaped tab or line break and after a
percent-encoded byte, which end in a letter or digit and still separate (``\\n`` or ``%3D`` in front of a pasted key).
The boundary is checked on each match the pattern finds. Writing it as a lookbehind at the front of the pattern instead
makes the regex engine try every position of the text rather than skip ahead to the pattern's literal prefix, which is
about ten times slower on ordinary text, and ordinary text is what every outbound message is.

[INPUT]
- (none: standard library only)

[OUTPUT]
- TOKEN_START: the start of a token as a regex fragment; a caller that joins vendor shapes into one pattern puts it in front
- NUMBER_START: the start of a number, for a shape that opens with digits and is written after letters
- TokenStartPattern: ``search`` / ``finditer`` / ``sub`` with the matches of the pattern that follow the start fragment

[POS]
Left-boundary wrapper for the vendor-prefix table of the leak detector. A match the boundary rejects is skipped and the
search resumes one character on, so a key that begins inside a rejected run (``task-notes-sk-...``) is still found. The
pattern must not match the empty string.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

TOKEN_START = r"(?:(?<![A-Za-z0-9])|(?<=\\[nrt])|(?<=%[0-9A-Fa-f]{2}))"
NUMBER_START = r"(?<!\d)"


class TokenStartPattern:
    """``pattern`` whose matches count only where ``start`` holds in front of them."""

    __slots__ = ("_pattern", "_start")

    def __init__(self, pattern: re.Pattern[str], start: str = TOKEN_START) -> None:
        self._pattern = pattern
        self._start = re.compile(start)

    def finditer(self, content: str, /) -> Iterator[re.Match[str]]:
        position = 0
        while (match := self._pattern.search(content, position)) is not None:
            if self._start.match(content, match.start()):
                yield match
                position = max(match.end(), match.start() + 1)
            else:
                position = match.start() + 1

    def search(self, content: str, /) -> re.Match[str] | None:
        return next(self.finditer(content), None)

    def sub(self, repl: Callable[[re.Match[str]], str], content: str, /) -> str:
        pieces: list[str] = []
        last = 0
        for match in self.finditer(content):
            pieces += (content[last : match.start()], repl(match))
            last = match.end()
        return "".join((*pieces, content[last:])) if pieces else content
