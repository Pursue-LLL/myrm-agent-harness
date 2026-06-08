"""Unit tests for SessionMemoryBridge — 100% isolated with mocks.

Covers: on_session_saved, on_session_deleted, on_sessions_expired,
_parse_entries, _format_entry, _serialize, MAX_TRACKED limit, dedup,
empty-state handling, error resilience, and profile key cleanup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.session_memory_bridge import (
    PROFILE_KEY,
    SessionMemoryBridge,
    _MAX_TRACKED_SESSIONS,
    _format_entry,
    _parse_entries,
    _serialize,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_mm() -> MagicMock:
    """Mock MemoryManager with async profile methods."""
    mm = MagicMock()
    mm.get_profile_attribute = AsyncMock(return_value=None)
    mm.set_system_profile_attribute = AsyncMock()
    mm.delete_system_profile_attribute = AsyncMock(return_value=True)
    return mm


@pytest.fixture
def bridge(mock_mm: MagicMock) -> SessionMemoryBridge:
    return SessionMemoryBridge(mock_mm)


# ===========================================================================
# Pure-function helpers
# ===========================================================================


class TestParseEntries:
    def test_empty_string(self) -> None:
        assert _parse_entries("") == []

    def test_none(self) -> None:
        assert _parse_entries(None) == []

    def test_single_entry(self) -> None:
        entries = _parse_entries("github.com (Jun 08)")
        assert len(entries) == 1
        assert entries[0][0] == "github.com"

    def test_multiple_entries(self) -> None:
        entries = _parse_entries("github.com (Jun 08), google.com (Jun 07)")
        assert len(entries) == 2
        assert entries[0][0] == "github.com"
        assert entries[1][0] == "google.com"

    def test_trailing_comma_ignored(self) -> None:
        entries = _parse_entries("a.com (Jun 01), ")
        assert len(entries) == 1
        assert entries[0][0] == "a.com"

    def test_no_paren_fallback(self) -> None:
        entries = _parse_entries("bare-domain")
        assert len(entries) == 1
        assert entries[0][0] == "bare-domain"
        assert entries[0][1] == "bare-domain"

    def test_whitespace_only(self) -> None:
        assert _parse_entries("   ") == []

    def test_domain_with_port(self) -> None:
        entries = _parse_entries("localhost:3000 (Jun 08)")
        assert len(entries) == 1
        assert entries[0][0] == "localhost:3000"

    def test_subdomain_with_hyphens(self) -> None:
        entries = _parse_entries("my-app.us-east-1.example.com (Jun 08)")
        assert len(entries) == 1
        assert entries[0][0] == "my-app.us-east-1.example.com"

    def test_roundtrip_parse_serialize(self) -> None:
        original = "a.com (Jun 08), b.com (Jun 07), c.com (Jun 06)"
        entries = _parse_entries(original)
        assert _serialize(entries) == original


class TestFormatEntry:
    def test_contains_domain_and_date(self) -> None:
        entry = _format_entry("example.com")
        assert "example.com" in entry
        assert "(" in entry and ")" in entry

    @patch(
        "myrm_agent_harness.toolkits.browser.session.session_memory_bridge.datetime"
    )
    def test_date_format(self, mock_dt: MagicMock) -> None:
        from datetime import datetime, timezone

        mock_dt.now.return_value = datetime(2026, 1, 15, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = _format_entry("test.com")
        assert result == "test.com (Jan 15)"


class TestSerialize:
    def test_empty(self) -> None:
        assert _serialize([]) == ""

    def test_single(self) -> None:
        assert _serialize([("a.com", "a.com (Jun 08)")]) == "a.com (Jun 08)"

    def test_multiple(self) -> None:
        result = _serialize([("a.com", "a.com (Jun 08)"), ("b.com", "b.com (Jun 07)")])
        assert result == "a.com (Jun 08), b.com (Jun 07)"


# ===========================================================================
# on_session_saved
# ===========================================================================


class TestOnSessionSaved:
    @pytest.mark.asyncio
    async def test_first_save_creates_profile(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = None

        await bridge.on_session_saved("github.com", 12, 3)

        mock_mm.set_system_profile_attribute.assert_awaited_once()
        key, value = mock_mm.set_system_profile_attribute.call_args[0]
        assert key == PROFILE_KEY
        assert "github.com" in value

    @pytest.mark.asyncio
    async def test_dedup_updates_existing(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "github.com (Jun 01), google.com (Jun 01)"

        await bridge.on_session_saved("github.com", 5, 2)

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        domains = [d.strip().split(" ")[0] for d in value.split(",")]
        assert domains.count("github.com") == 1
        assert domains[0] == "github.com"

    @pytest.mark.asyncio
    async def test_max_tracked_limit(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        existing = ", ".join(
            f"d{i}.com (Jun 01)" for i in range(_MAX_TRACKED_SESSIONS)
        )
        mock_mm.get_profile_attribute.return_value = existing

        await bridge.on_session_saved("overflow.com", 1, 0)

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        count = len(value.split(", "))
        assert count == _MAX_TRACKED_SESSIONS
        assert "overflow.com" in value
        assert f"d{_MAX_TRACKED_SESSIONS - 1}.com" not in value

    @pytest.mark.asyncio
    async def test_new_save_moves_to_front(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01), b.com (Jun 01)"

        await bridge.on_session_saved("b.com", 3, 1)

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        parts = [p.strip() for p in value.split(",")]
        assert parts[0].startswith("b.com")

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.side_effect = RuntimeError("DB down")

        await bridge.on_session_saved("fail.com", 0, 0)

    @pytest.mark.asyncio
    async def test_write_exception_does_not_propagate(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = None
        mock_mm.set_system_profile_attribute.side_effect = IOError("disk full")

        await bridge.on_session_saved("fail.com", 1, 0)

    @pytest.mark.asyncio
    async def test_exactly_at_limit_no_truncation(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        existing = ", ".join(
            f"d{i}.com (Jun 01)" for i in range(_MAX_TRACKED_SESSIONS - 1)
        )
        mock_mm.get_profile_attribute.return_value = existing

        await bridge.on_session_saved("new.com", 1, 0)

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        count = len(value.split(", "))
        assert count == _MAX_TRACKED_SESSIONS

    @pytest.mark.asyncio
    async def test_rapid_duplicate_saves_are_idempotent(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "same.com (Jun 01)"

        await bridge.on_session_saved("same.com", 5, 2)

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        domains = [p.strip().split(" ")[0] for p in value.split(",")]
        assert domains.count("same.com") == 1


# ===========================================================================
# on_session_deleted
# ===========================================================================


class TestOnSessionDeleted:
    @pytest.mark.asyncio
    async def test_delete_existing(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "github.com (Jun 08), google.com (Jun 07)"

        await bridge.on_session_deleted("github.com")

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        assert "github.com" not in value
        assert "google.com" in value

    @pytest.mark.asyncio
    async def test_delete_last_removes_key(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "only.com (Jun 08)"

        await bridge.on_session_deleted("only.com")

        mock_mm.delete_system_profile_attribute.assert_awaited_once_with(PROFILE_KEY)
        mock_mm.set_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 08)"

        await bridge.on_session_deleted("not-here.com")

        mock_mm.set_system_profile_attribute.assert_not_awaited()
        mock_mm.delete_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_from_empty_is_noop(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = None

        await bridge.on_session_deleted("ghost.com")

        mock_mm.set_system_profile_attribute.assert_not_awaited()
        mock_mm.delete_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.side_effect = RuntimeError("oops")

        await bridge.on_session_deleted("fail.com")

    @pytest.mark.asyncio
    async def test_delete_exception_on_write(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01), b.com (Jun 01)"
        mock_mm.set_system_profile_attribute.side_effect = IOError("write fail")

        await bridge.on_session_deleted("a.com")

    @pytest.mark.asyncio
    async def test_delete_exception_on_key_removal(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "only.com (Jun 01)"
        mock_mm.delete_system_profile_attribute.side_effect = IOError("delete fail")

        await bridge.on_session_deleted("only.com")


# ===========================================================================
# on_sessions_expired
# ===========================================================================


class TestOnSessionsExpired:
    @pytest.mark.asyncio
    async def test_expire_some(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01), b.com (Jun 01), c.com (Jun 01)"

        await bridge.on_sessions_expired(["a.com", "c.com"])

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        assert "a.com" not in value
        assert "c.com" not in value
        assert "b.com" in value

    @pytest.mark.asyncio
    async def test_expire_all_removes_key(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "x.com (Jun 01), y.com (Jun 01)"

        await bridge.on_sessions_expired(["x.com", "y.com"])

        mock_mm.delete_system_profile_attribute.assert_awaited_once_with(PROFILE_KEY)

    @pytest.mark.asyncio
    async def test_expire_none_matching_is_noop(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01)"

        await bridge.on_sessions_expired(["z.com"])

        mock_mm.set_system_profile_attribute.assert_not_awaited()
        mock_mm.delete_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expire_from_empty_is_noop(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = None

        await bridge.on_sessions_expired(["a.com"])

        mock_mm.set_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.side_effect = ConnectionError("gone")

        await bridge.on_sessions_expired(["fail.com"])

    @pytest.mark.asyncio
    async def test_expire_empty_list_is_noop(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01)"

        await bridge.on_sessions_expired([])

        mock_mm.set_system_profile_attribute.assert_not_awaited()
        mock_mm.delete_system_profile_attribute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_expire_duplicate_domains_handled(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01), b.com (Jun 01)"

        await bridge.on_sessions_expired(["a.com", "a.com"])

        _, value = mock_mm.set_system_profile_attribute.call_args[0]
        assert "a.com" not in value
        assert "b.com" in value

    @pytest.mark.asyncio
    async def test_expire_write_exception_does_not_propagate(
        self, bridge: SessionMemoryBridge, mock_mm: MagicMock
    ) -> None:
        mock_mm.get_profile_attribute.return_value = "a.com (Jun 01), b.com (Jun 01)"
        mock_mm.set_system_profile_attribute.side_effect = IOError("disk full")

        await bridge.on_sessions_expired(["a.com"])


# ===========================================================================
# Protocol conformance
# ===========================================================================


class TestProtocolConformance:
    def test_bridge_satisfies_protocol(self, bridge: SessionMemoryBridge) -> None:
        from myrm_agent_harness.toolkits.browser.session.session_lifecycle_hook import (
            SessionLifecycleHookProtocol,
        )

        assert isinstance(bridge, SessionLifecycleHookProtocol)
