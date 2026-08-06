"""Deliverable write claim verifier for CompletionGuard.

Detects when the assistant's final response claims a workspace file was written
or saved, but no successful file_write_tool / file_edit_tool calls exist in the
session window. Complements _mutation_verifier (failed writes) with zero-call
hallucination blocking.

[INPUT]
- Assistant final text + LoopGuard CallRecord window

[OUTPUT]
- check_deliverable_write_claim(): reason string or None

[POS]
Harness middleware helper; invoked from CompletionGuard.aafter_model at completion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.security.guards.loop_guard import SuccessLevel

if TYPE_CHECKING:
    from myrm_agent_harness.agent.security.guards.loop_guard import CallRecord

_FILE_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "file_write_tool",
        "file_edit_tool",
    }
)

_WRITE_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(saved to|wrote to|written to|saved as|created (?:the )?file|exported to|generated (?:the )?file)\b"
    ),
    re.compile(r"(已保存|已写入|写入到|保存至|保存到|已生成(?:文件|报告)?|已创建(?:文件)?|文件已)"),
)

_FILE_PATH_INDICATOR = re.compile(
    r"(?i)(`[^`]+`|workspace/[A-Za-z0-9_./-]+|[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,12})"
)


def detect_claimed_file_write(content: str) -> bool:
    """Return True when assistant text likely claims a deliverable file write."""
    text = content.strip()
    if not text:
        return False

    has_claim = any(pattern.search(text) for pattern in _WRITE_CLAIM_PATTERNS)
    if not has_claim:
        return False

    return _FILE_PATH_INDICATOR.search(text) is not None


def has_successful_file_write_calls(records: list[CallRecord]) -> bool:
    """Return True when at least one successful file write/edit tool call exists."""
    for record in records:
        if record.tool_name not in _FILE_WRITE_TOOLS:
            continue
        if record.success_level != SuccessLevel.FAILURE:
            return True
    return False


def check_deliverable_write_claim(content: str, records: list[CallRecord]) -> str | None:
    """Block completion when a write is claimed without any successful write tool call."""
    if not detect_claimed_file_write(content):
        return None
    if has_successful_file_write_calls(records):
        return None
    return (
        "The assistant response claims a workspace file was written or saved, "
        "but no successful file_write_tool or file_edit_tool calls were recorded. "
        "Use a file write tool before finishing, or revise the response."
    )


__all__ = [
    "check_deliverable_write_claim",
    "detect_claimed_file_write",
    "has_successful_file_write_calls",
]
