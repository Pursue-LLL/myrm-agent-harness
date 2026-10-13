"""Record ephemeral session deltas after durable memory writes (cache-safe recency).

[INPUT]
- ephemeral_delta.shared_store::get_shared_ephemeral_delta_store
- core.context_vars::chat_id_var

[OUTPUT]
- record_ephemeral_memory_delta: append in-flight override for current chat session

[POS]
Toolkit hook invoked after profile/semantic writes during an agent run; does not mutate frozen system prefix.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from myrm_agent_harness.core.context_vars import chat_id_var
from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    DeltaActionKind,
    EphemeralDeltaItem,
)
from myrm_agent_harness.toolkits.memory.ephemeral_delta.shared_store import (
    get_shared_ephemeral_delta_store,
)

logger = logging.getLogger(__name__)

_MAX_DELTA_VALUE_CHARS = 480


def record_ephemeral_memory_delta(
    *,
    key: str,
    value: str,
    action: DeltaActionKind = DeltaActionKind.OVERRIDE,
    turn_index: int = 0,
    source: str = "memory_write",
) -> None:
    session_id = (chat_id_var.get() or "").strip()
    if not session_id or session_id == "default":
        return
    normalized_key = key.strip()
    normalized_value = value.strip()
    if not normalized_key or not normalized_value:
        return
    if len(normalized_value) > _MAX_DELTA_VALUE_CHARS:
        normalized_value = normalized_value[: _MAX_DELTA_VALUE_CHARS - 3] + "..."
    try:
        item = EphemeralDeltaItem(
            delta_id=f"delta_{uuid4().hex[:10]}",
            target_key=normalized_key,
            content=normalized_value,
            action=action,
            turn_index=turn_index,
            source=source,
        )
        get_shared_ephemeral_delta_store().record_delta(session_id, item)
    except Exception as exc:
        logger.warning("Failed to record ephemeral memory delta for session %s: %s", session_id, exc)


def clear_ephemeral_deltas_for_session(session_id: str | None) -> None:
    normalized = (session_id or "").strip()
    if not normalized:
        return
    try:
        get_shared_ephemeral_delta_store().clear(normalized)
    except Exception as exc:
        logger.warning("Failed to clear ephemeral deltas for session %s: %s", normalized, exc)
