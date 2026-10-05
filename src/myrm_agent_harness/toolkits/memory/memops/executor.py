"""MemOps 4-tuple standard semantic executor.

Implements the formal state machine and execution logic for Remember, Forget,
Update, and Reflect atomic operations (inspired by Metis / arXiv:2607.26760).

[INPUT]
- myrm_agent_harness.toolkits.memory.memops.models::* (POS: schemas, requests, results)
- asyncio, json, pathlib (POS: concurrency locking and optional persistence)

[OUTPUT]
- MemOpsExecutor: Core executor class handling atomic memory operations.

[POS]
Native Agent memory operation execution engine ensuring zero leakage and consistent mutations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.memops.models import (
    MemOpFact,
    MemOpRequest,
    MemOpResult,
    MemOpStatus,
    MemOpType,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemOpsExecutor:
    """Standardized atomic execution engine for native Remember, Forget, Update, and Reflect operations."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir
        self._lock = asyncio.Lock()
        # fact_id -> MemOpFact
        self._facts: dict[str, MemOpFact] = {}

        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    async def execute(self, request: MemOpRequest) -> MemOpResult:
        """Dispatch and execute a typed memory operation request."""
        match request.op_type:
            case MemOpType.REMEMBER:
                return await self.remember(request)
            case MemOpType.FORGET:
                return await self.forget(request)
            case MemOpType.UPDATE:
                return await self.update(request)
            case MemOpType.REFLECT:
                return await self.reflect(request)

    async def remember(self, request: MemOpRequest) -> MemOpResult:
        """Execute Remember: structured epistemic fact ingestion with deduplication."""
        if not request.fact:
            return MemOpResult(
                op_type=MemOpType.REMEMBER,
                status=MemOpStatus.REJECTED,
                message="Missing fact payload in Remember request",
            )

        fact = request.fact
        scope_id = request.scope_id or fact.scope_id

        async with self._lock:
            # Check for existing fact with matching entity and attribute in same scope
            for existing in self._facts.values():
                if (
                    existing.scope_id == scope_id
                    and existing.entity.strip().lower() == fact.entity.strip().lower()
                    and existing.attribute.strip().lower() == fact.attribute.strip().lower()
                    and existing.is_active
                ):
                    # Same fact value: absorb and reinforce confidence
                    if existing.value.strip().lower() == fact.value.strip().lower():
                        existing.confidence = min(1.0, max(existing.confidence, fact.confidence) + 0.05)
                        existing.updated_at = _utc_now()
                        if fact.evidence and fact.evidence not in existing.evidence:
                            existing.evidence = f"{existing.evidence}; {fact.evidence}".strip("; ")
                        self._persist_to_disk_sync()
                        return MemOpResult(
                            op_type=MemOpType.REMEMBER,
                            status=MemOpStatus.SUCCESS,
                            affected_fact_ids=[existing.fact_id],
                            fact=existing,
                            message=f"Reinforced existing fact {existing.fact_id}",
                        )
                    # Different fact value: conflict detected, suggest update instead
                    return MemOpResult(
                        op_type=MemOpType.REMEMBER,
                        status=MemOpStatus.CONFLICT,
                        affected_fact_ids=[existing.fact_id],
                        fact=existing,
                        message=(
                            f"Contradiction detected for entity '{existing.entity}.{existing.attribute}': "
                            f"existing='{existing.value}', proposed='{fact.value}'. Use Update to mutate."
                        ),
                    )

            # Insert new fact
            fact.scope_id = scope_id
            self._facts[fact.fact_id] = fact
            self._persist_to_disk_sync()
            return MemOpResult(
                op_type=MemOpType.REMEMBER,
                status=MemOpStatus.SUCCESS,
                affected_fact_ids=[fact.fact_id],
                fact=fact,
                message=f"Remembered fact {fact.fact_id}",
            )

    async def forget(self, request: MemOpRequest) -> MemOpResult:
        """Execute Forget: permanent or tombstone cascade elimination ensuring zero leakage."""
        async with self._lock:
            targets: list[MemOpFact] = []
            scope_id = request.scope_id

            if request.target_id:
                target = self._facts.get(request.target_id)
                if target and target.is_active and (target.scope_id == scope_id or scope_id == "default"):
                    targets.append(target)
            elif request.target_entity:
                target_entity = request.target_entity.strip().lower()
                for f in self._facts.values():
                    if f.is_active and f.entity.strip().lower() == target_entity and f.scope_id == scope_id:
                        targets.append(f)

            if not targets:
                return MemOpResult(
                    op_type=MemOpType.FORGET,
                    status=MemOpStatus.NOT_FOUND,
                    message="No matching active facts found to forget",
                )

            affected_ids: list[str] = []
            for target in targets:
                if request.hard_delete:
                    del self._facts[target.fact_id]
                else:
                    target.is_active = False
                    target.updated_at = _utc_now()
                affected_ids.append(target.fact_id)

            self._persist_to_disk_sync()
            action_desc = "Hard-deleted" if request.hard_delete else "Tombstoned"
            return MemOpResult(
                op_type=MemOpType.FORGET,
                status=MemOpStatus.SUCCESS,
                affected_fact_ids=affected_ids,
                message=f"{action_desc} {len(affected_ids)} facts. Reason: {request.reason or 'User requested'}",
            )

    async def update(self, request: MemOpRequest) -> MemOpResult:
        """Execute Update: atomic, audited mutation with monotonic version increment."""
        if not request.target_id and not (request.target_entity and request.target_attribute):
            return MemOpResult(
                op_type=MemOpType.UPDATE,
                status=MemOpStatus.REJECTED,
                message="Target fact_id or (target_entity, target_attribute) required for Update",
            )

        if request.new_value is None:
            return MemOpResult(
                op_type=MemOpType.UPDATE,
                status=MemOpStatus.REJECTED,
                message="New value payload required for Update",
            )

        async with self._lock:
            target: MemOpFact | None = None
            if request.target_id:
                target = self._facts.get(request.target_id)
            else:
                for f in self._facts.values():
                    if (
                        f.is_active
                        and f.scope_id == request.scope_id
                        and f.entity.strip().lower() == str(request.target_entity).strip().lower()
                        and f.attribute.strip().lower() == str(request.target_attribute).strip().lower()
                    ):
                        target = f
                        break

            if not target or not target.is_active:
                return MemOpResult(
                    op_type=MemOpType.UPDATE,
                    status=MemOpStatus.NOT_FOUND,
                    message="Target fact not found or inactive",
                )

            # Atomic mutation
            old_value = target.value
            target.value = request.new_value
            target.version += 1
            target.updated_at = _utc_now()
            if request.new_statement:
                target.statement = request.new_statement
            else:
                target.statement = target.statement.replace(old_value, request.new_value)
            if request.new_evidence:
                target.evidence = request.new_evidence

            self._persist_to_disk_sync()
            return MemOpResult(
                op_type=MemOpType.UPDATE,
                status=MemOpStatus.SUCCESS,
                affected_fact_ids=[target.fact_id],
                fact=target,
                message=f"Updated fact {target.fact_id} from '{old_value}' to '{target.value}' (v{target.version})",
            )

    async def reflect(self, request: MemOpRequest) -> MemOpResult:
        """Execute Reflect: multi-fact inductive synthesis across active knowledge."""
        async with self._lock:
            active_facts = [
                f for f in self._facts.values()
                if f.is_active and f.scope_id == request.scope_id
            ]

            if not active_facts:
                return MemOpResult(
                    op_type=MemOpType.REFLECT,
                    status=MemOpStatus.SUCCESS,
                    message="No active facts available for reflection",
                    reflection_synthesis=[],
                )

            # Synthesize cross-fact insights
            insights: list[str] = []
            goal = (request.reflection_goal or "").strip().lower()

            entity_groups: dict[str, list[MemOpFact]] = {}
            for f in active_facts:
                entity_groups.setdefault(f.entity, []).append(f)

            for entity, group in entity_groups.items():
                if len(group) >= 2:
                    attrs = ", ".join(f"{g.attribute}={g.value}" for g in group)
                    insights.append(f"Entity '{entity}' has unified profile: {attrs}")

            # If goal provided, filter or highlight goal-relevant facts
            if goal:
                relevant = [f.statement for f in active_facts if any(w in f.statement.lower() for w in goal.split())]
                if relevant:
                    insights.append(f"Goal '{goal}' is directly supported by: {'; '.join(relevant)}")

            if not insights:
                insights.append(f"Synthesized {len(active_facts)} active facts across {len(entity_groups)} entities")

            return MemOpResult(
                op_type=MemOpType.REFLECT,
                status=MemOpStatus.SUCCESS,
                affected_fact_ids=[f.fact_id for f in active_facts],
                reflection_synthesis=insights,
                message=f"Generated {len(insights)} synthesized reflection insights",
            )

    async def recall_active_facts(self, scope_id: str, query: str = "") -> list[MemOpFact]:
        """Recall active facts under zero-context replay protocol (no dialogue history)."""
        async with self._lock:
            active = [f for f in self._facts.values() if f.is_active and f.scope_id == scope_id]
            if not query.strip():
                return active

            query_lower = query.lower()
            return [
                f for f in active
                if query_lower in f.statement.lower()
                or query_lower in f.entity.lower()
                or query_lower in f.attribute.lower()
                or query_lower in f.value.lower()
            ]

    def _persist_to_disk_sync(self) -> None:
        """Sync internal state to disk if directory configured."""
        if not self._storage_dir:
            return
        try:
            facts_file = self._storage_dir / "memops_facts.json"
            data = [f.model_dump(mode="json") for f in self._facts.values()]
            facts_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist MemOps facts: %s", exc)

    def _load_from_disk(self) -> None:
        """Load internal state from disk on startup."""
        if not self._storage_dir:
            return
        try:
            facts_file = self._storage_dir / "memops_facts.json"
            if facts_file.is_file():
                raw = facts_file.read_text(encoding="utf-8")
                records = json.loads(raw)
                for item in records:
                    fact = MemOpFact.model_validate(item)
                    self._facts[fact.fact_id] = fact
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load MemOps facts from disk: %s", exc)
