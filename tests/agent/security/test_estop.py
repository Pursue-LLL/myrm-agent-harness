"""Tests for EStopGuard — emergency stop with JSON persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.security.guards.estop import (
    _INACTIVE,
    EStopGuard,
    EStopLevel,
    EStopState,
    check_estop,
    get_estop_guard,
)


@pytest.fixture()
def _state_file(tmp_path: Path):
    return tmp_path / "estop.json"


class TestEStopState:
    def test_inactive(self):
        assert _INACTIVE.is_active() is False
        assert _INACTIVE.level == EStopLevel.NONE

    def test_active_tool_freeze(self):
        s = EStopState(
            level=EStopLevel.TOOL_FREEZE,
            reason="test",
            activated_at=1.0,
            activated_by="op",
        )
        assert s.is_active() is True

    def test_active_kill_all(self):
        s = EStopState(
            level=EStopLevel.KILL_ALL,
            reason="test",
            activated_at=1.0,
            activated_by="op",
        )
        assert s.is_active() is True


class TestEStopLevel:
    def test_values(self):
        assert EStopLevel.NONE == "none"
        assert EStopLevel.TOOL_FREEZE == "tool_freeze"
        assert EStopLevel.KILL_ALL == "kill_all"


class TestEStopGuard:
    def test_initial_inactive(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        assert guard.state.is_active() is False

    def test_activate_and_state(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        state = guard.activate(EStopLevel.TOOL_FREEZE, "unit test", "tester")
        assert state.is_active() is True
        assert state.level == EStopLevel.TOOL_FREEZE
        assert state.reason == "unit test"
        assert state.activated_by == "tester"

    def test_activate_none_raises(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        with pytest.raises(ValueError, match="resume"):
            guard.activate(EStopLevel.NONE, "invalid", "tester")

    def test_resume(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        guard.activate(EStopLevel.KILL_ALL, "emergency", "tester")
        resumed = guard.resume(resumed_by="admin")
        assert resumed.is_active() is False
        assert guard.state.is_active() is False

    def test_persistence(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        guard.activate(EStopLevel.TOOL_FREEZE, "persist test", "tester")

        # Load a new guard from the same file
        guard2 = EStopGuard(state_path=_state_file)
        assert guard2.state.is_active() is True
        assert guard2.state.level == EStopLevel.TOOL_FREEZE
        assert guard2.state.reason == "persist test"

    def test_persistence_after_resume(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        guard.activate(EStopLevel.KILL_ALL, "test", "op")
        guard.resume()

        guard2 = EStopGuard(state_path=_state_file)
        assert guard2.state.is_active() is False

    def test_corrupted_file_fail_closed(self, _state_file):
        _state_file.write_text("INVALID JSON{{{", encoding="utf-8")
        guard = EStopGuard(state_path=_state_file)
        # Fail-closed: should be in KILL_ALL state
        assert guard.state.is_active() is True
        assert guard.state.level == EStopLevel.KILL_ALL

    def test_missing_fields_in_file(self, _state_file):
        _state_file.write_text(json.dumps({"level": "tool_freeze"}), encoding="utf-8")
        guard = EStopGuard(state_path=_state_file)
        assert guard.state.level == EStopLevel.TOOL_FREEZE
        assert guard.state.reason == ""

    def test_persist_failure_does_not_crash(self, _state_file):
        guard = EStopGuard(state_path=_state_file)
        with patch(
            "myrm_agent_harness.agent.security.guards.estop.atomic_write",
            side_effect=OSError("disk full"),
            create=True,
        ):
            # Should not raise
            state = guard.activate(EStopLevel.TOOL_FREEZE, "test", "op")
            assert state.is_active() is True


class TestCheckEstop:
    def test_returns_none_when_inactive(self, _state_file):
        import myrm_agent_harness.agent.security.guards.estop as mod

        # Reset global singleton for isolation
        mod._global_guard = None
        guard = EStopGuard(state_path=_state_file)
        mod._global_guard = guard
        try:
            result = check_estop()
            assert result is None
        finally:
            mod._global_guard = None

    def test_returns_state_when_active(self, _state_file):
        import myrm_agent_harness.agent.security.guards.estop as mod

        mod._global_guard = None
        guard = EStopGuard(state_path=_state_file)
        guard.activate(EStopLevel.TOOL_FREEZE, "test", "op")
        mod._global_guard = guard
        try:
            result = check_estop()
            assert result is not None
            assert result.level == EStopLevel.TOOL_FREEZE
        finally:
            mod._global_guard = None


class TestGetEstopGuard:
    def test_singleton_creation(self, _state_file):
        import myrm_agent_harness.agent.security.guards.estop as mod

        mod._global_guard = None
        try:
            guard = get_estop_guard(state_path=_state_file)
            assert isinstance(guard, EStopGuard)
            guard2 = get_estop_guard()
            assert guard is guard2
        finally:
            mod._global_guard = None
