"""Tests for StreamRepetitionScrubber."""

from __future__ import annotations

from myrm_agent_harness.agent.streaming.repetition_scrubber import StreamRepetitionScrubber
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken


class TestStreamRepetitionScrubber:
    """Unit tests verifying repetition detection, code block bypass, and cancellation."""

    def test_normal_text_not_blocked(self) -> None:
        scrubber = StreamRepetitionScrubber()
        chunks = [
            "Hello! Today we will explore how AI agents handle long-running tasks. ",
            "First, let's understand the problem domain and architectural requirements. ",
            "Second, we will review various strategies for state preservation and recovery. ",
            "Finally, we will write comprehensive test cases to verify the implementation.",
        ]
        output = []
        for chunk in chunks:
            res = scrubber.process(chunk)
            assert res is not None
            output.append(res)

        assert not scrubber.detected
        assert scrubber.aborted_reason is None
        assert "".join(output) == "".join(chunks)

    def test_repetition_loop_aborted(self) -> None:
        token = CancellationToken()
        scrubber = StreamRepetitionScrubber(cancel_token=token)

        loop_line = "Error: connection timed out while reading socket buffer.\n"
        chunks = [loop_line for _ in range(15)]

        aborted_at = None
        for i, chunk in enumerate(chunks):
            res = scrubber.process(chunk)
            if res is None:
                aborted_at = i
                break

        assert scrubber.detected is True
        assert token.is_cancelled is True
        assert aborted_at is not None
        assert "Model repetition loop detected" in (scrubber.aborted_reason or "")

    def test_code_block_threshold_scaling(self) -> None:
        """Repetitive data inside Markdown code block is not prematurely aborted."""
        scrubber = StreamRepetitionScrubber()

        # Markdown code block with repeated struct patterns
        code_chunks = [
            "Here is the database schema definition:\n```sql\n",
            "CREATE TABLE user_record_01 (id INT, status VARCHAR(20));\n",
            "CREATE TABLE user_record_02 (id INT, status VARCHAR(20));\n",
            "CREATE TABLE user_record_03 (id INT, status VARCHAR(20));\n",
            "CREATE TABLE user_record_04 (id INT, status VARCHAR(20));\n",
            "CREATE TABLE user_record_05 (id INT, status VARCHAR(20));\n",
            "```\nHope this helps!",
        ]

        for chunk in code_chunks:
            res = scrubber.process(chunk)
            assert res is not None

        assert not scrubber.detected

    def test_split_backtick_across_chunks(self) -> None:
        """Backticks split across chunk boundaries (e.g. `` + `) are accurately detected."""
        scrubber = StreamRepetitionScrubber()

        # Split ``` across chunks
        chunks = [
            "Here is the code:\n``",  # Chunk 1 ends with 2 backticks
            "`python\n",               # Chunk 2 starts with 1 backtick
            "print('Hello world 01')\n",
            "print('Hello world 02')\n",
            "print('Hello world 03')\n",
            "print('Hello world 04')\n",
            "print('Hello world 05')\n",
            "``",                      # Chunk 8 ends with 2 backticks
            "`\nDone!",                # Chunk 9 completes closing fence
        ]

        for chunk in chunks:
            res = scrubber.process(chunk)
            assert res is not None

        assert scrubber._in_code_block is False
        assert scrubber.detected is False
