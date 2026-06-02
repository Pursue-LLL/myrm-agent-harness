"""Tests for Tool Lifecycle Manager."""

import asyncio

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.tool_management import ToolLifecycleManager


class MockLifecycleTool(BaseTool):
    """Mock tool with lifecycle hooks."""

    name: str = "mock_lifecycle_tool"
    description: str = "A mock tool with lifecycle"

    # Allow extra attributes for tracking
    model_config = {"extra": "allow"}

    def __init__(self, name: str = "mock_lifecycle_tool") -> None:
        super().__init__()
        self.name = name
        self.ainit_called = False
        self.acleanup_called = False
        self.ainit_config = None
        self.fail_on_init = False
        self.fail_on_cleanup = False

    async def ainit(self, config: dict) -> None:
        """Initialize tool."""
        if self.fail_on_init:
            raise RuntimeError(f"{self.name}: Init failed")
        self.ainit_called = True
        self.ainit_config = config

    async def acleanup(self) -> None:
        """Cleanup tool."""
        if self.fail_on_cleanup:
            raise RuntimeError(f"{self.name}: Cleanup failed")
        self.acleanup_called = True

    def _run(self, query: str) -> str:
        """Run tool."""
        return f"Result from {self.name}"


class MockSimpleTool(BaseTool):
    """Mock tool without lifecycle hooks."""

    name: str = "mock_simple_tool"
    description: str = "A simple mock tool"

    def _run(self, query: str) -> str:
        """Run tool."""
        return "Simple result"


@pytest.fixture
def lifecycle_manager():
    """Create a ToolLifecycleManager instance."""
    return ToolLifecycleManager()


@pytest.fixture
def mock_config():
    """Create a mock RunnableConfig."""
    return {
        "configurable": {
            "context": {
                "session_id": "test_session_456",
            }
        }
    }


@pytest.mark.asyncio
async def test_initialize_tools_success(lifecycle_manager, mock_config):
    """Test successful initialization of lifecycle-aware tools."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")
    simple_tool = MockSimpleTool()

    tools = [tool1, simple_tool, tool2]

    await lifecycle_manager.initialize_tools(tools, mock_config)

    # Lifecycle tools should be initialized
    assert tool1.ainit_called
    assert tool2.ainit_called
    assert tool1.ainit_config == mock_config
    assert tool2.ainit_config == mock_config

    # Simple tool should not have ainit (no error)
    assert not hasattr(simple_tool, "ainit_called")

    # Check initialized set
    assert "tool1" in lifecycle_manager._initialized
    assert "tool2" in lifecycle_manager._initialized
    assert "mock_simple_tool" not in lifecycle_manager._initialized


@pytest.mark.asyncio
async def test_initialize_tools_rollback_on_failure(lifecycle_manager, mock_config):
    """Test rollback when tool initialization fails."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")
    tool3 = MockLifecycleTool("tool3")

    # tool2 will fail on init
    tool2.fail_on_init = True

    tools = [tool1, tool2, tool3]

    with pytest.raises(RuntimeError, match="tool2: Init failed"):
        await lifecycle_manager.initialize_tools(tools, mock_config)

    # tool1 should be initialized then cleaned up (rollback)
    assert tool1.ainit_called
    assert tool1.acleanup_called

    # tool2 failed, should not be cleaned up
    assert not tool2.ainit_called
    assert not tool2.acleanup_called

    # tool3 should not be initialized
    assert not tool3.ainit_called
    assert not tool3.acleanup_called

    # Check initialized set is empty after rollback
    assert len(lifecycle_manager._initialized) == 0


@pytest.mark.asyncio
async def test_cleanup_tools_success(lifecycle_manager, mock_config):
    """Test successful cleanup of lifecycle-aware tools."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")
    simple_tool = MockSimpleTool()

    tools = [tool1, simple_tool, tool2]

    # Initialize first
    await lifecycle_manager.initialize_tools(tools, mock_config)

    # Now cleanup
    await lifecycle_manager.cleanup_tools(tools)

    # Lifecycle tools should be cleaned up
    assert tool1.acleanup_called
    assert tool2.acleanup_called

    # Simple tool should not have acleanup (no error)
    assert not hasattr(simple_tool, "acleanup_called")

    # Check initialized set is empty after cleanup
    assert len(lifecycle_manager._initialized) == 0


@pytest.mark.asyncio
async def test_cleanup_tools_reverse_order(lifecycle_manager, mock_config):
    """Test cleanup happens in reverse order of initialization."""
    cleanup_order = []

    class OrderTrackingTool(MockLifecycleTool):
        async def acleanup(self) -> None:
            """Track cleanup order."""
            cleanup_order.append(self.name)
            await super().acleanup()

    tool1 = OrderTrackingTool("tool1")
    tool2 = OrderTrackingTool("tool2")
    tool3 = OrderTrackingTool("tool3")

    tools = [tool1, tool2, tool3]

    await lifecycle_manager.initialize_tools(tools, mock_config)
    await lifecycle_manager.cleanup_tools(tools)

    # Cleanup should be in reverse order
    assert cleanup_order == ["tool3", "tool2", "tool1"]


@pytest.mark.asyncio
async def test_cleanup_tools_best_effort(lifecycle_manager, mock_config):
    """Test cleanup continues even if one tool fails."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")
    tool3 = MockLifecycleTool("tool3")

    # tool2 will fail on cleanup
    tool2.fail_on_cleanup = True

    tools = [tool1, tool2, tool3]

    await lifecycle_manager.initialize_tools(tools, mock_config)

    # Cleanup should not raise, even though tool2 fails
    await lifecycle_manager.cleanup_tools(tools)

    # tool1 and tool3 should still be cleaned up
    assert tool1.acleanup_called
    assert tool3.acleanup_called

    # tool2 should have attempted cleanup (but failed)
    # Note: We can't easily verify the failure was logged, but we can verify
    # that the failure didn't prevent other tools from cleaning up


