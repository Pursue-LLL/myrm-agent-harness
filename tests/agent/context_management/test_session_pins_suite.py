"""Unit tests for SessionPinsPersistedInSessionsSuite."""

from __future__ import annotations

from pathlib import Path
import pytest

from myrm_agent_harness.agent.context_management import (
    PinActionKind,
    SessionDeeplinkRoute,
    SessionPinRepository,
    SessionPinState,
    SessionPinSyncReceipt,
    SessionPinsPersistedInSessionsSuite,
)


def test_session_pinning_state_and_idempotent_mutation() -> None:
    """Test setting, unpinning, and toggling session pin states."""
    suite = SessionPinsPersistedInSessionsSuite()

    # Initial state
    assert not suite.is_session_pinned("sess-001")

    # Pin session
    receipt1 = suite.pin_session("sess-001", pin_order=1, label="Architecture Review")
    assert suite.is_session_pinned("sess-001")
    assert receipt1.action == PinActionKind.PIN
    assert receipt1.is_pinned is True
    assert receipt1.total_pinned_sessions_count == 1

    # Toggle unpin
    receipt2 = suite.toggle_pin("sess-001")
    assert not suite.is_session_pinned("sess-001")
    assert receipt2.action == PinActionKind.UNPIN
    assert receipt2.is_pinned is False

    # Toggle pin again
    receipt3 = suite.toggle_pin("sess-001")
    assert suite.is_session_pinned("sess-001")
    assert receipt3.action == PinActionKind.PIN


def test_session_list_sorting_pinned_first_and_reorder() -> None:
    """Test prioritizing pinned sessions on top with custom ordering."""
    suite = SessionPinsPersistedInSessionsSuite()

    # Pin session B with order 1 (highest priority)
    suite.pin_session("sess-B", pin_order=1, label="Top Priority")
    # Pin session C with order 2
    suite.pin_session("sess-C", pin_order=2, label="Second Priority")

    sessions_raw = [
        {"session_id": "sess-A", "title": "Session A (Unpinned Recent)", "updated_at_iso": "2026-10-08T10:00:00Z"},
        {"session_id": "sess-B", "title": "Session B (Pinned #1)", "updated_at_iso": "2026-10-01T10:00:00Z"},
        {"session_id": "sess-C", "title": "Session C (Pinned #2)", "updated_at_iso": "2026-10-02T10:00:00Z"},
        {"session_id": "sess-D", "title": "Session D (Unpinned Older)", "updated_at_iso": "2026-10-07T10:00:00Z"},
    ]

    sorted_sessions = suite.sort_sessions(sessions_raw)
    sorted_ids = [str(s["session_id"]) for s in sorted_sessions]

    # Expected order: sess-B (pinned 1), sess-C (pinned 2), sess-A (unpinned newer), sess-D (unpinned older)
    assert sorted_ids == ["sess-B", "sess-C", "sess-A", "sess-D"]


def test_persistent_disk_storage_and_reload(tmp_path: Path) -> None:
    """Test cold-boot disk reload and persistence across suite instances."""
    pins_file = tmp_path / "session_pins.json"

    # Instance 1 writes pins
    suite1 = SessionPinsPersistedInSessionsSuite(persistence_file_path=str(pins_file))
    suite1.pin_session("sess-persist-1", pin_order=0, label="Release Checklist")
    suite1.pin_session("sess-persist-2", pin_order=1, label="Hotfix Investigation")

    assert pins_file.exists()

    # Instance 2 loads pins from the same file
    suite2 = SessionPinsPersistedInSessionsSuite(persistence_file_path=str(pins_file))
    assert suite2.is_session_pinned("sess-persist-1")
    assert suite2.is_session_pinned("sess-persist-2")

    pinned_list = suite2.get_pinned_sessions()
    assert len(pinned_list) == 2
    assert pinned_list[0].session_id == "sess-persist-1"
    assert pinned_list[1].session_id == "sess-persist-2"
    assert pinned_list[0].pin_label == "Release Checklist"


def test_session_deeplink_route_and_sync_receipt_integrity() -> None:
    """Test generating deep link URLs and verifying audit receipt properties."""
    suite = SessionPinsPersistedInSessionsSuite(base_deeplink_scheme="https://app.myrm.ai/studio")

    # Generate deep links
    route1 = suite.generate_session_deeplink(session_id="sess-xyz")
    assert route1.deeplink_url == "https://app.myrm.ai/studio/sessions/sess-xyz"
    assert route1.route_path == "/sessions/sess-xyz"

    route2 = suite.generate_session_deeplink(session_id="sess-xyz", target_entry_id="msg_987")
    assert route2.deeplink_url == "https://app.myrm.ai/studio/sessions/sess-xyz?entry=msg_987"
    assert route2.target_entry_id == "msg_987"

    # Receipts audit trail
    suite.pin_session("sess-xyz", label="Work")
    receipts = suite.get_sync_receipts()
    assert len(receipts) == 1
    assert receipts[0].receipt_id.startswith("spr_")
    assert receipts[0].sync_hash != ""
    assert receipts[0].total_pinned_sessions_count == 1
