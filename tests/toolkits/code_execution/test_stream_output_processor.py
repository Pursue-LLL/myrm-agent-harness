"""Tests for StreamOutputProcessor: SSE ANSI sanitization, throttle, valve, and tee."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.code_execution.session.stream_output_processor import (
    StreamOutputProcessor,
)


class TestAnsiStripping:
    """Verify that accumulate_sse strips ANSI escape sequences before accumulation."""

    def test_strips_csi_color_codes(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        result = sop.accumulate_sse("\x1b[31mERROR\x1b[0m: failed")
        assert result == "ERROR: failed"
        assert "\x1b" not in result

    def test_strips_multiple_ansi_sequences(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        text = "\x1b[1m\x1b[32mPASSED\x1b[0m test_foo \x1b[90m(0.1s)\x1b[0m"
        result = sop.accumulate_sse(text)
        assert result == "PASSED test_foo (0.1s)"

    def test_strips_osc_sequences(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        text = "\x1b]0;window title\x07real content"
        result = sop.accumulate_sse(text)
        assert result == "real content"

    def test_clean_text_passes_through_unchanged(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        clean = "hello world\nno escapes here"
        result = sop.accumulate_sse(clean)
        assert result == clean

    def test_empty_string(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        result = sop.accumulate_sse("")
        assert result == ""

    def test_flush_returns_stripped_content(self) -> None:
        """flush() returns already-stripped text from accumulation buffer."""
        sop = StreamOutputProcessor()
        # Don't expire throttle so text stays in buffer
        sop._last_sse_time = time.monotonic()

        sop.accumulate_sse("\x1b[31mred\x1b[0m")
        result = sop.flush()
        assert result == "red"
        assert "\x1b" not in result

    def test_valve_bytes_count_based_on_stripped_text(self) -> None:
        """_sse_bytes_sent should be based on stripped (clean) text length."""
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        ansi_text = "\x1b[31m" + "x" * 10 + "\x1b[0m"
        sop.accumulate_sse(ansi_text)
        # 10 bytes of actual content, not 10 + len("\x1b[31m\x1b[0m")
        assert sop._sse_bytes_sent == 10

    def test_strips_8bit_c1_control(self) -> None:
        """8-bit C1 CSI (0x9B) followed by SGR should be stripped."""
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        text = "\x9b31mRED\x9b0m"
        result = sop.accumulate_sse(text)
        assert result == "RED"

    def test_strips_cursor_movement(self) -> None:
        """CSI cursor sequences (e.g. \\x1b[2K erase line) should be stripped."""
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        text = "\x1b[2K\x1b[1Gprogress: 50%"
        result = sop.accumulate_sse(text)
        assert result == "progress: 50%"

    def test_npm_style_colored_output(self) -> None:
        """Simulate npm install colored output."""
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        text = "\x1b[32m+\x1b[39m \x1b[1mreact\x1b[22m@18.2.0\n"
        result = sop.accumulate_sse(text)
        assert result == "+ react@18.2.0\n"
        assert "\x1b" not in result

    def test_fast_path_no_copy_for_clean_text(self) -> None:
        """strip_ansi returns same object reference for clean text (zero-copy)."""
        from myrm_agent_harness.utils.text_utils import strip_ansi

        clean = "hello world"
        assert strip_ansi(clean) is clean


class TestThrottle:
    """Verify throttle behavior is not broken by ANSI stripping."""

    def test_accumulates_within_throttle_interval(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic()

        assert sop.accumulate_sse("chunk1") is None
        assert sop.accumulate_sse("chunk2") is None

        result = sop.flush()
        assert result == "chunk1chunk2"

    def test_emits_after_throttle_interval(self) -> None:
        sop = StreamOutputProcessor()
        sop._last_sse_time = time.monotonic() - 1.0

        result = sop.accumulate_sse("ready")
        assert result == "ready"


class TestValve:
    """Verify valve triggers correctly with stripped byte counts."""

    def test_valve_triggers_on_large_output(self) -> None:
        sop = StreamOutputProcessor()
        sop.setup_tee("/tmp")
        sop._last_sse_time = time.monotonic() - 1.0

        big_text = "x" * 600_000
        result = sop.accumulate_sse(big_text)
        assert result is not None
        assert "Terminal stream suspended" in result
        assert sop.valve_triggered

    def test_after_valve_returns_none(self) -> None:
        sop = StreamOutputProcessor()
        sop.setup_tee("/tmp")
        sop._last_sse_time = time.monotonic() - 1.0

        sop.accumulate_sse("x" * 600_000)
        sop._last_sse_time = time.monotonic() - 1.0
        assert sop.accumulate_sse("more") is None


class TestTeeNotStripped:
    """Verify that write_tee receives original text (not stripped)."""

    @pytest.mark.asyncio
    async def test_tee_gets_raw_text(self) -> None:
        """write_tee is called before accumulate_sse in the pipeline,
        so it should receive the original unstripped text. This test
        validates the architectural contract."""
        sop = StreamOutputProcessor()
        sop.setup_tee("/tmp")

        mock_file = AsyncMock()
        raw_text = "\x1b[31mERROR\x1b[0m: failed"

        await sop.write_tee(mock_file, raw_text)
        mock_file.write.assert_called_once_with(raw_text)
