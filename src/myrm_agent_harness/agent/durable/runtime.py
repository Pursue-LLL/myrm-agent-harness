"""Unified Durable Agent Runtime orchestrator.

[INPUT]
- .types::IntentRecord, TreeEntry, LaneState, UsageRecord, IntentStatus, EffectType
- .protocols::DurableStorageProtocol, EffectsBoundaryProtocol
- .storage::InMemoryDurableStorage, SqliteDurableStorage
- .mutation_line::LaneMutationLine, MutationAction
- .intent_engine::IntentExecutionEngine
- .replay_auditor::ReplaySafetyAuditor

[OUTPUT]
- RecoverySummary: Outcome report after recovering from a crash.
- DurableAgentRuntime: Core orchestrator integrating storage, mutation line, intent ledger, and recovery.

[POS]
Main entrypoint for durable stateful agent execution and recovery.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from myrm_agent_harness.agent.durable.effects_gate import (
    ManualDriveEffectsGate,
)
from myrm_agent_harness.agent.durable.intent_engine import IntentExecutionEngine
from myrm_agent_harness.agent.durable.mutation_line import (
    LaneMutationLine,
)
from myrm_agent_harness.agent.durable.protocols import DurableStorageProtocol
from myrm_agent_harness.agent.durable.replay_auditor import ReplaySafetyAuditor
from myrm_agent_harness.agent.durable.storage import (
    InMemoryDurableStorage,
    SqliteDurableStorage,
)
from myrm_agent_harness.agent.durable.types import (
    EffectType,
    IntentStatus,
    LaneState,
    TreeEntry,
    UsageRecord,
)


@dataclass(slots=True)
class RecoverySummary:
    """Summary metrics of crash recovery execution."""

    session_id: str
    pending_intents_count: int
    replayed_safe_count: int
    interrupted_synthetic_count: int
    recovered_lanes_count: int
    total_tree_entries: int
    is_clean: bool = True
    leaf_checksum: str | None = None


class DurableAgentRuntime:
    """Enterprise-grade durable stateful agent runtime."""

    def __init__(
        self,
        session_id: str,
        storage: DurableStorageProtocol | None = None,
        db_path: str | Path | None = None,
        effects_gate: ManualDriveEffectsGate | None = None,
        auditor: ReplaySafetyAuditor | None = None,
    ) -> None:
        self.session_id = session_id
        if storage:
            self.storage = storage
        elif db_path:
            self.storage = SqliteDurableStorage(db_path)
        else:
            self.storage = InMemoryDurableStorage()

        self.effects_gate = effects_gate or ManualDriveEffectsGate()
        self.intent_engine = IntentExecutionEngine(self.storage, self.effects_gate)
        self.auditor = auditor or ReplaySafetyAuditor()
        self._mutation_lines: dict[str, LaneMutationLine] = {}

    def get_mutation_line(self, lane_id: str = "main") -> LaneMutationLine:
        """Get or initialize the single-writer mutation line for a lane."""
        if lane_id not in self._mutation_lines:
            self._mutation_lines[lane_id] = LaneMutationLine(
                self.session_id,
                lane_id,
                self.storage,
            )
        return self._mutation_lines[lane_id]

    async def initialize_session(self, initial_system_prompt: str, user_prompt: str) -> tuple[TreeEntry, LaneState]:
        """Initialize a new conversation tree with system prompt and root user prompt."""
        lane = await self.storage.get_or_create_lane(self.session_id, "main")

        sys_entry = TreeEntry(
            entry_id=f"sys_{uuid.uuid4().hex[:12]}",
            session_id=self.session_id,
            parent_id=None,
            entry_type="system_prompt",
            content=initial_system_prompt,
        )
        await self.storage.append_tree_entry(sys_entry)

        user_entry = TreeEntry(
            entry_id=f"usr_{uuid.uuid4().hex[:12]}",
            session_id=self.session_id,
            parent_id=sys_entry.entry_id,
            entry_type="message",
            content=user_prompt,
            metadata={"role": "user"},
        )
        await self.storage.append_tree_entry(user_entry)

        lane.current_leaf_id = user_entry.entry_id
        lane.status = "running"
        await self.storage.update_lane_state(lane)
        return user_entry, lane

    async def execute_tool(
        self,
        lane_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_callable: Callable[[], Coroutine[Any, Any, Any]],
    ) -> TreeEntry:
        """Execute a tool wrapped in the Intent-First durability protocol."""
        lane = await self.storage.get_or_create_lane(self.session_id, lane_id)
        parent_leaf = lane.current_leaf_id

        intent, result_entry = await self.intent_engine.execute_effect(
            session_id=self.session_id,
            lane_id=lane_id,
            effect_type=EffectType.TOOL_EXECUTION,
            source_leaf_id=parent_leaf,
            payload={"tool_name": tool_name, "tool_args": tool_args},
            effect_callable=tool_callable,
            entry_type="tool_result",
        )

        # Update lane leaf pointer
        lane.current_leaf_id = result_entry.entry_id
        await self.storage.update_lane_state(lane)
        return result_entry

    async def record_usage(
        self,
        lane_id: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> UsageRecord:
        """Atomically persist LLM usage and cost immediately after model response."""
        usage = UsageRecord(
            usage_id=f"usg_{uuid.uuid4().hex[:14]}",
            session_id=self.session_id,
            lane_id=lane_id,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached_tokens=cached_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )
        await self.storage.append_usage(usage)
        return usage

    async def resume_and_recover(self) -> RecoverySummary:
        """Recover from an unexpected shutdown/crash by resolving pending intents."""
        pending_intents = await self.storage.get_pending_intents(self.session_id)
        replayed_count = 0
        interrupted_count = 0

        for intent in pending_intents:
            decision = self.auditor.audit_intent(intent)
            if decision.can_reexecute:
                # Safe to re-execute or leave pending for caller
                replayed_count += 1
            else:
                # Unsafe side-effect: synthesize interrupted result to prevent duplicate mutation
                synthetic_entry = TreeEntry(
                    entry_id=intent.provisioned_result_id,
                    session_id=self.session_id,
                    parent_id=intent.source_leaf_id,
                    entry_type="tool_result",
                    content=decision.synthetic_result_payload or {"status": "interrupted"},
                    metadata={"intent_id": intent.intent_id, "status": "synthetic_interrupted"},
                )
                await self.storage.append_tree_entry(synthetic_entry)

                intent.status = IntentStatus.INTERRUPTED
                intent.error_message = decision.reason
                intent.completed_at_ms = int(time.time() * 1000)
                await self.storage.update_intent(intent)

                # Advance lane leaf to synthetic entry
                lane = await self.storage.get_or_create_lane(self.session_id, intent.lane_id)
                lane.current_leaf_id = synthetic_entry.entry_id
                lane.status = "interrupted"
                await self.storage.update_lane_state(lane)
                interrupted_count += 1

        history = await self.storage.get_tree_history(self.session_id)
        last_checksum = history[-1].checksum_sha256 if history else None

        return RecoverySummary(
            session_id=self.session_id,
            pending_intents_count=len(pending_intents),
            replayed_safe_count=replayed_count,
            interrupted_synthetic_count=interrupted_count,
            recovered_lanes_count=len(self._mutation_lines) or 1,
            total_tree_entries=len(history),
            is_clean=True,
            leaf_checksum=last_checksum,
        )
