"""Tests for action_capture engine navigation folding."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.toolkits.browser.action_capture.capture_engine import (
    _NAV_ACTION_WINDOW_S,
    ActionCaptureEngine,
)
from myrm_agent_harness.toolkits.browser.action_capture.types import (
    ActionStep,
    ActionType,
    CaptureSession,
)


def _make_step(
    seq: int,
    action: ActionType,
    value: str = "",
    url: str = "https://example.com",
    timestamp: float | None = None,
) -> ActionStep:
    return ActionStep(
        seq=seq,
        action=action,
        selector="#el" if action != ActionType.NAVIGATE else "",
        value=value,
        url=url,
        title="",
        timestamp=timestamp if timestamp is not None else time.time(),
    )


@pytest.fixture
def engine() -> ActionCaptureEngine:
    # _record_navigation only touches self._session, so a dummy page is fine.
    eng = ActionCaptureEngine.__new__(ActionCaptureEngine)  # type: ignore[attr-defined]
    eng._session = CaptureSession(session_id="test", start_url="https://example.com")
    return eng


class _DummyPage:
    """Page stub recording screenshot calls for hover/screenshot assertions."""

    def __init__(self) -> None:
        self.screenshot_calls: int = 0

    async def screenshot(self, **kwargs: object) -> bytes:
        self.screenshot_calls += 1
        return b"png-bytes"


def _screenshot_engine() -> tuple[ActionCaptureEngine, _DummyPage]:
    eng = ActionCaptureEngine.__new__(ActionCaptureEngine)  # type: ignore[attr-defined]
    page = _DummyPage()
    eng._page = page  # type: ignore[attr-defined]
    eng._capture_screenshots = True
    eng._callbacks = []  # type: ignore[attr-defined]
    eng._session = CaptureSession(session_id="test", start_url="https://example.com")
    return eng, page


async def test_first_navigation_creates_step(engine: ActionCaptureEngine) -> None:
    await engine._record_navigation("https://example.com/a")

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.NAVIGATE
    assert steps[0].value == "https://example.com/a"


async def test_consecutive_navigations_collapse(engine: ActionCaptureEngine) -> None:
    await engine._record_navigation("https://example.com/old")
    await engine._record_navigation("https://example.com/new")

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.NAVIGATE
    assert steps[0].value == "https://example.com/new"
    assert steps[0].url == "https://example.com/new"


async def test_navigation_after_action_merges_into_action(
    engine: ActionCaptureEngine,
) -> None:
    click = _make_step(
        seq=1,
        action=ActionType.CLICK,
        url="https://example.com/page",
        timestamp=time.time() - 0.5,
    )
    engine._session.add_step(click)
    await engine._record_navigation("https://example.com/destination")

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.CLICK
    assert steps[0].url == "https://example.com/destination"


async def test_stale_action_does_not_merge_navigation(
    engine: ActionCaptureEngine,
) -> None:
    old_click = _make_step(
        seq=1,
        action=ActionType.CLICK,
        timestamp=time.time() - (_NAV_ACTION_WINDOW_S + 5),
    )
    engine._session.add_step(old_click)
    await engine._record_navigation("https://example.com/destination")

    steps = engine._session.steps
    assert len(steps) == 2
    assert steps[0].action == ActionType.CLICK
    assert steps[1].action == ActionType.NAVIGATE
    assert steps[1].value == "https://example.com/destination"


async def test_navigation_after_select_creates_step(
    engine: ActionCaptureEngine,
) -> None:
    select = _make_step(
        seq=1,
        action=ActionType.SELECT,
        value="option-b",
        timestamp=time.time() - 0.3,
    )
    engine._session.add_step(select)
    await engine._record_navigation("https://example.com/after-select")

    steps = engine._session.steps
    assert len(steps) == 2
    assert steps[1].action == ActionType.NAVIGATE


async def test_spa_navigation_event_creates_step(engine: ActionCaptureEngine) -> None:
    await engine._on_action_event(
        '{"action":"navigate","selector":"","value":"https://example.com/spa",'
        '"url":"https://example.com/spa","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.NAVIGATE
    assert steps[0].value == "https://example.com/spa"
    assert steps[0].selector == ""


async def test_spa_navigation_after_action_merges(engine: ActionCaptureEngine) -> None:
    click = _make_step(
        seq=1,
        action=ActionType.CLICK,
        url="https://example.com/list",
        timestamp=time.time() - 0.4,
    )
    engine._session.add_step(click)
    await engine._on_action_event(
        '{"action":"navigate","selector":"","value":"https://example.com/new",'
        '"url":"https://example.com/new","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.CLICK
    assert steps[0].url == "https://example.com/new"


async def test_spa_consecutive_navigations_collapse(
    engine: ActionCaptureEngine,
) -> None:
    await engine._on_action_event(
        '{"action":"navigate","selector":"","value":"https://example.com/a",'
        '"url":"https://example.com/a","title":"","ts":1000.0}'
    )
    await engine._on_action_event(
        '{"action":"navigate","selector":"","value":"https://example.com/b",'
        '"url":"https://example.com/b","title":"","ts":1001.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].value == "https://example.com/b"


async def test_hover_action_skips_screenshot() -> None:
    engine, page = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"hover","selector":"#avatar","value":"","url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.HOVER
    assert steps[0].screenshot_b64 is None
    assert page.screenshot_calls == 0


async def test_non_hover_action_takes_screenshot() -> None:
    engine, page = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"click","selector":"#submit","value":"","url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.CLICK
    assert steps[0].screenshot_b64 == "cG5nLWJ5dGVz"  # base64("png-bytes")
    assert page.screenshot_calls == 1


async def test_press_step_carries_modifiers() -> None:
    engine, _ = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"press","selector":"#msg","value":"Enter","modifiers":["ctrl"],'
        '"url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.PRESS
    assert steps[0].modifiers == ["ctrl"]


async def test_press_step_defaults_empty_modifiers() -> None:
    engine, _ = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"press","selector":"#msg","value":"Enter","url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].modifiers == []


async def test_select_step_carries_label() -> None:
    engine, _ = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"select","selector":"#lang","value":"en; zh",'
        '"label":"English, Chinese","url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].action == ActionType.SELECT
    assert steps[0].value == "en; zh"
    assert steps[0].label == "English, Chinese"


async def test_select_step_label_defaults_empty() -> None:
    engine, _ = _screenshot_engine()
    await engine._on_action_event(
        '{"action":"select","selector":"#lang","value":"en","url":"https://example.com","title":"","ts":1000.0}'
    )

    steps = engine._session.steps
    assert len(steps) == 1
    assert steps[0].label == ""
