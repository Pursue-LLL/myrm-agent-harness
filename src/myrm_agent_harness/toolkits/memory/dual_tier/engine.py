"""Dual-tier memory block lifecycle engine.

Orchestrates Hyper Memory Blocks (global macro models) and Local Memory Blocks
(session-bound working memories), providing scoped storage, dynamic attention fusion,
and session-end distillation & evaporation (inspired by Metis / arXiv:2607.26760).

[INPUT]
- myrm_agent_harness.toolkits.memory.dual_tier.models::* (POS: schemas)
- myrm_agent_harness.toolkits.memory.dual_tier.attention::MemoryAttentionRouter (POS: attention scoring and prompt fusion)
- myrm_agent_harness.toolkits.memory.types::EvaporationState (POS: evaporation enum)
- asyncio, json, pathlib (POS: concurrency and optional disk persistence)

[OUTPUT]
- DualTierBlockEngine: Core management service for dual-tier block lifecycles.

[POS]
Dual-tier engine isolating global mental models from transient session details.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.memory.dual_tier.attention import MemoryAttentionRouter
from myrm_agent_harness.toolkits.memory.dual_tier.models import (
    AttentionFusionContext,
    DistillationResult,
    HyperMemoryBlock,
    LocalMemoryBlock,
)
from myrm_agent_harness.toolkits.memory.types import EvaporationState

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DualTierBlockEngine:
    """Manages the lifecycle, fusion, and evaporation of Hyper and Local memory blocks."""

    def __init__(
        self,
        storage_dir: Path | None = None,
        router: MemoryAttentionRouter | None = None,
    ) -> None:
        self._storage_dir = storage_dir
        self._router = router or MemoryAttentionRouter()
        self._lock = asyncio.Lock()

        # In-memory indices: block_id -> block
        self._hyper_blocks: dict[str, HyperMemoryBlock] = {}
        self._local_blocks: dict[str, LocalMemoryBlock] = {}

        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    async def record_hyper_block(
        self,
        scope_id: str,
        statement: str,
        category: str = "preference",
        confidence: float = 0.9,
        source_session_id: str | None = None,
    ) -> HyperMemoryBlock:
        """Record or reinforce a long-term global Hyper Memory Block."""
        async with self._lock:
            # Check for existing matching statement to reinforce rather than duplicate
            for block in self._hyper_blocks.values():
                if (
                    block.scope_id == scope_id
                    and block.category == category
                    and block.statement.strip().lower() == statement.strip().lower()
                    and block.status == "active"
                ):
                    block.reinforcement_count += 1
                    block.confidence = min(1.0, block.confidence + 0.05)
                    block.updated_at = _utc_now()
                    if source_session_id and source_session_id not in block.source_sessions:
                        block.source_sessions.append(source_session_id)
                    self._persist_to_disk_sync()
                    logger.debug("Reinforced existing hyper block %s", block.block_id)
                    return block

            # Create new hyper block
            source_sessions = [source_session_id] if source_session_id else []
            new_block = HyperMemoryBlock(
                scope_id=scope_id,
                category=category,
                statement=statement,
                confidence=confidence,
                source_sessions=source_sessions,
            )
            self._hyper_blocks[new_block.block_id] = new_block
            self._persist_to_disk_sync()
            logger.info("Recorded new hyper block %s: %s", new_block.block_id, statement[:60])
            return new_block

    async def record_local_block(
        self,
        session_id: str,
        content: str,
        transient_tag: str = "task_context",
        task_id: str | None = None,
        verified_useful: bool = False,
        expires_at: datetime | None = None,
    ) -> LocalMemoryBlock:
        """Record a session-bound transient working memory entry."""
        async with self._lock:
            block = LocalMemoryBlock(
                session_id=session_id,
                content=content,
                transient_tag=transient_tag,
                task_id=task_id,
                verified_useful=verified_useful,
                expires_at=expires_at,
            )
            self._local_blocks[block.block_id] = block
            self._persist_to_disk_sync()
            logger.debug("Recorded local block %s for session %s", block.block_id, session_id)
            return block

    async def mark_local_verified(self, block_id: str, verified: bool = True) -> LocalMemoryBlock | None:
        """Mark a local memory block as verified useful for potential distillation."""
        async with self._lock:
            block = self._local_blocks.get(block_id)
            if not block:
                return None
            block.verified_useful = verified
            self._persist_to_disk_sync()
            return block

    async def get_active_blocks(
        self,
        session_id: str,
        scope_id: str,
    ) -> tuple[list[HyperMemoryBlock], list[LocalMemoryBlock]]:
        """Retrieve active hyper blocks for scope and unevaporated local blocks for session."""
        async with self._lock:
            now = _utc_now()
            hyper_active = [
                b for b in self._hyper_blocks.values()
                if b.scope_id == scope_id and b.status == "active"
            ]
            local_active = [
                b for b in self._local_blocks.values()
                if b.session_id == session_id
                and b.evaporation_state == EvaporationState.PENDING
                and (b.expires_at is None or b.expires_at > now)
            ]
            return hyper_active, local_active

    async def fuse_for_task(
        self,
        task_query: str,
        session_id: str,
        scope_id: str,
    ) -> AttentionFusionContext:
        """Score memory attention and assemble scoped prompt for current task."""
        hyper_active, local_active = await self.get_active_blocks(session_id, scope_id)
        return self._router.fuse(task_query, hyper_active, local_active)

    async def evaporate_and_consolidate(
        self,
        session_id: str,
        scope_id: str | None = None,
        auto_distill: bool = True,
    ) -> DistillationResult:
        """Evaporate transient session blocks and optionally distill verified entries to Hyper."""
        async with self._lock:
            now = _utc_now()
            session_local = [
                b for b in self._local_blocks.values()
                if b.session_id == session_id and b.evaporation_state == EvaporationState.PENDING
            ]

            distilled_hyper: list[HyperMemoryBlock] = []
            evaporated_ids: list[str] = []

            for lb in session_local:
                if auto_distill and lb.verified_useful:
                    target_scope = scope_id or "default"
                    # Synthesize macro rule from verified local experience
                    category = "tool_profile" if lb.transient_tag == "tool_override" else "preference"
                    hb = HyperMemoryBlock(
                        scope_id=target_scope,
                        category=category,
                        statement=lb.content,
                        confidence=0.85,
                        source_sessions=[session_id],
                    )
                    self._hyper_blocks[hb.block_id] = hb
                    distilled_hyper.append(hb)
                    logger.info("Distilled local block %s into hyper block %s", lb.block_id, hb.block_id)

                # Mark all processed local blocks as evaporated
                lb.evaporation_state = EvaporationState.EVAPORATED
                lb.evaporated_at = now
                evaporated_ids.append(lb.block_id)

            self._persist_to_disk_sync()

            return DistillationResult(
                session_id=session_id,
                distilled_hyper_blocks=distilled_hyper,
                evaporated_local_block_ids=evaporated_ids,
                retained_active_count=0,
            )

    def _persist_to_disk_sync(self) -> None:
        """Persist state to local storage if directory configured."""
        if not self._storage_dir:
            return
        try:
            hyper_file = self._storage_dir / "hyper_blocks.json"
            local_file = self._storage_dir / "local_blocks.json"

            hyper_data = [b.model_dump(mode="json") for b in self._hyper_blocks.values()]
            local_data = [b.model_dump(mode="json") for b in self._local_blocks.values()]

            hyper_file.write_text(json.dumps(hyper_data, indent=2), encoding="utf-8")
            local_file.write_text(json.dumps(local_data, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to persist dual-tier blocks to disk: %s", exc)

    def _load_from_disk(self) -> None:
        """Load state from local storage on startup."""
        if not self._storage_dir:
            return
        try:
            hyper_file = self._storage_dir / "hyper_blocks.json"
            if hyper_file.is_file():
                raw = hyper_file.read_text(encoding="utf-8")
                records = json.loads(raw)
                for item in records:
                    b = HyperMemoryBlock.model_validate(item)
                    self._hyper_blocks[b.block_id] = b

            local_file = self._storage_dir / "local_blocks.json"
            if local_file.is_file():
                raw = local_file.read_text(encoding="utf-8")
                records = json.loads(raw)
                for item in records:
                    b = LocalMemoryBlock.model_validate(item)
                    self._local_blocks[b.block_id] = b
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load dual-tier blocks from disk: %s", exc)
