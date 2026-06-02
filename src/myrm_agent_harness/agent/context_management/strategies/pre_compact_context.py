"""Pre-compaction protected-zone assembly helpers.

[INPUT]
- pipeline.base::ProcessorContext (POS: processor context)

[OUTPUT]
- PRE_COMPACT_RECALL_MARKER: detectable marker for injected recall blocks
- prepend_pre_compact_message: merge pre-compact HumanMessage into compacted layouts
- apply_pre_compact_after_protected_head: inject recall after protected head for compress-only paths

[POS]
Helpers for preserving pre-compaction recall injections across SessionNotes and Summarize.
"""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from ..infra.schemas import PRE_COMPACT_MESSAGE_METADATA_KEY
from ..pipeline.base import ProcessorContext
from .summary_builder import extract_protected_head

PRE_COMPACT_RECALL_MARKER = "<pre_compact_recall_context"


def get_pre_compact_message(context: ProcessorContext) -> BaseMessage | None:
    """Return the pending pre-compact message stored on the processor context."""
    candidate = context.metadata.get(PRE_COMPACT_MESSAGE_METADATA_KEY)
    return candidate if isinstance(candidate, BaseMessage) else None


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


def _messages_contain_pre_compact(messages: list[BaseMessage]) -> bool:
    return any(PRE_COMPACT_RECALL_MARKER in _message_text(message) for message in messages)


def prepend_pre_compact_message(
    protected_head: list[BaseMessage],
    summary_messages: list[BaseMessage],
    recent_messages: list[BaseMessage],
    *,
    context: ProcessorContext,
) -> list[BaseMessage]:
    """Insert the pre-compact recall message after protected head and before summary."""
    merged = protected_head + summary_messages + recent_messages
    pre_compact = get_pre_compact_message(context)
    if pre_compact is None:
        return merged
    if _messages_contain_pre_compact(merged):
        return merged
    return [*protected_head, pre_compact, *summary_messages, *recent_messages]


def apply_pre_compact_after_protected_head(
    messages: list[BaseMessage],
    *,
    context: ProcessorContext,
) -> list[BaseMessage]:
    """Insert pending pre-compact recall after protected head for in-place compaction paths."""
    if get_pre_compact_message(context) is None:
        return messages
    protected_head = extract_protected_head(messages)
    tail = messages[len(protected_head) :]
    return prepend_pre_compact_message(protected_head, [], tail, context=context)
