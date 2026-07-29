"""Shared retention helpers for context pipeline processors.

[INPUT]
- infra.schemas::CompressionIntent, DEFAULT_CACHE_TTL_PRUNE_CONFIG
- infra.message_priority::_is_tool_error
- strategies.tool_call_groups::build_tool_call_groups

[OUTPUT]
- extract_failed_tool_call_ids: read failed tool IDs from compression intent metadata
- should_retain_tool_message: whether a tool result should skip LLM semantic filtering
- find_keep_recent_prune_cutoff: align ActivePrune with Compress keep_recent_calls
- format_retained_tool_trim_message: deterministic trim message for error/failed outputs

[POS]
Cross-processor retention contract. Keeps Filter and ActivePrune aligned with
CompressProcessor keep_recent_calls without a separate planner processor.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.utils.text_utils import get_token_count

from .message_priority import _is_tool_error
from ..strategies.tool_call_groups import build_tool_call_groups

_ECO_KEEP_RECENT_REDUCTION = 2
_ECO_KEEP_RECENT_MIN = 2


def extract_failed_tool_call_ids(metadata: dict[str, object]) -> frozenset[str]:
    """Read failed tool-call IDs from pipeline metadata compression intent."""
    raw_intent = metadata.get("compression_intent")
    if not isinstance(raw_intent, dict):
        return frozenset()

    raw_failed_ids = raw_intent.get("failed_tool_call_ids")
    if not isinstance(raw_failed_ids, list):
        return frozenset()

    return frozenset(
        tool_call_id
        for tool_call_id in raw_failed_ids
        if isinstance(tool_call_id, str) and tool_call_id
    )


def effective_keep_recent_calls(*, keep_recent_calls: int, eco_mode: bool) -> int:
    """Mirror CompressProcessor eco adjustment for keep_recent_calls."""
    if not eco_mode:
        return max(keep_recent_calls, 0)
    return max(_ECO_KEEP_RECENT_MIN, keep_recent_calls - _ECO_KEEP_RECENT_REDUCTION)


def should_retain_tool_message(msg: ToolMessage, failed_tool_call_ids: frozenset[str]) -> bool:
    """Return True when Filter should use deterministic trim instead of LLM summary."""
    tool_call_id = getattr(msg, "tool_call_id", None)
    if isinstance(tool_call_id, str) and tool_call_id and tool_call_id in failed_tool_call_ids:
        return True
    return _is_tool_error(msg)


def format_retained_tool_trim_message(trimmed_content: str, *, saved_path: str | None) -> str:
    """Format a deterministic trim preview for retained error/failed tool output."""
    lines = [
        "[RETAINED TOOL OUTPUT - deterministic trim; full content preserved on disk]",
        trimmed_content,
    ]
    if saved_path:
        lines.append(f"Full output saved to: {saved_path}")
        lines.append("Use file_read_tool to read specific portions of the saved file.")
    return "\n".join(lines)


def find_keep_recent_prune_cutoff(messages: list[BaseMessage], keep_recent_calls: int) -> int:
    """Return the max ToolMessage index that may be pruned (exclusive upper bound).

    Tool messages at index >= cutoff are within the keep_recent tool-call window
    and must not be active-pruned. Falls back to 0 when all groups are protected.
    """
    if keep_recent_calls <= 0:
        return len(messages)

    groups = build_tool_call_groups(messages)
    if not groups:
        return 0

    if len(groups) <= keep_recent_calls:
        return groups[0].tool_index

    first_protected = groups[-keep_recent_calls]
    return first_protected.tool_index


def structure_trim_tokens_saved(original: str, trimmed: str) -> int:
    """Estimate tokens saved by deterministic structure trim."""
    return max(0, get_token_count(original) - get_token_count(trimmed))
