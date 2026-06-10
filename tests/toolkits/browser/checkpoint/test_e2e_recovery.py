"""End-to-end test for checkpoint auto-recovery flow.

Verifies complete integration:
1. IncrementalSessionCheckpointer auto-registers threads
2. ThreadStore tracks thread lifecycle
3. AutoRecoveryOrchestrator discovers incomplete tasks
4. Session state restoration works correctly
"""

import pytest
from langgraph.checkpoint.base import Checkpoint

from myrm_agent_harness.toolkits.browser.checkpoint import (
    AutoRecoveryOrchestrator,
    IncrementalSessionCheckpointer,
    ThreadStore,
    create_thread_tables,
)


@pytest.fixture
async def test_env(tmp_path):
    """Create complete test environment."""
    import aiosqlite
    from langgraph.checkpoint.memory import MemorySaver

    # Setup database
    db_path = tmp_path / "test_recovery.db"
    conn = await aiosqlite.connect(str(db_path))

    # Create thread registry table
    await create_thread_tables(conn)
    thread_store = ThreadStore(conn)

    # Create checkpointer
    base_saver = MemorySaver()
    checkpointer = IncrementalSessionCheckpointer(base_saver, thread_store=thread_store)

    # Create orchestrator
    orchestrator = AutoRecoveryOrchestrator(checkpointer, thread_store)
    await orchestrator.initialize()

    yield {
        "conn": conn,
        "thread_store": thread_store,
        "checkpointer": checkpointer,
        "orchestrator": orchestrator,
    }

    await conn.close()


