"""Tests for storage quota protocol."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.quota.errors import QuotaExceededError


class MockQuotaChecker:
    """Mock implementation of StorageQuotaChecker for testing."""

    def __init__(self, quota_bytes: int = 1024000) -> None:
        """Initialize mock quota checker.

        Args:
            quota_bytes: Total quota in bytes (default 1MB)
        """
        self.quota_bytes = quota_bytes
        self.used_bytes: dict[str, int] = {}

    async def check_write_allowed(self, session_id: str, write_size_bytes: int) -> bool:
        """Check if write is allowed within quota."""
        current_usage = self.used_bytes.get(session_id, 0)
        return (current_usage + write_size_bytes) <= self.quota_bytes

    async def get_remaining_quota(self, session_id: str) -> int:
        """Get remaining quota in bytes."""
        current_usage = self.used_bytes.get(session_id, 0)
        return max(0, self.quota_bytes - current_usage)

    def record_write(self, session_id: str, write_size_bytes: int) -> None:
        """Record a write operation (for testing)."""
        self.used_bytes[session_id] = self.used_bytes.get(session_id, 0) + write_size_bytes


class TestQuotaProtocol:
    """Test quota protocol implementation."""

    @pytest.mark.asyncio
    async def test_check_write_allowed_within_quota(self) -> None:
        """Test write is allowed when within quota."""
        checker = MockQuotaChecker(quota_bytes=1024000)  # 1MB
        assert await checker.check_write_allowed("session1", 500000)  # 500KB

    @pytest.mark.asyncio
    async def test_check_write_allowed_exceeds_quota(self) -> None:
        """Test write is denied when exceeding quota."""
        checker = MockQuotaChecker(quota_bytes=1024000)  # 1MB
        checker.record_write("session1", 900000)  # 900KB used
        assert not await checker.check_write_allowed("session1", 200000)  # Would exceed

    @pytest.mark.asyncio
    async def test_get_remaining_quota(self) -> None:
        """Test getting remaining quota."""
        checker = MockQuotaChecker(quota_bytes=1024000)  # 1MB
        checker.record_write("session1", 300000)  # 300KB used
        remaining = await checker.get_remaining_quota("session1")
        assert remaining == 724000  # 700KB + 24KB

    @pytest.mark.asyncio
    async def test_get_remaining_quota_empty(self) -> None:
        """Test getting remaining quota when nothing used."""
        checker = MockQuotaChecker(quota_bytes=1024000)  # 1MB
        remaining = await checker.get_remaining_quota("session1")
        assert remaining == 1024000

    @pytest.mark.asyncio
    async def test_multiple_sessions_independent(self) -> None:
        """Test different sessions have independent quotas."""
        checker = MockQuotaChecker(quota_bytes=1024000)  # 1MB per session
        checker.record_write("session1", 900000)  # 900KB used in session1

        # session2 should still have full quota
        assert await checker.check_write_allowed("session2", 500000)
        assert await checker.get_remaining_quota("session2") == 1024000


class TestQuotaExceededError:
    """Test QuotaExceededError."""

    def test_error_attributes(self) -> None:
        """Test error contains correct attributes."""
        error = QuotaExceededError(
            "Quota exceeded",
            session_id="session1",
            requested_bytes=1000000,
            available_bytes=500000,
        )

        assert error.session_id == "session1"
        assert error.requested_bytes == 1000000
        assert error.available_bytes == 500000
        assert "Quota exceeded" in str(error)
