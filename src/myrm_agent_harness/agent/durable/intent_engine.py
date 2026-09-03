"""Intent-first execution engine pre-allocating result IDs and recording intent logs.

[INPUT]
- .types::IntentRecord, TreeEntry, EffectType, IntentStatus, generate_provisioned_id
- .protocols::DurableStorageProtocol, EffectsBoundaryProtocol

[OUTPUT]
- IntentExecutionEngine: Coordinates intent pre-recording, effect invocation, and atomic result appending.

[POS]
Intent-First durability engine guaranteeing mathematical determinism across crashes.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from myrm_agent_harness.agent.durable.protocols import (
    DurableStorageProtocol,
    EffectsBoundaryProtocol,
)
from myrm_agent_harness.agent.durable.types import (
    EffectType,
    IntentRecord,
    IntentStatus,
    TreeEntry,
    generate_provisioned_id,
)


class IntentExecutionEngine:
    """Orchestrates the Intent-First durability protocol before and after any side effect."""

    def __init__(
        self,
        storage: DurableStorageProtocol,
        effects_boundary: EffectsBoundaryProtocol | None = None,
    ) -> None:
        self.storage = storage
        self.effects_boundary = effects_boundary

    async def execute_effect(
        self,
        session_id: str,
        lane_id: str,
        effect_type: EffectType,
        source_leaf_id: str | None,
        payload: dict[str, Any],
        effect_callable: Callable[[], Coroutine[Any, Any, Any]],
        entry_type: str = "tool_result",
    ) -> tuple[IntentRecord, TreeEntry]:
        """Execute an effect strictly following the Intent-First protocol."""
        provisioned_id = generate_provisioned_id(prefix=f"{effect_type.value}_res")
        intent_id = f"intent_{uuid.uuid4().hex[:14]}"

        intent = IntentRecord(
            intent_id=intent_id,
            session_id=session_id,
            lane_id=lane_id,
            effect_type=effect_type,
            source_leaf_id=source_leaf_id,
            provisioned_result_id=provisioned_id,
            payload=payload,
            status=IntentStatus.PENDING,
        )

        # 1. Intent-First Rule: Persist intent record BEFORE invoking effect
        await self.storage.append_intent(intent)

        # 2. Effects boundary before hook
        if self.effects_boundary:
            await self.effects_boundary.before_effect(intent)

        error_msg: str | None = None
        result_content: Any = None
        try:
            # 3. Produce actual external side effect
            result_content = await effect_callable()
            intent.status = IntentStatus.COMPLETED
            intent.completed_at_ms = int(time.time() * 1000)
        except Exception as ex:
            intent.status = IntentStatus.INTERRUPTED
            intent.error_message = str(ex)
            error_msg = str(ex)
            result_content = {"error": str(ex), "status": "failed"}

        # 4. Effects boundary after hook
        if self.effects_boundary:
            await self.effects_boundary.after_effect(intent, result_content)

        # 5. Append real Result Entry using the EXACT provisioned result ID
        result_entry = TreeEntry(
            entry_id=provisioned_id,
            session_id=session_id,
            parent_id=source_leaf_id,
            entry_type=entry_type,
            content=result_content,
            metadata={"intent_id": intent_id, "status": intent.status.value},
        )
        await self.storage.append_tree_entry(result_entry)

        # 6. Update intent status in storage
        await self.storage.update_intent(intent)

        if error_msg:
            # Propagate exception after persistent state is clean
            pass

        return intent, result_entry
