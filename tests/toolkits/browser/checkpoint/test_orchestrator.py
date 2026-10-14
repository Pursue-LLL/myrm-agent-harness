"""Unit tests for recovery orchestrators."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint import (
    AutoRecoveryOrchestrator,
    IncrementalSessionCheckpointer,
    ParallelRecoveryOrchestrator,
    ThreadStore,
)
from myrm_agent_harness.toolkits.browser.checkpoint.orchestrator import RecoveryContext


class TestAutoRecoveryOrchestrator:
    """Test AutoRecoveryOrchestrator."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies."""
        checkpointer = Mock(spec=IncrementalSessionCheckpointer)
        thread_store = Mock(spec=ThreadStore)

        return {
            "checkpointer": checkpointer,
            "thread_store": thread_store,
        }

    @pytest.mark.asyncio
    async def test_initialize_once(self, mock_deps):
        """Test that initialize can only be called once."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
        )

        await orchestrator.initialize()
        assert orchestrator._initialized is True

        # Second call should log warning but not fail
        await orchestrator.initialize()

    @pytest.mark.asyncio
    async def test_find_incomplete_before_init_raises(self, mock_deps):
        """Test that find_incomplete_tasks raises if not initialized."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
        )

        with pytest.raises(RuntimeError, match="not initialized"):
            await orchestrator.find_incomplete_tasks()

    @pytest.mark.asyncio
    async def test_recover_session_with_vault_and_url(self, mock_deps):
        """Test recover_session with SessionVault and URL navigation."""
        vault = Mock()
        mock_entry = Mock(storage_state={"cookies": [{"name": "token", "value": "xyz"}]})
        vault.load = AsyncMock(return_value=mock_entry)

        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            session_vault=vault,
        )
        await orchestrator.initialize()

        # Create recovery context
        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={
                "session_domain": "example.com",
                "current_url": "https://example.com/restored",
            },
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        # Mock BrowserSession
        browser_session = Mock()
        browser_session.new_tab = AsyncMock()
        browser_session.snapshot = AsyncMock()

        with patch(
            "myrm_agent_harness.toolkits.browser.checkpoint.session_state.apply_storage_state",
            new_callable=AsyncMock,
        ) as mock_apply:
            result = await orchestrator.recover_session(ctx, browser_session)

        assert result is True
        vault.load.assert_called_once_with("example.com")
        mock_apply.assert_called_once_with(browser_session, mock_entry.storage_state)
        browser_session.new_tab.assert_called_once_with("https://example.com/restored")
        browser_session.snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_session_without_vault(self, mock_deps):
        """Test recover_session without SessionVault."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            session_vault=None,
        )
        await orchestrator.initialize()

        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={"current_url": "https://example.com/page"},
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        browser_session = Mock()
        browser_session.new_tab = AsyncMock()
        browser_session.snapshot = AsyncMock()

        result = await orchestrator.recover_session(ctx, browser_session)

        assert result is True
        browser_session.new_tab.assert_called_once_with("https://example.com/page")

    @pytest.mark.asyncio
    async def test_recover_session_no_url_no_vault(self, mock_deps):
        """Test recover_session with no URL and no vault (only snapshot)."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
        )
        await orchestrator.initialize()

        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={},
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        browser_session = Mock()
        browser_session.new_tab = AsyncMock()
        browser_session.snapshot = AsyncMock()

        result = await orchestrator.recover_session(ctx, browser_session)

        assert result is True
        browser_session.new_tab.assert_not_called()
        browser_session.snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_session_retry_on_failure(self, mock_deps):
        """Test that recover_session retries on failure."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            max_retries=2,
            retry_delay_ms=100,
        )
        await orchestrator.initialize()

        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={"current_url": "https://example.com"},
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        # Mock BrowserSession that fails first 2 times, succeeds on 3rd
        browser_session = Mock()
        browser_session.new_tab = AsyncMock(side_effect=[RuntimeError("Fail 1"), RuntimeError("Fail 2"), None])
        browser_session.snapshot = AsyncMock()

        result = await orchestrator.recover_session(ctx, browser_session)

        assert result is True
        assert browser_session.new_tab.call_count == 3

    @pytest.mark.asyncio
    async def test_recover_session_final_failure(self, mock_deps):
        """Test that recover_session returns False after max retries."""
        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            max_retries=1,
            retry_delay_ms=50,
        )
        await orchestrator.initialize()

        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={"current_url": "https://example.com"},
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        browser_session = Mock()
        browser_session.new_tab = AsyncMock(side_effect=RuntimeError("Permanent failure"))
        browser_session.snapshot = AsyncMock()

        result = await orchestrator.recover_session(ctx, browser_session)

        assert result is False
        assert browser_session.new_tab.call_count == 2  # Initial + 1 retry
        assert orchestrator._metrics.recovery_failures == 1

    @pytest.mark.asyncio
    async def test_recover_session_vault_not_found(self, mock_deps):
        """Test recover_session when vault entry doesn't exist."""
        vault = Mock()
        vault.load = AsyncMock(return_value=None)

        orchestrator = AutoRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            session_vault=vault,
        )
        await orchestrator.initialize()

        ctx = RecoveryContext(
            thread_id="test-thread",
            checkpoint_id="cp-1",
            metadata={
                "session_domain": "example.com",
                "current_url": "https://example.com/page",
            },
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )

        browser_session = Mock()
        browser_session.new_tab = AsyncMock()
        browser_session.snapshot = AsyncMock()

        result = await orchestrator.recover_session(ctx, browser_session)

        assert result is True
        vault.load.assert_called_once_with("example.com")
        browser_session.new_tab.assert_called_once()


