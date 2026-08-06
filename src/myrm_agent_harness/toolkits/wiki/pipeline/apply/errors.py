"""Wiki apply mutation errors.

[POS]
See module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WikiApplyError(Exception):
    """Structured apply failure surfaced to REST and agent callers."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message