@pytest.mark.asyncio
async def test_cleanup_tools_thread_safe(lifecycle_manager, mock_config):
    """Test cleanup is thread-safe (concurrent calls)."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")

    tools = [tool1, tool2]

    await lifecycle_manager.initialize_tools(tools, mock_config)

    # Attempt concurrent cleanup (should be protected by lock)
    await asyncio.gather(
        lifecycle_manager.cleanup_tools(tools),
        lifecycle_manager.cleanup_tools(tools),
        lifecycle_manager.cleanup_tools(tools),
    )

    # Tools should only be cleaned up once (idempotent)
    # Note: This test mainly verifies no exceptions are raised


@pytest.mark.asyncio
async def test_cleanup_tools_idempotent(lifecycle_manager, mock_config):
    """Test cleanup can be called multiple times safely."""
    tool1 = MockLifecycleTool("tool1")

    tools = [tool1]

    await lifecycle_manager.initialize_tools(tools, mock_config)

    # First cleanup
    await lifecycle_manager.cleanup_tools(tools)
    assert tool1.acleanup_called

    # Reset flag
    tool1.acleanup_called = False

    # Second cleanup should skip (tool not in initialized set)
    await lifecycle_manager.cleanup_tools(tools)
    assert not tool1.acleanup_called  # Should not be called again


@pytest.mark.asyncio
async def test_cleanup_tools_without_init(lifecycle_manager, mock_config):
    """Test cleanup on non-initialized tools is safe."""
    tool1 = MockLifecycleTool("tool1")

    tools = [tool1]

    # Cleanup without init should not raise
    await lifecycle_manager.cleanup_tools(tools)

    # Tool should not be cleaned up (never initialized)
    assert not tool1.acleanup_called


@pytest.mark.asyncio
async def test_initialize_tools_idempotent(lifecycle_manager, mock_config):
    """Test initialize_tools is idempotent (skips already-initialized tools)."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")

    tools = [tool1, tool2]

    # First initialization
    await lifecycle_manager.initialize_tools(tools, mock_config)
    assert tool1.ainit_called
    assert tool2.ainit_called

    # Reset flags
    tool1.ainit_called = False
    tool2.ainit_called = False

    # Second initialization should skip both tools (already in _initialized set)
    await lifecycle_manager.initialize_tools(tools, mock_config)
    assert not tool1.ainit_called  # Should not be called again
    assert not tool2.ainit_called  # Should not be called again


@pytest.mark.asyncio
async def test_initialize_tools_partial_idempotent(lifecycle_manager, mock_config):
    """Test initialize_tools initializes only new tools (partial idempotency)."""
    tool1 = MockLifecycleTool("tool1")
    tool2 = MockLifecycleTool("tool2")
    tool3 = MockLifecycleTool("tool3")

    # First initialization: tool1 and tool2
    await lifecycle_manager.initialize_tools([tool1, tool2], mock_config)
    assert tool1.ainit_called
    assert tool2.ainit_called

    # Reset flags
    tool1.ainit_called = False
    tool2.ainit_called = False

    # Second initialization: tool1, tool2, tool3
    # tool1 and tool2 should be skipped, only tool3 should be initialized
    await lifecycle_manager.initialize_tools([tool1, tool2, tool3], mock_config)
    assert not tool1.ainit_called  # Skipped
    assert not tool2.ainit_called  # Skipped
    assert tool3.ainit_called  # Newly initialized


@pytest.mark.asyncio
async def test_cleanup_timeout(lifecycle_manager, mock_config):
    """Test cleanup timeout prevents hanging."""

    class SlowCleanupTool(MockLifecycleTool):
        async def acleanup(self) -> None:
            """Cleanup that takes too long."""
            await asyncio.sleep(60)  # Simulate slow cleanup
            await super().acleanup()

    tool1 = SlowCleanupTool("tool1")
    tools = [tool1]

    # Initialize first
    await lifecycle_manager.initialize_tools(tools, mock_config)

    # Cleanup should timeout (default timeout is 30s, but we can use a shorter one for testing)
    short_timeout_manager = ToolLifecycleManager(cleanup_timeout=0.1)
    short_timeout_manager._initialized.add("tool1")  # Mark as initialized

    # Cleanup should complete despite timeout (best-effort)
    await short_timeout_manager.cleanup_tools(tools)

    # Tool should be removed from initialized set even though cleanup timed out
    assert "tool1" not in short_timeout_manager._initialized
