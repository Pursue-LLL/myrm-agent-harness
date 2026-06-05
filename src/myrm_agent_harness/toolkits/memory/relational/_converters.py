"""Row-to-model converters for SQLiteRelationalStore.

[INPUT]
- toolkits.memory.types::MemoryScope, MemoryType, MemoryStatus, PendingRecord (POS: Memory type system foundation. Provides type-safe schema definitions for all memory types. ConversationMemory implements verbatim storage with dual-field (raw_exchange + content summary) and dual-embedding (raw + summary vectors) for lossless information preservation and adaptive retrieval optimization.)

[OUTPUT]
- now_iso: Column order: id, user_id, key, value, primary_namespace,...
- parse_dt: function — parse_dt
- row_to_profile: function — row_to_profile
- row_to_procedural: Column order: id, user_id, content, trigger_text, action_...
- row_to_pending: Column order: id, user_id, memory_type, content, memory_d...

[POS]
Row-to-model converters for SQLiteRelationalStore.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.types import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    PendingRecord,
    ProceduralMemory,
    ProfileEntry,
    RuleSource,
    ToolRulePriority,
)

PROCEDURAL_COLUMNS = (
    "id, user_id, content, trigger_text, action_text, "
    "priority, is_active, trigger_keywords, source, metadata, "
    "primary_namespace, namespaces, agent_id, channel_id, conversation_id, task_id, "
    "tool_name, tool_rule_priority, created_at, updated_at"
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_dt(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def row_to_profile(row: tuple[object, ...]) -> ProfileEntry:
    """Column order: id, user_id, key, value, primary_namespace, namespaces, agent_id, channel_id, conversation_id, task_id, created_at, updated_at."""
    return ProfileEntry(
        id=str(row[0]),
        user_id=str(row[1]),
        key=str(row[2]),
        value=str(row[3]),
        scope=MemoryScope(
            primary_namespace=str(row[4] or ""),
            namespaces=json.loads(row[5]) if row[5] else [],
            agent_id=str(row[6]) if row[6] else None,
            channel_id=str(row[7]) if row[7] else None,
            conversation_id=str(row[8]) if row[8] else None,
            task_id=str(row[9]) if row[9] else None,
        ),
        created_at=parse_dt(str(row[10])),
        updated_at=parse_dt(str(row[11])),
    )


def row_to_procedural(row: tuple[object, ...]) -> ProceduralMemory:
    """Column order: id, user_id, content, trigger_text, action_text,
    priority, is_active, trigger_keywords, source, metadata, primary_namespace,
    namespaces, agent_id, channel_id, conversation_id, task_id,
    tool_name, tool_rule_priority, created_at, updated_at.
    """
    keywords = json.loads(row[7]) if row[7] else []  # type: ignore[arg-type]
    metadata = json.loads(row[9]) if row[9] else {}  # type: ignore[arg-type]
    active = bool(row[6])

    tool_name_val = str(row[16]) if row[16] else None
    try:
        tool_priority = ToolRulePriority(row[17]) if row[17] else ToolRulePriority.NORMAL
    except ValueError:
        tool_priority = ToolRulePriority.NORMAL

    return ProceduralMemory(
        id=str(row[0]),
        user_id=str(row[1]),
        content=str(row[2]),
        trigger=str(row[3]),
        action=str(row[4]),
        priority=int(row[5]),  # type: ignore[arg-type]
        is_active=active,
        status=MemoryStatus.ACTIVE if active else MemoryStatus.DISABLED,
        trigger_keywords=keywords,
        source=RuleSource(row[8]) if row[8] else RuleSource.USER_EXTRACTED,
        metadata=metadata,
        scope=MemoryScope(
            primary_namespace=str(row[10] or ""),
            namespaces=json.loads(row[11]) if row[11] else [],
            agent_id=str(row[12]) if row[12] else None,
            channel_id=str(row[13]) if row[13] else None,
            conversation_id=str(row[14]) if row[14] else None,
            task_id=str(row[15]) if row[15] else None,
        ),
        tool_name=tool_name_val,
        tool_rule_priority=tool_priority,
        created_at=parse_dt(str(row[18])),
        updated_at=parse_dt(str(row[19])),
    )


def row_to_pending(row: tuple[object, ...]) -> PendingRecord:
    """Column order: id, user_id, memory_type, content, memory_data,
    source_chat_id, source_message_id, status, created_at, resolved_at.
    """
    memory_data = json.loads(row[4]) if row[4] else {}  # type: ignore[arg-type]
    return PendingRecord(
        id=str(row[0]),
        user_id=str(row[1]),
        memory_type=MemoryType(row[2]),
        content=str(row[3]),
        memory_data=memory_data,
        source_chat_id=str(row[5]) if row[5] else None,
        source_message_id=str(row[6]) if row[6] else None,
        status=str(row[7]),
        created_at=parse_dt(str(row[8])),
        resolved_at=parse_dt(str(row[9])) if row[9] else None,
    )
