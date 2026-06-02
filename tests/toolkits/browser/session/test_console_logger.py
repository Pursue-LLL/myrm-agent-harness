"""Tests for ConsoleLogger — browser console message capture and formatting.

Covers:
- ConsoleEntry: frozen dataclass, is_error property
- ConsoleLogger._cb_console: message capture, text truncation, exception safety
- ConsoleLogger._cb_pageerror: page error capture, exception safety
- ConsoleLogger.start_capture: page binding, idempotent, auto-detach
- ConsoleLogger.detach_page: correct page matching, mismatched page no-op
- ConsoleLogger.detach_current: safe when no binding
- ConsoleLogger.stop_capture: detach without clearing entries
- ConsoleLogger.get_summary: empty, with messages, errors_only, truncation at 30
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.console_logger import (
    _ERROR_TYPES,
    _MAX_TEXT_LENGTH,
    ConsoleEntry,
    ConsoleLogger,
)


class TestConsoleEntry:
    """ConsoleEntry dataclass behavior."""

    def test_basic_fields(self) -> None:
        entry = ConsoleEntry(level="log", text="Hello", url="http://x.com:10", timestamp=1.0)
        assert entry.level == "log"
        assert entry.text == "Hello"
        assert entry.url == "http://x.com:10"
        assert entry.timestamp == 1.0

    def test_is_error_for_error_level(self) -> None:
        entry = ConsoleEntry(level="error", text="err", url="", timestamp=0)
        assert entry.is_error is True

    def test_is_error_for_warning_level(self) -> None:
        entry = ConsoleEntry(level="warning", text="warn", url="", timestamp=0)
        assert entry.is_error is True

    def test_is_error_false_for_log(self) -> None:
        entry = ConsoleEntry(level="log", text="info", url="", timestamp=0)
        assert entry.is_error is False

    def test_is_error_false_for_info(self) -> None:
        entry = ConsoleEntry(level="info", text="info", url="", timestamp=0)
        assert entry.is_error is False

    def test_frozen_immutability(self) -> None:
        entry = ConsoleEntry(level="log", text="x", url="", timestamp=0)
        with pytest.raises(AttributeError):
            entry.level = "error"  # type: ignore[misc]

    def test_slots_present(self) -> None:
        assert hasattr(ConsoleEntry, "__slots__")


class TestConsoleLoggerCbConsole:
    """ConsoleLogger._cb_console callback behavior."""

    def test_captures_console_message(self) -> None:
        logger = ConsoleLogger()
        msg = MagicMock()
        msg.text = "Test message"
        msg.type = "log"
        msg.location = {"url": "http://test.com/app.js", "lineNumber": 42}

        logger._cb_console(msg)

        assert len(logger._entries) == 1
        entry = logger._entries[0]
        assert entry.text == "Test message"
        assert entry.level == "log"
        assert "test.com/app.js:42" in entry.url

    def test_truncates_long_text(self) -> None:
        logger = ConsoleLogger()
        msg = MagicMock()
        msg.text = "x" * 1000
        msg.type = "error"
        msg.location = None

        logger._cb_console(msg)

        assert len(logger._entries[0].text) == _MAX_TEXT_LENGTH

    def test_handles_none_location(self) -> None:
        logger = ConsoleLogger()
        msg = MagicMock()
        msg.text = "No location"
        msg.type = "log"
        msg.location = None

        logger._cb_console(msg)

        assert logger._entries[0].url == ""

    def test_handles_empty_location(self) -> None:
        logger = ConsoleLogger()
        msg = MagicMock()
        msg.text = "Empty loc"
        msg.type = "log"
        msg.location = {}

        logger._cb_console(msg)

        # Empty dict is falsy in Python, so url should be ""
        assert logger._entries[0].url == ""

    def test_exception_in_callback_does_not_raise(self) -> None:
        logger = ConsoleLogger()
        msg = MagicMock()
        msg.text = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        msg.type = "log"

        broken_msg = MagicMock()
        type(broken_msg).text = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

        logger._cb_console(broken_msg)
        assert len(logger._entries) == 0

    def test_max_entries_bounded(self) -> None:
        logger = ConsoleLogger(max_entries=5)
        for i in range(10):
            msg = MagicMock()
            msg.text = f"msg-{i}"
            msg.type = "log"
            msg.location = None
            logger._cb_console(msg)

        assert len(logger._entries) == 5
        assert logger._entries[0].text == "msg-5"
        assert logger._entries[-1].text == "msg-9"


class TestConsoleLoggerCbPageerror:
    """ConsoleLogger._cb_pageerror callback behavior."""

    def test_captures_page_error(self) -> None:
        logger = ConsoleLogger()
        error = RuntimeError("Uncaught TypeError: x is undefined")

        logger._cb_pageerror(error)

        assert len(logger._entries) == 1
        entry = logger._entries[0]
        assert entry.level == "error"
        assert "[PageError]" in entry.text
        assert "TypeError" in entry.text

    def test_truncates_long_error(self) -> None:
        logger = ConsoleLogger()
        error = RuntimeError("x" * 1000)

        logger._cb_pageerror(error)

        text = logger._entries[0].text
        assert len(text) <= _MAX_TEXT_LENGTH + len("[PageError] ")

    def test_exception_in_callback_does_not_raise(self) -> None:
        logger = ConsoleLogger()

        class BadError:
            def __str__(self):
                raise ValueError("cannot stringify")

        logger._cb_pageerror(BadError())
        assert len(logger._entries) == 0


class TestConsoleLoggerStartCapture:
    """ConsoleLogger.start_capture lifecycle management."""

    def test_binds_to_page(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()

        logger.start_capture(page)

        assert logger._bound_page is page
        page.on.assert_any_call("console", logger._cb_console)
        page.on.assert_any_call("pageerror", logger._cb_pageerror)

    def test_idempotent_same_page(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()

        logger.start_capture(page)
        logger.start_capture(page)

        assert page.on.call_count == 2  # only first time: console + pageerror

    def test_auto_detach_previous_page(self) -> None:
        logger = ConsoleLogger()
        page1 = MagicMock()
        page2 = MagicMock()

        logger.start_capture(page1)
        logger.start_capture(page2)

        page1.off.assert_any_call("console", logger._cb_console)
        page1.off.assert_any_call("pageerror", logger._cb_pageerror)
        assert logger._bound_page is page2


class TestConsoleLoggerDetach:
    """ConsoleLogger.detach_page and detach_current behavior."""

    def test_detach_matching_page(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()
        logger.start_capture(page)

        logger.detach_page(page)

        page.off.assert_any_call("console", logger._cb_console)
        page.off.assert_any_call("pageerror", logger._cb_pageerror)
        assert logger._bound_page is None

    def test_detach_mismatched_page_noop(self) -> None:
        logger = ConsoleLogger()
        page1 = MagicMock()
        page2 = MagicMock()
        logger.start_capture(page1)

        logger.detach_page(page2)

        page2.off.assert_not_called()
        assert logger._bound_page is page1

    def test_detach_current_clears_binding(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()
        logger.start_capture(page)

        logger.detach_current()

        assert logger._bound_page is None

    def test_detach_current_noop_when_unbound(self) -> None:
        logger = ConsoleLogger()
        logger.detach_current()  # should not raise

    def test_detach_handles_exception_in_off(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()
        page.off.side_effect = RuntimeError("page closed")
        logger._bound_page = page

        logger.detach_page(page)

        assert logger._bound_page is None


class TestConsoleLoggerStopCapture:
    """ConsoleLogger.stop_capture behavior."""

    def test_stop_detaches_page(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()
        logger.start_capture(page)

        logger.stop_capture()

        assert logger._bound_page is None

    def test_stop_preserves_entries(self) -> None:
        logger = ConsoleLogger()
        page = MagicMock()
        logger.start_capture(page)

        msg = MagicMock()
        msg.text = "kept"
        msg.type = "log"
        msg.location = None
        logger._cb_console(msg)

        logger.stop_capture()

        assert len(logger._entries) == 1
        assert logger._entries[0].text == "kept"


class TestConsoleLoggerGetSummary:
    """ConsoleLogger.get_summary formatting."""

    def test_empty_returns_no_messages(self) -> None:
        logger = ConsoleLogger()
        result = logger.get_summary()
        assert "No console messages captured." in result

    def test_empty_errors_only_returns_no_errors(self) -> None:
        logger = ConsoleLogger()
        result = logger.get_summary(errors_only=True)
        assert "No console errors." in result

    def test_single_entry_formatting(self) -> None:
        logger = ConsoleLogger()
        logger._entries.append(
            ConsoleEntry(level="error", text="ReferenceError: x", url="app.js:10", timestamp=time.time())
        )

        result = logger.get_summary()

        assert "[ERROR]" in result
        assert "ReferenceError: x" in result
        assert "(app.js:10)" in result
        assert "1/1 entries" in result

    def test_multiple_levels(self) -> None:
        logger = ConsoleLogger()
        logger._entries.append(ConsoleEntry(level="log", text="info msg", url="", timestamp=time.time()))
        logger._entries.append(ConsoleEntry(level="warning", text="warn msg", url="", timestamp=time.time()))
        logger._entries.append(ConsoleEntry(level="error", text="err msg", url="", timestamp=time.time()))

        result = logger.get_summary()

        assert "[LOG]" in result
        assert "[WARNING]" in result
        assert "[ERROR]" in result
        assert "3/3 entries" in result

    def test_errors_only_filters(self) -> None:
        logger = ConsoleLogger()
        logger._entries.append(ConsoleEntry(level="log", text="info", url="", timestamp=time.time()))
        logger._entries.append(ConsoleEntry(level="error", text="err", url="", timestamp=time.time()))
        logger._entries.append(ConsoleEntry(level="warning", text="warn", url="", timestamp=time.time()))

        result = logger.get_summary(errors_only=True)

        assert "err" in result
        assert "warn" in result
        assert "info" not in result
        assert "errors only" in result

    def test_max_30_shown(self) -> None:
        logger = ConsoleLogger(max_entries=200)
        for i in range(50):
            logger._entries.append(
                ConsoleEntry(level="error", text=f"err-{i}", url="", timestamp=time.time())
            )

        result = logger.get_summary()

        assert "30/50 entries" in result
        assert "err-49" in result
        assert "err-20" in result
        assert "err-19" not in result

    def test_url_omitted_when_empty(self) -> None:
        logger = ConsoleLogger()
        logger._entries.append(ConsoleEntry(level="log", text="no url", url="", timestamp=time.time()))

        result = logger.get_summary()

        assert "()" not in result
        assert "no url" in result

    def test_header_format(self) -> None:
        logger = ConsoleLogger()
        logger._entries.append(ConsoleEntry(level="log", text="x", url="", timestamp=time.time()))

        result = logger.get_summary()

        assert result.startswith("Console log (")


class TestConsoleLoggerConstants:
    """Verify module constants."""

    def test_error_types(self) -> None:
        assert "error" in _ERROR_TYPES
        assert "warning" in _ERROR_TYPES
        assert "log" not in _ERROR_TYPES

    def test_max_text_length(self) -> None:
        assert _MAX_TEXT_LENGTH == 500
