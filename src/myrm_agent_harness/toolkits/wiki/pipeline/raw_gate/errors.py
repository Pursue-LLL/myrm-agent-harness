"""Raw publication gate errors.

[INPUT]
- dataclasses::dataclass (POS: standard library dataclass definition)

[OUTPUT]
- RawGateError: structured raw write failure surfaced to REST and agent callers

[POS]
Raw Gate 错误异常定义。提供统一的错误码与异常基类。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RawGateError(Exception):
    """Structured raw write failure surfaced to REST and agent callers."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message
