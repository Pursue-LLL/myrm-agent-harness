"""`console_log` tells the model when the engine cannot capture the console, instead of an empty log.

The default Chromium driver keeps `Console.enable` off to stay undetectable, so its pages never report
console output: an empty log there says nothing about the page's errors. Camoufox does report it.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine, BrowserPoolConfig
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.session.browser_session_network_mixin import CONSOLE_CAPTURE_UNAVAILABLE


def _session(*, preference: str | None = None, pool_engine: BrowserEngine | None = None) -> BrowserSession:
    pool = MagicMock()
    pool.config = dataclasses.replace(BrowserPoolConfig(), engine=pool_engine or BrowserPoolConfig().engine)
    return BrowserSession(pool, ContextType.AGENT, engine_preference=preference)


def _console_error(session: BrowserSession, text: str) -> None:
    message = MagicMock()
    message.type = "error"
    message.text = text
    message.location = {}
    session._console_logger._cb_console(message)


@pytest.mark.parametrize("preference", [None, BrowserEngine.CHROMIUM_PATCHRIGHT.value])
def test_default_chromium_engine_reports_capture_unavailable(preference: str | None) -> None:
    session = _session(preference=preference)

    assert session.get_console_log() == CONSOLE_CAPTURE_UNAVAILABLE


def test_unavailable_answer_is_not_an_empty_log() -> None:
    """The model must not read the answer as 'the console is clean'."""
    assert "No console messages" not in CONSOLE_CAPTURE_UNAVAILABLE
    assert "network_log" in CONSOLE_CAPTURE_UNAVAILABLE
    assert "evaluate" in CONSOLE_CAPTURE_UNAVAILABLE


def test_camoufox_session_returns_what_the_page_logged() -> None:
    session = _session(preference=BrowserEngine.FIREFOX_CAMOUFOX.value)
    _console_error(session, "boom at checkout")

    assert "boom at checkout" in session.get_console_log()


def test_camoufox_without_entries_is_an_honest_empty_log() -> None:
    session = _session(preference=BrowserEngine.FIREFOX_CAMOUFOX.value)

    assert session.get_console_log() == "No console messages captured."


def test_pool_default_engine_decides_when_the_session_has_no_preference() -> None:
    session = _session(pool_engine=BrowserEngine.FIREFOX_CAMOUFOX)
    _console_error(session, "boom at checkout")

    assert "boom at checkout" in session.get_console_log()
