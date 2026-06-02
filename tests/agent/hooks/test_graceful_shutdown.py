"""Tests for GracefulShutdownManager."""

import asyncio
import signal

import pytest

from myrm_agent_harness.agent.hooks.graceful_shutdown import GracefulShutdownManager, get_shutdown_manager


@pytest.fixture
def shutdown_manager():
    """Create a fresh GracefulShutdownManager instance for each test."""
    # Reset singleton
    GracefulShutdownManager._instance = None
    return GracefulShutdownManager.get_instance()


def test_singleton_pattern(shutdown_manager):
    """Test that GracefulShutdownManager is a singleton."""
    manager1 = GracefulShutdownManager.get_instance()
    manager2 = get_shutdown_manager()
    assert manager1 is shutdown_manager
    assert manager2 is shutdown_manager


def test_register_signals_idempotent(shutdown_manager):
    """Test that register_signals is idempotent."""
    shutdown_manager.register_signals()
    assert shutdown_manager._registered is True

    # Call again should not raise error
    shutdown_manager.register_signals()
    assert shutdown_manager._registered is True


def test_register_checkpoint_callback(shutdown_manager):
    """Test checkpoint callback registration."""
    callback_count = 0

    def dummy_callback():
        nonlocal callback_count
        callback_count += 1

    shutdown_manager.register_checkpoint_callback(dummy_callback)
    assert len(shutdown_manager._shutdown_callbacks) == 1

    # Manually trigger signal handler
    shutdown_manager._handle_signal(signal.SIGTERM, None)
    assert callback_count == 1


def test_shutdown_event(shutdown_manager):
    """Test shutdown event is set when signal received."""
    assert not shutdown_manager.is_shutting_down()

    shutdown_manager._handle_signal(signal.SIGTERM, None)
    assert shutdown_manager.is_shutting_down()


def test_multiple_callbacks_exception_safety(shutdown_manager):
    """Test that exception in one callback doesn't affect others."""
    callback1_count = 0
    callback2_count = 0

    def callback1():
        nonlocal callback1_count
        callback1_count += 1

    def callback2():
        raise ValueError("Callback2 error")

    def callback3():
        nonlocal callback2_count
        callback2_count += 1

    shutdown_manager.register_checkpoint_callback(callback1)
    shutdown_manager.register_checkpoint_callback(callback2)
    shutdown_manager.register_checkpoint_callback(callback3)

    # Trigger signal
    shutdown_manager._handle_signal(signal.SIGINT, None)

    # Both callback1 and callback3 should have been called
    assert callback1_count == 1
    assert callback2_count == 1


@pytest.mark.asyncio
async def test_wait_for_shutdown(shutdown_manager):
    """Test wait_for_shutdown blocks until signal received."""
    shutdown_triggered = False

    async def wait_task():
        nonlocal shutdown_triggered
        await shutdown_manager.wait_for_shutdown()
        shutdown_triggered = True

    # Start wait task
    task = asyncio.create_task(wait_task())

    # Wait briefly
    await asyncio.sleep(0.1)
    assert not shutdown_triggered

    # Trigger shutdown
    shutdown_manager._handle_signal(signal.SIGTERM, None)

    # Wait should complete
    await asyncio.wait_for(task, timeout=1.0)
    assert shutdown_triggered
