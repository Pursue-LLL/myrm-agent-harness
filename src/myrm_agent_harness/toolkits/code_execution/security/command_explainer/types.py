"""DTO types for shell command explanation spans."""

from __future__ import annotations

from typing import Literal, TypedDict

SpanRiskLevel = Literal["safe", "unknown"]


class CommandSpan(TypedDict):
    """Char index span into the displayed command string."""

    startIndex: int
    endIndex: int