class TestE2ERecovery:
    """End-to-end recovery tests."""

    @pytest.mark.asyncio
    async def test_auto_register_on_checkpoint(self, test_env):
        """Test that threads are auto-registered on first checkpoint."""
        checkpointer = test_env["checkpointer"]
        thread_store = test_env["thread_store"]

        # Save checkpoint with browser metadata
        config = {"configurable": {"thread_id": "test-thread-1", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts=1000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata = {
            "browser": {
                "session_hash": "hash-1",
                "current_url": "https://example.com",
                "session_domain": "example.com",
            }
        }

        await checkpointer.aput(config, checkpoint, metadata, {})

        # Verify thread was registered
        record = await thread_store.get("test-thread-1")
        assert record is not None
        assert record.status == "active"

    @pytest.mark.asyncio
    async def test_update_activity_on_subsequent_checkpoints(self, test_env):
        """Test that thread activity is updated on each checkpoint."""
        checkpointer = test_env["checkpointer"]
        thread_store = test_env["thread_store"]

        config = {"configurable": {"thread_id": "test-thread-2", "checkpoint_ns": ""}}

        # First checkpoint
        checkpoint1 = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts=1000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata1 = {
            "browser": {
                "session_hash": "hash-1",
                "current_url": "https://example.com/page1",
            }
        }
        await checkpointer.aput(config, checkpoint1, metadata1, {})

        # Second checkpoint
        checkpoint2 = Checkpoint(
            v=1,
            id="checkpoint-2",
            ts=2000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata2 = {
            "browser": {
                "session_hash": "hash-2",
                "current_url": "https://example.com/page2",
            }
        }
        await checkpointer.aput(config, checkpoint2, metadata2, {})

        # Verify thread exists and activity was updated
        record = await thread_store.get("test-thread-2")
        assert record is not None
        assert record.status == "active"

    @pytest.mark.asyncio
    async def test_orchestrator_finds_active_threads(self, test_env):
        """Test that orchestrator can find active threads."""
        checkpointer = test_env["checkpointer"]
        orchestrator = test_env["orchestrator"]

        # Create some active threads via checkpoints
        for i in range(3):
            config = {"configurable": {"thread_id": f"thread-{i}", "checkpoint_ns": ""}}
            checkpoint = Checkpoint(
                v=1,
                id=f"checkpoint-{i}",
                ts=1000000 + i * 1000,
                channel_values={"messages": []},
                channel_versions={},
                versions_seen={},
                pending_sends=[],
            )
            metadata = {
                "browser": {
                    "session_hash": f"hash-{i}",
                    "current_url": f"https://example.com/page{i}",
                }
            }
            await checkpointer.aput(config, checkpoint, metadata, {})

        # Find incomplete tasks
        contexts = await orchestrator.find_incomplete_tasks()

        # Should find all 3 threads
        assert len(contexts) == 3
        thread_ids = [ctx.thread_id for ctx in contexts]
        assert "thread-0" in thread_ids
        assert "thread-1" in thread_ids
        assert "thread-2" in thread_ids

    @pytest.mark.asyncio
    async def test_completed_threads_not_recovered(self, test_env):
        """Test that completed threads are not recovered."""
        checkpointer = test_env["checkpointer"]
        thread_store = test_env["thread_store"]
        orchestrator = test_env["orchestrator"]

        # Create active thread
        config = {"configurable": {"thread_id": "thread-complete", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts=1000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata = {
            "browser": {
                "session_hash": "hash-1",
                "current_url": "https://example.com",
            }
        }
        await checkpointer.aput(config, checkpoint, metadata, {})

        # Mark as completed
        await thread_store.mark_completed("thread-complete")

        # Find incomplete tasks
        contexts = await orchestrator.find_incomplete_tasks()

        # Should not find completed thread
        thread_ids = [ctx.thread_id for ctx in contexts]
        assert "thread-complete" not in thread_ids

    @pytest.mark.asyncio
    async def test_recovery_context_contains_metadata(self, test_env):
        """Test that recovery context contains full checkpoint metadata."""
        checkpointer = test_env["checkpointer"]
        orchestrator = test_env["orchestrator"]

        # Create checkpoint with rich metadata
        config = {"configurable": {"thread_id": "thread-meta", "checkpoint_ns": ""}}
        checkpoint = Checkpoint(
            v=1,
            id="checkpoint-meta",
            ts=1000000,
            channel_values={
                "messages": [
                    {"role": "user", "content": "Visit example.com"},
                    {"role": "assistant", "content": "[10 refs | ~50 tokens | url: https://example.com/result]"},
                ]
            },
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata = {
            "browser": {
                "session_hash": "hash-meta",
                "current_url": "https://example.com/result",
                "session_domain": "example.com",
                "task_counters": {
                    "clicks": 5,
                    "navigations": 2,
                },
            }
        }
        await checkpointer.aput(config, checkpoint, metadata, {})

        # Find tasks
        contexts = await orchestrator.find_incomplete_tasks()

        # Verify metadata extraction
        assert len(contexts) == 1
        ctx = contexts[0]
        assert ctx.thread_id == "thread-meta"
        assert ctx.checkpoint_id == "checkpoint-meta"
        assert ctx.metadata.get("current_url") == "https://example.com/result"
        assert ctx.metadata.get("session_domain") == "example.com"
        assert ctx.metadata.get("task_counters", {}).get("clicks") == 5

    @pytest.mark.asyncio
    async def test_incremental_save_with_thread_tracking(self, test_env):
        """Test that incremental save works with thread tracking."""
        checkpointer = test_env["checkpointer"]
        thread_store = test_env["thread_store"]

        config = {"configurable": {"thread_id": "thread-incremental", "checkpoint_ns": ""}}

        # First checkpoint
        checkpoint1 = Checkpoint(
            v=1,
            id="checkpoint-1",
            ts=1000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata1 = {
            "browser": {
                "session_hash": "hash-1",
                "current_url": "https://example.com",
            }
        }
        await checkpointer.aput(config, checkpoint1, metadata1, {})

        # Second checkpoint with SAME hash (should skip Session Vault save)
        checkpoint2 = Checkpoint(
            v=1,
            id="checkpoint-2",
            ts=2000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata2 = {
            "browser": {
                "session_hash": "hash-1",  # Same hash
                "current_url": "https://example.com",
            }
        }
        await checkpointer.aput(config, checkpoint2, metadata2, {})

        # Third checkpoint with DIFFERENT hash
        checkpoint3 = Checkpoint(
            v=1,
            id="checkpoint-3",
            ts=3000000,
            channel_values={"messages": []},
            channel_versions={},
            versions_seen={},
            pending_sends=[],
        )
        metadata3 = {
            "browser": {
                "session_hash": "hash-2",  # Different hash
                "current_url": "https://example.com/page2",
            }
        }
        await checkpointer.aput(config, checkpoint3, metadata3, {})

        # Verify metrics
        metrics = checkpointer.metrics
        assert metrics.vault_save_count == 2  # First and third
        assert metrics.save_skipped_count == 1  # Second

        # Verify thread registry
        record = await thread_store.get("thread-incremental")
        assert record is not None
        assert record.status == "active"
