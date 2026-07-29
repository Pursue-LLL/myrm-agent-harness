"""Raw publication gate errors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawGateError(Exception):
    """Structured raw write failure surfaced to REST and agent callers."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message
