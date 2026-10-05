"""Unit tests for the Hyper and Local dual-tier memory block engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.dual_tier.attention import MemoryAttentionRouter
from myrm_agent_harness.toolkits.memory.dual_tier.engine import DualTierBlockEngine
from myrm_agent_harness.toolkits.memory.dual_tier.models import (
    HyperMemoryBlock,
    LocalMemoryBlock,
)
from myrm_agent_harness.toolkits.memory.types import EvaporationState


class TestDualTierModels:
    def test_hyper_memory_block_defaults(self) -> None:
        block = HyperMemoryBlock(
            scope_id="user_123",
            statement="Always prefer uv and bun for build tasks",
        )
        assert block.block_id.startswith("hyper_")
        assert block.confidence == 0.9
        assert block.version == 1
        assert block.reinforcement_count == 1
        assert block.status == "active"
        assert block.created_at.tzinfo is not None

    def test_local_memory_block_defaults(self) -> None:
        block = LocalMemoryBlock(
            session_id="sess_abc",
            content="Temporary port 8080 used for debugging",
        )
        assert block.block_id.startswith("local_")
        assert block.evaporation_state == EvaporationState.PENDING
        assert block.verified_useful is False
        assert block.expires_at is None


class TestMemoryAttentionRouter:
    def test_attention_scoring_and_filtering(self) -> None:
        router = MemoryAttentionRouter(min_activation_threshold=0.2)

        hyper = HyperMemoryBlock(
            scope_id="user_1",
            statement="Always use pytest for testing Python code",
            category="preference",
            confidence=0.95,
        )
        local = LocalMemoryBlock(
            session_id="s1",
            content="Running pytest with -k test_auth for quick inspection",
            transient_tag="tool_override",
            verified_useful=True,
        )

        query = "Please run pytest on the codebase"
        result = router.fuse(query, [hyper], [local])

        assert hyper.block_id in result.hyper_weights
        assert local.block_id in result.local_weights
        assert result.hyper_weights[hyper.block_id] > 0.4
        assert result.local_weights[local.block_id] > 0.4

        # Verify structured prompt contains both sections with proper isolation warnings
        assert "[Global Mental Models & Long-term Preferences (Hyper Memory)]" in result.formatted_prompt
        assert "[Active Session Transient Context (Local Memory)]" in result.formatted_prompt
        assert "DO NOT treat them as global rules" in result.formatted_prompt

    def test_irrelevant_memory_filtered_out(self) -> None:
        router = MemoryAttentionRouter(min_activation_threshold=0.3)

        hyper = HyperMemoryBlock(
            scope_id="user_1",
            statement="Prefer PostgreSQL over MySQL for relational storage",
            confidence=0.5,
        )
        local = LocalMemoryBlock(
            session_id="s1",
            content="Investigating Docker bridge network latency",
        )

        # Unrelated query
        result = router.fuse("Write a simple CSS style for the header", [hyper], [local])
        assert len(result.hyper_blocks) == 0
        assert len(result.local_blocks) == 0
        assert result.formatted_prompt == ""


class TestDualTierBlockEngine:
    @pytest.mark.asyncio
    async def test_hyper_block_reinforcement(self) -> None:
        engine = DualTierBlockEngine()

        b1 = await engine.record_hyper_block(
            scope_id="user_1",
            statement="Always format with ruff",
            confidence=0.85,
            source_session_id="sess_1",
        )
        assert b1.reinforcement_count == 1
        assert b1.confidence == 0.85

        # Recording exact same statement reinforces the existing block
        b2 = await engine.record_hyper_block(
            scope_id="user_1",
            statement="always format with ruff",  # case-insensitive match
            source_session_id="sess_2",
        )
        assert b2.block_id == b1.block_id
        assert b2.reinforcement_count == 2
        assert b2.confidence == 0.90
        assert "sess_1" in b2.source_sessions
        assert "sess_2" in b2.source_sessions

    @pytest.mark.asyncio
    async def test_session_isolation(self) -> None:
        engine = DualTierBlockEngine()

        await engine.record_local_block(
            session_id="sess_A",
            content="Temp variable foo=bar",
        )
        await engine.record_local_block(
            session_id="sess_B",
            content="Temp variable baz=qux",
        )

        # Session A only sees its own local blocks
        _, local_a = await engine.get_active_blocks("sess_A", "user_1")
        assert len(local_a) == 1
        assert local_a[0].content == "Temp variable foo=bar"

        # Session B only sees its own local blocks
        _, local_b = await engine.get_active_blocks("sess_B", "user_1")
        assert len(local_b) == 1
        assert local_b[0].content == "Temp variable baz=qux"

    @pytest.mark.asyncio
    async def test_evaporation_discards_unverified_local_blocks(self) -> None:
        engine = DualTierBlockEngine()

        await engine.record_local_block(
            session_id="sess_ephemeral",
            content="One-off curl command executed for test",
            verified_useful=False,
        )

        res = await engine.evaporate_and_consolidate("sess_ephemeral", scope_id="user_1")
        assert len(res.evaporated_local_block_ids) == 1
        assert len(res.distilled_hyper_blocks) == 0

        # Subsequent retrieval finds 0 active local blocks for this session
        _, local_active = await engine.get_active_blocks("sess_ephemeral", "user_1")
        assert len(local_active) == 0

    @pytest.mark.asyncio
    async def test_distillation_promotes_verified_useful_block(self) -> None:
        engine = DualTierBlockEngine()

        local_block = await engine.record_local_block(
            session_id="sess_learning",
            content="When installing complex wheel packages, pass --no-cache-dir flag",
            transient_tag="tool_override",
            verified_useful=True,
        )

        res = await engine.evaporate_and_consolidate("sess_learning", scope_id="team_repo")
        assert len(res.evaporated_local_block_ids) == 1
        assert len(res.distilled_hyper_blocks) == 1

        distilled = res.distilled_hyper_blocks[0]
        assert distilled.statement == local_block.content
        assert distilled.scope_id == "team_repo"
        assert distilled.category == "tool_profile"
        assert "sess_learning" in distilled.source_sessions

        # Verify new session inherits this distilled hyper block
        hyper_active, _ = await engine.get_active_blocks("sess_fresh", "team_repo")
        assert any(b.statement == local_block.content for b in hyper_active)

    @pytest.mark.asyncio
    async def test_disk_persistence_and_reload(self, tmp_path: Path) -> None:
        storage_dir = tmp_path / "dual_tier_store"

        engine1 = DualTierBlockEngine(storage_dir=storage_dir)
        await engine1.record_hyper_block(
            scope_id="user_persistent",
            statement="Strictly use Python 3.12+ features",
        )
        await engine1.record_local_block(
            session_id="sess_p",
            content="Active test plan running in background",
        )

        # Create new engine pointing to same storage directory
        engine2 = DualTierBlockEngine(storage_dir=storage_dir)
        hyper_blocks, local_blocks = await engine2.get_active_blocks("sess_p", "user_persistent")

        assert len(hyper_blocks) == 1
        assert hyper_blocks[0].statement == "Strictly use Python 3.12+ features"
        assert len(local_blocks) == 1
        assert local_blocks[0].content == "Active test plan running in background"
