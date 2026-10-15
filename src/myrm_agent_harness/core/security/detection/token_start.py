"""A pattern that matches only where a token starts, without the cost of a leading lookbehind.

A vendor key prefix such as ``sk-`` also ends ordinary words ("task", "risk", "disk"), so it identifies a key only when
no letter or digit comes right before it. Writing that as a lookbehind at the front of the pattern makes the regex engine
try every position of the text instead of skipping ahead to the pattern's literal prefix (ten times slower on ordinary
text, which is what every outbound message is). The text is therefore searched without the boundary first, and the
bounded pattern runs only where that finds a candidate; the bounded pattern alone decides the result.

[INPUT]
- (none: standard library only)

[OUTPUT]
- TokenStartPattern: ``search`` / ``finditer`` / ``sub`` with the semantics of ``(?<![A-Za-z0-9])`` + the pattern

[POS]
Left-boundary wrapper for the vendor-prefix table of the leak detector. It is meant for prefix shapes: a pattern with
an inline flag, one that can match nothing, or one that opens with a lookbehind of its own is outside that.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

_TOKEN_START = r"(?<![A-Za-z0-9])"


class TokenStartPattern:
    """``pattern`` that counts only where no ASCII letter or digit precedes the match."""

    __slots__ = ("_bounded", "_candidate")

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self._candidate = pattern
        self._bounded = re.compile(_TOKEN_START + pattern.pattern, pattern.flags)

    def search(self, content: str, /) -> re.Match[str] | None:
        return self._bounded.search(content) if self._candidate.search(content) else None

    def finditer(self, content: str, /) -> Iterator[re.Match[str]]:
        return self._bounded.finditer(content) if self._candidate.search(content) else iter(())

    def sub(self, repl: Callable[[re.Match[str]], str], content: str, /) -> str:
        return self._bounded.sub(repl, content) if self._candidate.search(content) else content