class TestParallelRecoveryOrchestrator:
    """Test ParallelRecoveryOrchestrator."""

    @pytest.fixture
    def mock_deps(self):
        """Create mock dependencies."""
        checkpointer = Mock(spec=IncrementalSessionCheckpointer)
        thread_store = Mock(spec=ThreadStore)
        browser_pool = Mock()

        return {
            "checkpointer": checkpointer,
            "thread_store": thread_store,
            "browser_pool": browser_pool,
        }

    @pytest.mark.asyncio
    async def test_initialization(self, mock_deps):
        """Test ParallelRecoveryOrchestrator initialization."""
        orchestrator = ParallelRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            mock_deps["browser_pool"],
            max_concurrent_recoveries=5,
        )

        await orchestrator.initialize()

        assert orchestrator._max_concurrent == 5
        assert orchestrator._base_orchestrator is not None

    @pytest.mark.asyncio
    async def test_recover_all_empty_list(self, mock_deps):
        """Test parallel recovery with empty task list."""
        orchestrator = ParallelRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            mock_deps["browser_pool"],
        )
        await orchestrator.initialize()

        results = await orchestrator.recover_all([])

        assert results["success_count"] == 0
        assert results["failure_count"] == 0
        assert results["total_count"] == 0

    @pytest.mark.asyncio
    async def test_recover_all_gives_each_task_an_agent_context_session(self, mock_deps):
        """Recovery sessions are built with the real ContextType, not its string name."""
        from myrm_agent_harness.toolkits.browser.pool import ContextType

        orchestrator = ParallelRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            AsyncMock(),  # session.close() awaits the pool to release the context
        )
        await orchestrator.initialize()
        context = RecoveryContext(
            thread_id="thread-1",
            checkpoint_id="cp-1",
            metadata=Mock(),
            messages=[],
            last_updated_at=datetime.now().timestamp(),
        )
        recovered_sessions = []

        async def recover_session(_ctx, session):
            recovered_sessions.append(session)
            return True

        with (
            patch.object(orchestrator._base_orchestrator, "find_incomplete_tasks", AsyncMock(return_value=[context])),
            patch.object(orchestrator._base_orchestrator, "recover_session", side_effect=recover_session),
        ):
            summary = await orchestrator.recover_all()

        assert summary["success_count"] == 1
        assert summary["failure_count"] == 0
        assert [session._context_type for session in recovered_sessions] == [ContextType.AGENT]

    @pytest.mark.asyncio
    async def test_recover_all_counts_declined_and_raised_recoveries_as_failures(self, mock_deps):
        """A recovery that returns False and one that raises both land in failed_threads."""
        orchestrator = ParallelRecoveryOrchestrator(
            mock_deps["checkpointer"],
            mock_deps["thread_store"],
            AsyncMock(),
        )
        await orchestrator.initialize()
        contexts = [
            RecoveryContext(
                thread_id=thread_id,
                checkpoint_id="cp",
                metadata=Mock(),
                messages=[],
                last_updated_at=datetime.now().timestamp(),
            )
            for thread_id in ("recovered", "declined", "raised")
        ]

        async def recover_session(ctx, _session):
            if ctx.thread_id == "raised":
                raise RuntimeError("boom")
            return ctx.thread_id == "recovered"

        with (
            patch.object(orchestrator._base_orchestrator, "find_incomplete_tasks", AsyncMock(return_value=contexts)),
            patch.object(orchestrator._base_orchestrator, "recover_session", side_effect=recover_session),
        ):
            summary = await orchestrator.recover_all()

        assert summary["success_count"] == 1
        assert summary["failure_count"] == 2
        assert summary["total_count"] == 3
        assert sorted(summary["failed_threads"]) == ["declined", "raised"]
