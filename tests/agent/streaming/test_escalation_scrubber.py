"""Unit tests for EscalationScrubber — model self-escalation marker detection."""


from myrm_agent_harness.agent.streaming.escalation_scrubber import (
    EscalationScrubber,
    _could_be_partial_marker,
)


class TestEscalationScrubberDisabled:
    def test_passes_through_when_disabled(self):
        s = EscalationScrubber(enabled=False)
        assert s.process("<<<NEEDS_PRO>>>") == "<<<NEEDS_PRO>>>"
        assert s.detected is False

    def test_flush_returns_none_when_disabled(self):
        s = EscalationScrubber(enabled=False)
        s.process("hello")
        assert s.flush() is None


class TestEscalationScrubberDetection:
    def test_detects_basic_marker(self):
        s = EscalationScrubber(enabled=True)
        result = s.process("<<<NEEDS_PRO>>>")
        assert result is None
        assert s.detected is True
        assert s.reason is None

    def test_detects_marker_with_reason(self):
        s = EscalationScrubber(enabled=True)
        result = s.process("<<<NEEDS_PRO: complex mathematical proof>>>")
        assert result is None
        assert s.detected is True
        assert s.reason == "complex mathematical proof"

    def test_detects_marker_with_leading_whitespace(self):
        s = EscalationScrubber(enabled=True)
        r1 = s.process("   ")
        assert r1 is None
        r2 = s.process("<<<NEEDS_PRO>>>")
        assert r2 is None
        assert s.detected is True

    def test_cross_chunk_marker_detection(self):
        s = EscalationScrubber(enabled=True)
        chunks = ["<<<", "NEEDS", "_PRO", ">>>"]
        for c in chunks:
            result = s.process(c)
            assert result is None
        assert s.detected is True

    def test_character_by_character_detection(self):
        s = EscalationScrubber(enabled=True)
        marker = "<<<NEEDS_PRO: deep reasoning>>>"
        for char in marker:
            result = s.process(char)
            assert result is None
        assert s.detected is True
        assert s.reason == "deep reasoning"

    def test_suppresses_content_after_detection(self):
        s = EscalationScrubber(enabled=True)
        s.process("<<<NEEDS_PRO>>>")
        assert s.detected is True
        result = s.process("This should be suppressed")
        assert result is None


class TestEscalationScrubberPassthrough:
    def test_non_marker_content_forwarded(self):
        s = EscalationScrubber(enabled=True)
        result = s.process("Hello, I can help you with that task.")
        assert result is not None
        assert "Hello" in result

    def test_short_non_marker_forwarded_immediately(self):
        s = EscalationScrubber(enabled=True)
        result = s.process("Hi")
        assert result == "Hi"

    def test_decided_state_passes_through(self):
        s = EscalationScrubber(enabled=True)
        s.process("Normal text that is clearly not a marker.")
        r2 = s.process("Second chunk")
        assert r2 == "Second chunk"

    def test_buffer_overflow_flushes(self):
        """When buffer fills up with a valid partial prefix, overflow triggers flush."""
        s = EscalationScrubber(enabled=True, buffer_size=30)
        # Feed content that looks like partial marker prefix (stays in buffer)
        r1 = s.process("<<<NEEDS_PRO")
        assert r1 is None  # still buffering — matches prefix
        # Feed enough to overflow buffer without completing marker
        r2 = s.process("X" * 30)
        # Overflow triggers decision: not a valid marker → flush all
        assert r2 is not None
        assert "<<<NEEDS_PRO" in r2
        assert s.detected is False


class TestEscalationScrubberFlush:
    def test_flush_returns_buffered_partial_marker(self):
        s = EscalationScrubber(enabled=True)
        s.process("<<<")
        flushed = s.flush()
        assert flushed == "<<<"

    def test_flush_returns_none_when_empty(self):
        s = EscalationScrubber(enabled=True)
        assert s.flush() is None

    def test_flush_returns_none_after_detection(self):
        s = EscalationScrubber(enabled=True)
        s.process("<<<NEEDS_PRO>>>")
        assert s.flush() is None


class TestEscalationScrubberReset:
    def test_reset_clears_all_state(self):
        s = EscalationScrubber(enabled=True)
        s.process("<<<NEEDS_PRO: reason>>>")
        assert s.detected is True
        assert s.reason == "reason"

        s.reset()
        assert s.detected is False
        assert s.reason is None

    def test_reset_allows_new_detection(self):
        s = EscalationScrubber(enabled=True)
        s.process("<<<NEEDS_PRO>>>")
        s.reset()

        result = s.process("Normal response after reset")
        assert result is not None
        assert "Normal response" in result
        assert s.detected is False


class TestEscalationScrubberEdgeCases:
    def test_buffer_overflow_with_valid_prefix(self):
        """Buffer fills up with content that starts with the marker prefix."""
        s = EscalationScrubber(enabled=True, buffer_size=20)
        # "<<<NEEDS_PRO:" matches prefix and has colon → stays in buffer
        r1 = s.process("<<<NEEDS_PRO:")
        assert r1 is None
        # Feed more to overflow
        r2 = s.process("X" * 20)
        assert r2 is not None
        assert "<<<NEEDS_PRO:" in r2
        assert s.detected is False

    def test_flush_after_detection_returns_none(self):
        """Flush after detection discards any buffered content."""
        s = EscalationScrubber(enabled=True)
        s.process("<<<NEEDS_PRO>>>")
        assert s.detected is True
        # Manually set buffer to simulate edge case
        s._buffer = "leftover"
        result = s.flush()
        assert result is None


class TestCouldBePartialMarker:
    def test_exact_prefix_match(self):
        assert _could_be_partial_marker("<<<NEEDS_PRO", "<<<NEEDS_PRO") is True

    def test_shorter_than_prefix(self):
        assert _could_be_partial_marker("<<<NE", "<<<NEEDS_PRO") is True

    def test_non_matching(self):
        assert _could_be_partial_marker("Hello", "<<<NEEDS_PRO") is False

    def test_prefix_plus_colon(self):
        assert _could_be_partial_marker("<<<NEEDS_PRO:", "<<<NEEDS_PRO") is True

    def test_prefix_plus_angle(self):
        assert _could_be_partial_marker("<<<NEEDS_PRO>", "<<<NEEDS_PRO") is True

    def test_prefix_plus_invalid_char(self):
        assert _could_be_partial_marker("<<<NEEDS_PROX", "<<<NEEDS_PRO") is False
