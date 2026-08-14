"""Tests for ActionCaptureEngine lifecycle, callback registry, and error branches.

Coverage companion for test_capture_engine.py — exercises start/stop/pause/
resume, callback add/remove, bridge parse failures, screenshot failure, and
callback exceptions via a mock Page (no real browser).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.browser.action_capture.capture_engine import (
    ActionCaptureEngine,
)
from myrm_agent_harness.toolkits.browser.action_capture.types import (
    ActionStep,
    ActionType,
)


class _FakeFrame:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakePage:
    """Minimal async Page stub for lifecycle tests."""

    def __init__(self) -> None:
        self.url = "https://example.com"
        self.main_frame = _FakeFrame("https://example.com")
        self.exposed: list[str] = []
        self.init_scripts: list[str] = []
        self.evaluated: list[str] = []
        self.listeners: dict[str, object] = {}
        self.screenshot_raises = False

    async def expose_function(self, name: str, _fn: object) -> None:
        self.exposed.append(name)

    async def add_init_script(self, js: str) -> None:
        self.init_scripts.append(js)

    async def evaluate(self, expr: str) -> None:
        self.evaluated.append(expr)

    def on(self, event: str, cb: object) -> None:
        self.listeners[event] = cb

    async def screenshot(self, **_kwargs: object) -> bytes:
        if self.screenshot_raises:
            raise RuntimeError("screenshot failed")
        return b"png-bytes"


async def _make_engine(page: _FakePage) -> ActionCaptureEngine:
    eng = ActionCaptureEngine(page, capture_screenshots=True)  # type: ignore[arg-type]
    return eng


async def test_init_sets_attributes() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    assert eng.session is None
    assert eng._callbacks == []
    assert eng._attached is False


async def test_add_and_remove_callback() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    cb: object = object()

    eng.add_callback(cb)  # type: ignore[arg-type]
    assert eng._callbacks == [cb]

    eng.remove_callback(cb)  # type: ignore[arg-type]
    assert eng._callbacks == []

    # Removing a callback that was never registered must not raise.
    eng.remove_callback(object())  # type: ignore[arg-type]


async def test_start_attaches_and_evaluates_script() -> None:
    page = _FakePage()
    eng = await _make_engine(page)

    session = await eng.start("https://example.com/start")

    assert session is eng._session
    assert session.session_id
    assert session.start_url == "https://example.com/start"
    assert page.exposed == ["__myrmCaptureCallback"]
    assert len(page.init_scripts) == 0  # injection uses evaluate, not add_init_script
    assert len(page.evaluated) == 2
    assert "function truncateText" in page.evaluated[0]
    assert page.evaluated[1] == "window.__myrmCaptureActive = true"
    assert "framenavigated" in page.listeners


async def test_start_uses_page_url_when_start_url_empty() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    session = await eng.start()
    assert session.start_url == "https://example.com"


async def test_start_attaches_bridge_only_once() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    await eng.start()
    assert page.exposed == ["__myrmCaptureCallback"]


async def test_stop_marks_session_stopped_and_returns_it() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    session = await eng.start()

    stopped = await eng.stop()
    assert stopped is session
    assert stopped.status == "stopped"
    # stop re-injects the script and then sets the active gate to false
    assert page.evaluated[-1] == "window.__myrmCaptureActive = false"


async def test_stop_without_session_returns_none() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    assert await eng.stop() is None


async def test_pause_toggles_status() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()

    await eng.pause()
    assert eng.session.status == "paused"
    assert page.evaluated[-1] == "window.__myrmCaptureActive = false"

    await eng.resume()
    assert eng.session.status == "recording"
    assert page.evaluated[-1] == "window.__myrmCaptureActive = true"


async def test_pause_and_resume_without_session_noop() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.pause()
    await eng.resume()


async def test_bridge_ignores_events_when_session_missing() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng._on_action_event(
        '{"action":"click","selector":"#x","value":"","url":"u","title":"","ts":1.0}'
    )
    assert eng.session is None


async def test_bridge_ignores_events_when_paused() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    await eng.pause()
    await eng._on_action_event(
        '{"action":"click","selector":"#x","value":"","url":"u","title":"","ts":1.0}'
    )
    assert len(eng.session.steps) == 0


async def test_bridge_handles_invalid_json(caplog: pytest.LogCaptureFixture) -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    with caplog.at_level("WARNING", logger="myrm_agent_harness.toolkits.browser.action_capture.capture_engine"):
        await eng._on_action_event("not-json")
    assert "Invalid JSON from capture bridge" in caplog.text
    assert len(eng.session.steps) == 0


async def test_bridge_handles_unknown_action(caplog: pytest.LogCaptureFixture) -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    with caplog.at_level("DEBUG", logger="myrm_agent_harness.toolkits.browser.action_capture.capture_engine"):
        await eng._on_action_event(
            '{"action":"teleport","selector":"#x","value":"","url":"u","title":"","ts":1.0}'
        )
    assert "Unknown action type: teleport" in caplog.text
    assert len(eng.session.steps) == 0


async def test_screenshot_failure_is_tolerated() -> None:
    page = _FakePage()
    page.screenshot_raises = True
    eng = await _make_engine(page)
    await eng.start()

    await eng._on_action_event(
        '{"action":"click","selector":"#x","value":"","url":"u","title":"","ts":1.0}'
    )
    steps = eng.session.steps
    assert len(steps) == 1
    assert steps[0].screenshot_b64 is None


async def test_callback_exception_is_logged_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    page = _FakePage()
    eng = await _make_engine(page)

    class _BadCallback:
        async def on_step(self, _step: ActionStep) -> None:
            raise RuntimeError("callback boom")

    eng.add_callback(_BadCallback())
    await eng.start()

    with caplog.at_level("ERROR", logger="myrm_agent_harness.toolkits.browser.action_capture.capture_engine"):
        await eng._on_action_event(
            '{"action":"click","selector":"#x","value":"","url":"u","title":"","ts":1.0}'
        )
    assert "Capture callback error" in caplog.text
    assert len(eng.session.steps) == 1


async def test_callback_receives_step() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    received: list[ActionStep] = []

    class _SpyCallback:
        async def on_step(self, step: ActionStep) -> None:
            received.append(step)

    eng.add_callback(_SpyCallback())
    await eng.start()
    await eng._on_action_event(
        '{"action":"select","selector":"#lang","value":"en","label":"English",'
        '"url":"u","title":"t","ts":1.0,"elementText":"Language","elementRole":"combobox"}'
    )

    assert len(received) == 1
    step = received[0]
    assert step.action == ActionType.SELECT
    assert step.selector == "#lang"
    assert step.value == "en"
    assert step.label == "English"
    assert step.element_text == "Language"
    assert step.element_role == "combobox"


async def test_on_navigation_records_main_frame() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    # frame must be the same object as page.main_frame (compared by identity).
    await eng._on_navigation(page.main_frame)
    assert len(eng.session.steps) == 1
    assert eng.session.steps[0].action == ActionType.NAVIGATE
    assert eng.session.steps[0].value == "https://example.com"


async def test_on_navigation_ignores_subframes() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()
    sub = _FakeFrame("https://iframe.example.com")
    await eng._on_navigation(sub)
    assert len(eng.session.steps) == 0


async def test_on_navigation_without_session_noop() -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng._on_navigation(_FakeFrame("https://example.com"))


async def test_on_navigation_tolerates_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    page = _FakePage()
    eng = await _make_engine(page)
    await eng.start()

    class _BrokenFrame:
        @property
        def url(self) -> str:
            raise RuntimeError("frame closed")

    with caplog.at_level("DEBUG", logger="myrm_agent_harness.toolkits.browser.action_capture.capture_engine"):
        await eng._on_navigation(_BrokenFrame())
    assert len(eng.session.steps) == 0
