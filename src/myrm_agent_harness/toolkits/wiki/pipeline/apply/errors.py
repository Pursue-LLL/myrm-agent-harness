"""Wiki apply mutation errors.

[INPUT]
- dataclasses::dataclass (POS: standard library dataclass definition)

[OUTPUT]
- WikiApplyError: structured apply failure surfaced to REST and agent callers

[POS]
Wiki apply 异常定义。提供统一的错误结构与状态码。
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
