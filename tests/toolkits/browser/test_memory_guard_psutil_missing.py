"""Tests for MemoryGuard when psutil is missing or behavior is cached."""

from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.config import MemoryGuardConfig
from myrm_agent_harness.toolkits.browser.pool.memory_guard import MemoryGuard


def test_memory_guard_warning_when_psutil_missing(caplog: pytest.LogCaptureFixture) -> None:
    """When psutil is unavailable, enabled guard logs warning and disables checks."""
    import logging

    config = MemoryGuardConfig(enabled=True)

    with (
        patch("myrm_agent_harness.toolkits.browser.pool.memory_guard.psutil", None),
        caplog.at_level(logging.WARNING),
    ):
        guard = MemoryGuard(config)

        assert "Memory guard enabled but psutil not installed" in caplog.text
        assert "uv sync --all-extras" in caplog.text
        assert guard._enabled is False


@pytest.mark.asyncio
async def test_memory_guard_cached_failure_fast_path() -> None:
    """Within check_interval, cached high memory result rejects without extra psutil calls."""
    config = MemoryGuardConfig(enabled=True, max_memory_percent=50.0, check_interval=1.0)

    with patch("myrm_agent_harness.toolkits.browser.pool.memory_guard.psutil") as mock_psutil:
        mock_psutil.virtual_memory.return_value.percent = 80.0

        guard = MemoryGuard(config)

        with pytest.raises(MemoryError, match="Memory usage 80.0% exceeds threshold 50.0%"):
            await guard.check_memory()

        call_count_before = mock_psutil.virtual_memory.call_count

        with pytest.raises(MemoryError, match="Memory usage 80.0% exceeds threshold 50.0%"):
            await guard.check_memory()

        assert mock_psutil.virtual_memory.call_count == call_count_before
