"""ScreenGuard and the on-demand unlock hook of ComputerSession / DesktopSession."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.dref.errors import AXTreeEmptyError, DRefStaleError
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.safety import (
    PhysicalSleepInterruptionError,
    ScreenLockedInterruptionError,
)
from myrm_agent_harness.toolkits.computer_use.screen_guard import ScreenGuard
from myrm_agent_harness.toolkits.computer_use.session import ComputerSession
from myrm_agent_harness.toolkits.computer_use.types import ActionResult, ComputerUseConfig

_LOCKED_REFUSAL = "Safety: Screen is locked"
_SNAPSHOT_REFUSAL = "Safety: Desktop screen is locked"
_TYPE_PAYLOAD_ERROR = "Error: text (key combo) is required for key action"
_APPROVAL_STOP = ActionResult(success=False, error="stop-after-guard")


def _backend(*, locked: bool = False, asleep: bool = False) -> MagicMock:
    backend = MagicMock(spec=ComputerBackend)
    backend.is_screen_locked.return_value = locked
    backend.is_display_asleep.return_value = asleep
    backend.type_text = AsyncMock(return_value=ActionResult(success=True))
    backend.click = AsyncMock(return_value=ActionResult(success=True))
    return backend


class _Host:
    """Scriptable ScreenUnlockCallback: counts awaits and optionally unlocks the backend."""

    def __init__(self, backend: MagicMock, *, unlocks: bool) -> None:
        self._backend = backend
        self._unlocks = unlocks
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        if self._unlocks:
            self._backend.is_screen_locked.return_value = False


def _guard(backend: MagicMock) -> tuple[ScreenGuard, MagicMock]:
    on_unlocked = MagicMock()
    return ScreenGuard(backend, on_unlocked), on_unlocked


def _computer_session(backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> ComputerSession:
    session = ComputerSession(backend=backend, config=ComputerUseConfig(screenshot_delay=0.0))
    monkeypatch.setattr(session, "take_screenshot", AsyncMock(return_value=ActionResult(success=True)))
    return session


def _desktop_session(backend: MagicMock, monkeypatch: pytest.MonkeyPatch) -> DesktopSession:
    session = DesktopSession(backend=backend)
    monkeypatch.setattr(session, "check_app_approval", AsyncMock(return_value=_APPROVAL_STOP))
    return session


def _seed_pre_lock_ref(session: DesktopSession) -> None:
    ref = ElementRef(
        ref_id="d1",
        role="AXButton",
        name="Send",
        bbox=BBox(x=0, y=0, width=10, height=10),
        backend_key="key_d1",
        actions=("click",),
    )
    meta = SnapshotMeta(ref_count=1, app_name="Mail", window_title="Inbox", scope="foreground")
    session.ref_registry.replace({"d1": ref}, meta)


class TestScreenGuardProbes:
    @pytest.mark.parametrize(("locked", "asleep"), [(False, False), (True, False), (False, True)])
    def test_probes_report_the_backend_flags(self, locked: bool, asleep: bool) -> None:
        guard, _ = _guard(_backend(locked=locked, asleep=asleep))

        assert guard.is_locked() is locked
        assert guard.is_sleeping() is asleep

    @pytest.mark.parametrize("opaque", [object(), MagicMock()], ids=["no-probe", "non-bool-probe"])
    def test_backend_that_cannot_tell_counts_as_usable(self, opaque: object) -> None:
        guard = ScreenGuard(opaque, MagicMock())  # type: ignore[arg-type]

        assert guard.is_locked() is False
        assert guard.is_sleeping() is False


class TestStillLocked:
    async def test_usable_screen_never_involves_the_host(self) -> None:
        backend = _backend()
        guard, on_unlocked = _guard(backend)
        host = _Host(backend, unlocks=True)
        guard.unlock_callback = host

        assert await guard.still_locked() is False
        assert host.calls == 0
        on_unlocked.assert_not_called()

    async def test_locked_screen_without_a_host_stays_locked(self) -> None:
        guard, on_unlocked = _guard(_backend(locked=True))

        assert await guard.still_locked() is True
        on_unlocked.assert_not_called()

    async def test_host_unlock_opens_the_guard_and_discards_cached_visual_state(self) -> None:
        backend = _backend(locked=True)
        guard, on_unlocked = _guard(backend)
        host = _Host(backend, unlocks=True)
        guard.unlock_callback = host

        assert await guard.still_locked() is False
        assert host.calls == 1
        on_unlocked.assert_called_once_with()

    async def test_only_the_reprobe_decides_not_the_host(self) -> None:
        backend = _backend(locked=True)
        guard, on_unlocked = _guard(backend)
        host = _Host(backend, unlocks=False)
        guard.unlock_callback = host

        assert await guard.still_locked() is True
        assert host.calls == 1
        on_unlocked.assert_not_called()

    async def test_failing_host_keeps_the_guard_closed(self, caplog: pytest.LogCaptureFixture) -> None:
        guard, on_unlocked = _guard(_backend(locked=True))
        guard.unlock_callback = AsyncMock(side_effect=RuntimeError("keychain unavailable"))

        with caplog.at_level(logging.WARNING):
            assert await guard.still_locked() is True

        assert "keychain unavailable" in caplog.text
        on_unlocked.assert_not_called()

    async def test_cancellation_is_not_swallowed(self) -> None:
        guard, _ = _guard(_backend(locked=True))
        guard.unlock_callback = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await guard.still_locked()


class TestRefusal:
    async def test_usable_screen_has_no_refusal(self) -> None:
        guard, _ = _guard(_backend())

        assert await guard.refusal() is None
        assert await guard.refusal(snapshot=True) is None

    async def test_locked_screen_refuses_with_the_tool_specific_text(self) -> None:
        guard, _ = _guard(_backend(locked=True))

        assert await guard.refusal() == (
            "Safety: Screen is locked. Automated inputs are halted to prevent password leakage and account lockout."
        )
        assert await guard.refusal(snapshot=True) == (
            "Safety: Desktop screen is locked. Snapshot aborted to prevent capturing private lock-screen content."
        )

    async def test_sleeping_display_refuses_without_involving_the_host(self) -> None:
        backend = _backend(asleep=True)
        guard, _ = _guard(backend)
        host = _Host(backend, unlocks=True)
        guard.unlock_callback = host

        assert await guard.refusal() == (
            "Safety: Display is sleeping. Automated inputs are halted to prevent unintended actions."
        )
        assert await guard.refusal(snapshot=True) == "Safety: Display is sleeping. Snapshot aborted."
        assert host.calls == 0

    async def test_host_recovery_lifts_the_refusal(self) -> None:
        backend = _backend(locked=True)
        guard, _ = _guard(backend)
        guard.unlock_callback = _Host(backend, unlocks=True)

        assert await guard.refusal() is None


class TestComputerSessionOnDemandUnlock:
    async def test_locked_screen_is_unlocked_then_the_action_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _computer_session(backend, monkeypatch)
        host = _Host(backend, unlocks=True)
        session.set_screen_unlock_callback(host)

        result = await session.type_text("hello")

        assert result.success is True
        assert host.calls == 1
        assert backend.type_text.await_count == 1

    async def test_declined_unlock_still_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _computer_session(backend, monkeypatch)
        host = _Host(backend, unlocks=False)
        session.set_screen_unlock_callback(host)

        with pytest.raises(ScreenLockedInterruptionError):
            await session.type_text("secret")

        assert host.calls == 1
        assert backend.type_text.await_count == 0

    async def test_clearing_the_callback_restores_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _computer_session(backend, monkeypatch)
        host = _Host(backend, unlocks=True)
        session.set_screen_unlock_callback(host)
        session.set_screen_unlock_callback(None)

        with pytest.raises(ScreenLockedInterruptionError):
            await session.type_text("secret")

        assert host.calls == 0

    async def test_sleeping_display_is_not_the_hosts_to_fix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(asleep=True)
        session = _computer_session(backend, monkeypatch)
        host = _Host(backend, unlocks=True)
        session.set_screen_unlock_callback(host)

        with pytest.raises(PhysicalSleepInterruptionError):
            await session.type_text("hello")

        assert host.calls == 0

    async def test_unlock_discards_the_visual_state_cached_before_the_lock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _backend(locked=True)
        session = _computer_session(backend, monkeypatch)
        session.set_screen_unlock_callback(_Host(backend, unlocks=True))
        session._last_screenshot_bytes = b"pre-lock frame"

        await session.type_text("hello")

        assert session._last_screenshot_bytes is None


class TestDesktopSessionReanchor:
    def test_every_pre_lock_ref_resolves_as_stale(self) -> None:
        session = DesktopSession(backend=_backend())
        _seed_pre_lock_ref(session)
        generation = session.ref_registry.generation

        session.reanchor_visual_state()

        with pytest.raises(DRefStaleError):
            session.ref_registry.get("d1")
        assert session.ref_registry.meta is None
        assert session.ref_registry.previous_refs == {}
        assert session.ref_registry.previous_meta is None
        assert session.ref_registry.generation > generation

    async def test_on_demand_unlock_invalidates_refs_issued_before_the_lock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = _backend(locked=True)
        session = _desktop_session(backend, monkeypatch)
        _seed_pre_lock_ref(session)
        session.set_screen_unlock_callback(_Host(backend, unlocks=True))

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            side_effect=AXTreeEmptyError("unlocked"),
        ):
            await session.desktop_snapshot()

        with pytest.raises(DRefStaleError):
            session.ref_registry.get("d1")


class TestDesktopSessionOnDemandUnlock:
    async def test_snapshot_proceeds_after_on_demand_unlock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _desktop_session(backend, monkeypatch)
        host = _Host(backend, unlocks=True)
        session.set_screen_unlock_callback(host)

        with patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            side_effect=AXTreeEmptyError("unlocked"),
        ):
            result = await session.desktop_snapshot()

        assert "Accessibility tree is empty" in str(result)
        assert host.calls == 1

    async def test_interact_and_vision_proceed_after_on_demand_unlock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _desktop_session(backend, monkeypatch)
        host = _Host(backend, unlocks=True)
        session.set_screen_unlock_callback(host)

        interact = await session.desktop_interact("ref1", "click")
        backend.is_screen_locked.return_value = True
        vision = await session.desktop_vision_action("key")

        assert interact == f"Control denied: {_APPROVAL_STOP.error}"
        assert vision == _TYPE_PAYLOAD_ERROR
        assert host.calls == 2

    async def test_declined_unlock_keeps_every_refusal_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = _backend(locked=True)
        session = _desktop_session(backend, monkeypatch)
        host = _Host(backend, unlocks=False)
        session.set_screen_unlock_callback(host)

        snapshot = await session.desktop_snapshot()
        interact = await session.desktop_interact("ref1", "click")
        vision = await session.desktop_vision_action("left_click", coordinate=[100, 100])

        assert _SNAPSHOT_REFUSAL in str(snapshot)
        assert _LOCKED_REFUSAL in str(interact)
        assert _LOCKED_REFUSAL in str(vision)
        assert backend.click.await_count == 0
        assert host.calls == 3
