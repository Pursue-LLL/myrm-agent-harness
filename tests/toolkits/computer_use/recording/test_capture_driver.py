"""Tests for DesktopCaptureDriver: AX snapshot diffing into recorded interaction events."""

from __future__ import annotations

import asyncio

from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta
from myrm_agent_harness.toolkits.computer_use.recording.capture_driver import (
    DesktopCaptureDriver,
)
from myrm_agent_harness.toolkits.computer_use.recording.types import RecordedActionType


class _FakeBackend:
    """Platform backend stand-in; the driver only passes it through to the dispatcher."""


def _element(ref_id: str, role: str, name: str, value: str = "", x: int = 0, y: int = 0) -> ElementRef:
    return ElementRef(
        ref_id=ref_id,
        role=role,
        name=name,
        bbox=BBox(x, y, 100, 20),
        backend_key=ref_id,
        value=value,
    )


class _ScriptedCapture:
    """Replaces ax_dispatch.capture_snapshot with scripted frames."""

    def __init__(self, frames: list[tuple[SnapshotMeta, dict[str, ElementRef]]]) -> None:
        self._frames = list(frames)
        self.calls = 0

    def __call__(self, backend: object, scope: str, app_name: str | None = None):
        self.calls += 1
        if not self._frames:
            raise AssertionError("capture_snapshot called more times than scripted")
        return self._frames.pop(0)


def _meta(app_name: str, window_title: str = "Main") -> SnapshotMeta:
    return SnapshotMeta(
        ref_count=1,
        app_name=app_name,
        window_title=window_title,
        scope="foreground",
        app_id=f"com.example.{app_name.lower()}",
    )


def test_first_poll_primes_baseline_without_emitting(monkeypatch) -> None:
    """A diff needs a previous frame; the first poll must not fabricate interactions."""
    frames = [(_meta("Finder"), {"r1": _element("r1", "button", "Open")})]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    frame = asyncio.run(driver.poll())

    assert frame.events == ()
    assert driver.event_count == 0


def test_emits_click_event_for_newly_added_element(monkeypatch) -> None:
    """A newly appeared element is the observable trace of a click/navigation."""
    frames = [
        (_meta("Finder"), {"r1": _element("r1", "button", "Open")}),
        (
            _meta("Finder", "Documents"),
            {
                "r1": _element("r1", "button", "Open"),
                "r2": _element("r2", "button", "Documents"),
            },
        ),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    assert len(frame.events) == 1
    event = frame.events[0]
    assert event.action == RecordedActionType.CLICK.value
    assert event.dref_id == "r2"
    assert event.element_title == "Documents"
    assert event.app_name == "Finder"
    assert event.window_title == "Documents"


def test_emits_type_event_when_input_value_changes(monkeypatch) -> None:
    """A value change on an input-bearing role is the trace of text entry."""
    frames = [
        (_meta("Safari"), {"r1": _element("r1", "AXTextField", "Search")}),
        (_meta("Safari"), {"r1": _element("r1", "AXTextField", "Search", value="quarterly tax")}),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    assert len(frame.events) == 1
    event = frame.events[0]
    assert event.action == RecordedActionType.TYPE.value
    assert event.value == "quarterly tax"
    assert event.element_role == "AXTextField"


def test_emits_window_focus_event_on_app_change(monkeypatch) -> None:
    """Switching to another app is recorded as a window focus change."""
    frames = [
        (_meta("Finder"), {"r1": _element("r1", "button", "Open")}),
        (_meta("Microsoft Excel"), {"r1": _element("r1", "cell", "A1")}),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    actions = [event.action for event in frame.events]
    assert RecordedActionType.WINDOW_FOCUS.value in actions
    focus_event = next(
        event for event in frame.events if event.action == RecordedActionType.WINDOW_FOCUS.value
    )
    assert focus_event.app_name == "Microsoft Excel"


def test_skips_permission_denied_capture(monkeypatch) -> None:
    """A permission-denied frame must not diff as 'everything removed'."""
    denied = SnapshotMeta(
        ref_count=0,
        app_name="",
        window_title="",
        scope="foreground",
        needs_permission=True,
    )
    frames = [
        (_meta("Finder"), {"r1": _element("r1", "button", "Open")}),
        (denied, {}),
        (_meta("Finder"), {"r1": _element("r1", "button", "Open")}),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    denied_frame = asyncio.run(driver.poll())
    assert denied_frame.events == ()

    # Baseline survived the denied frame, so the unchanged frame yields no phantom events.
    recovered = asyncio.run(driver.poll())
    assert recovered.events == ()


def test_ignores_value_change_on_non_input_role(monkeypatch) -> None:
    """Progress labels and counters change value without any user interaction."""
    frames = [
        (_meta("App"), {"r1": _element("r1", "label", "Progress", value="10%")}),
        (_meta("App"), {"r1": _element("r1", "label", "Progress", value="80%")}),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    assert frame.events == ()


def test_events_are_sequential_and_bounded(monkeypatch) -> None:
    """Sequence numbers stay monotonic and a single poll emits a bounded number of events.

    A wholesale tree replacement trips the diff's change-ratio guard (`use_full_view`), so the
    driver must also report events when the renderer would fall back to the full tree.
    """
    many_added = {f"r{i}": _element(f"r{i}", "button", f"Action {i}", x=i * 10) for i in range(10)}
    frames = [
        (_meta("App"), {"r0": _element("r0", "button", "Initial", x=0)}),
        (_meta("App"), many_added),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    assert 0 < len(frame.events) <= 3
    sequences = [event.seq for event in frame.events]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)


def test_accepts_session_object_via_backend_attribute(monkeypatch) -> None:
    """A DesktopSession can be passed directly; the driver draws capture from its backend."""
    frames = [
        (_meta("Finder"), {"r1": _element("r1", "AXButton", "Open")}),
        (
            _meta("Finder"),
            {"r1": _element("r1", "AXButton", "Open"), "r2": _element("r2", "AXButton", "Taxes")},
        ),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    class _FakeDesktopSession:
        # Mirrors DesktopSession, which holds its platform backend on `_backend`.
        _backend = _FakeBackend()

    driver = DesktopCaptureDriver(_FakeDesktopSession())
    asyncio.run(driver.poll())
    frame = asyncio.run(driver.poll())

    assert len(frame.events) == 1
    assert frame.events[0].dref_id == "r2"


def test_reset_clears_baseline_and_counter(monkeypatch) -> None:
    """Reset re-arms the driver for a new recording session."""
    frames = [
        (_meta("App"), {"r1": _element("r1", "button", "Open")}),
        (_meta("App"), {"r1": _element("r1", "button", "Open")}),
    ]
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.computer_use.recording.capture_driver.capture_snapshot",
        _ScriptedCapture(frames),
    )

    driver = DesktopCaptureDriver(_FakeBackend())
    asyncio.run(driver.poll())
    driver.reset()
    assert driver.event_count == 0

    primed = asyncio.run(driver.poll())
    assert primed.events == ()
