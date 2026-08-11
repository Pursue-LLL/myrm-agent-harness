"""Compactor subpackage: priority-aware message compression.

[INPUT]
- chat_history: 待压缩消息列表（含 tool 消息对）

[OUTPUT]
- compress_messages_async(): 消息压缩（工具消息对合并）
- should_compress(): 是否触发压缩
- deduplicate_tool_results(): 工具结果去重

[POS]
Priority-aware context compaction strategies. Groups tool messages, deduplicates
results, and applies integrity-safe compression to fit the active context window.
"""

from .compact_rules import COMPACT_RULES
from .compactor import (
    compress_messages_async,
    compress_tool_message_async,
    find_tool_message_pairs,
    should_compress,
)
from .deduplication import deduplicate_tool_results
from .integrity_guard import ensure_tool_pair_integrity
from .pre_compact_context import (
    PRE_COMPACT_RECALL_MARKER,
    apply_pre_compact_after_protected_head,
    prepend_pre_compact_message,
)
from .smart_fallback import apply_smart_fallback

__all__ = [
    "COMPACT_RULES",
    "PRE_COMPACT_RECALL_MARKER",
    "apply_pre_compact_after_protected_head",
    "apply_smart_fallback",
    "compress_messages_async",
    "compress_tool_message_async",
    "deduplicate_tool_results",
    "ensure_tool_pair_integrity",
    "find_tool_message_pairs",
    "prepend_pre_compact_message",
    "should_compress",
]
