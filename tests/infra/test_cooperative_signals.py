"""Unit tests for infra.cooperative_signals and its runtime re-export shim."""

from __future__ import annotations

import pytest

from myrm_agent_harness.infra import cooperative_signals as signals_module
from myrm_agent_harness.infra.cooperative_signals import (
    CooperativePauseSignal,
    PauseRequestedError,
    get_global_pause_signal,
)


class TestCooperativePauseSignal:
    def test_initial_state_not_paused(self) -> None:
        signal = CooperativePauseSignal()
        assert signal.is_pause_requested is False
        assert signal.pause_reason == ""
        assert signal.cursor is None

    def test_request_and_clear_cycle(self) -> None:
        signal = CooperativePauseSignal()
        signal.request_pause("foreground_user_activity")
        assert signal.is_pause_requested is True
        assert signal.pause_reason == "foreground_user_activity"
        signal.clear()
        assert signal.is_pause_requested is False

    def test_raise_if_paused(self) -> None:
        signal = CooperativePauseSignal()
        signal.raise_if_paused()
        signal.request_pause("busy")
        with pytest.raises(PauseRequestedError):
            signal.raise_if_paused()

    def test_pause_with_ttl_lapses_without_anyone_polling_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [1000.0]
        monkeypatch.setattr(signals_module.time, "monotonic", lambda: clock[0])
        signal = CooperativePauseSignal()

        signal.request_pause("typing", ttl_seconds=120.0)
        clock[0] += 119.0
        assert signal.is_pause_requested is True

        clock[0] += 2.0
        assert signal.is_pause_requested is False
        assert signal.pause_reason == ""
        signal.raise_if_paused()

    def test_pause_without_ttl_holds_until_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [1000.0]
        monkeypatch.setattr(signals_module.time, "monotonic", lambda: clock[0])
        signal = CooperativePauseSignal()

        signal.request_pause("manual")
        clock[0] += 10**6

        assert signal.is_pause_requested is True

    def test_a_new_request_replaces_the_previous_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [1000.0]
        monkeypatch.setattr(signals_module.time, "monotonic", lambda: clock[0])
        signal = CooperativePauseSignal()

        signal.request_pause("typing", ttl_seconds=10.0)
        clock[0] += 8.0
        signal.request_pause("typing", ttl_seconds=10.0)
        clock[0] += 8.0

        assert signal.is_pause_requested is True

    def test_checkpoint_cursor_roundtrip(self) -> None:
        signal = CooperativePauseSignal()
        signal.checkpoint_cursor("txn-42")
        assert signal.cursor == "txn-42"

    def test_global_singleton_is_shared(self) -> None:
        first = get_global_pause_signal()
        second = get_global_pause_signal()
        assert first is second

    def test_runtime_shim_shares_singleton(self) -> None:
        from myrm_agent_harness.runtime.cognitive_clock.signals import (
            get_global_pause_signal as runtime_getter,
        )

        assert runtime_getter() is get_global_pause_signal()
