"""Tests for HookOutputSpiller — oversized hook output disk spill."""

import pytest

from myrm_agent_harness.agent.hooks.output_spiller import (
    HOOK_OUTPUT_TOKEN_LIMIT,
    HookOutputSpiller,
    _build_preview,
    _truncate_preview,
    spill_hook_contexts,
)

# Realistic multi-word text that resists BPE compression
_LONG_TEXT = "This is a realistic hook output that contains actual words and sentences. It provides context information about the tool execution results. " * 300  # ~6900 tokens


@pytest.fixture
def spiller(tmp_path):
    return HookOutputSpiller(output_dir=tmp_path / "hook_outputs")


class TestHookOutputSpiller:
    """Core spiller behavior."""

    @pytest.mark.asyncio
    async def test_short_text_passes_through(self, spiller):
        text = "Hello, this is a short hook output."
        result = await spiller.maybe_spill_text(text, session_id="s1")
        assert result == text

    @pytest.mark.asyncio
    async def test_empty_text_passes_through(self, spiller):
        result = await spiller.maybe_spill_text("", session_id="s1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_long_text_spilled_to_disk(self, spiller):
        result = await spiller.maybe_spill_text(_LONG_TEXT, session_id="s1")

        assert "Full hook output saved to:" in result
        assert ".txt" in result

        files = list((spiller._output_dir / "s1").glob("*.txt"))
        assert len(files) == 1
        assert files[0].read_text(encoding="utf-8") == _LONG_TEXT

    @pytest.mark.asyncio
    async def test_spilled_preview_is_shorter_than_original(self, spiller):
        result = await spiller.maybe_spill_text(_LONG_TEXT, session_id="s1")
        assert len(result) < len(_LONG_TEXT)

    @pytest.mark.asyncio
    async def test_anonymous_session_uses_anonymous_dir(self, spiller):
        await spiller.maybe_spill_text(_LONG_TEXT, session_id="")
        files = list((spiller._output_dir / "anonymous").glob("*.txt"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_batch_spill(self, spiller):
        texts = [
            "short text",
            _LONG_TEXT,
            "another short",
            _LONG_TEXT,
        ]
        results = await spiller.maybe_spill_texts(texts, session_id="batch")

        assert results[0] == "short text"
        assert results[2] == "another short"
        assert "Full hook output saved to:" in results[1]
        assert "Full hook output saved to:" in results[3]


class TestTruncatePreview:
    """Fallback truncation when disk write fails."""

    def test_short_text_unchanged(self):
        text = "short"
        assert _truncate_preview(text) == text

    def test_long_text_truncated(self):
        text = _LONG_TEXT
        result = _truncate_preview(text)
        assert len(result) < len(text)
        assert result.endswith("...[truncated]")


class TestBuildPreview:
    """Preview format with head/tail + file path."""

    def test_short_text_with_footer(self, tmp_path):
        text = "hello world"
        path = tmp_path / "test.txt"
        result = _build_preview(text, path)
        assert result == f"hello world\n\nFull hook output saved to: {path}"

    def test_long_text_has_omission_marker(self, tmp_path):
        path = tmp_path / "test.txt"
        result = _build_preview(_LONG_TEXT, path)
        assert "chars omitted" in result
        assert f"Full hook output saved to: {path}" in result


class TestSpillHookContexts:
    """Convenience function for batch spilling."""

    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await spill_hook_contexts([])
        assert result == []

    @pytest.mark.asyncio
    async def test_short_contexts_unchanged(self):
        contexts = ["hello", "world"]
        result = await spill_hook_contexts(contexts)
        assert result == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_mixed_contexts(self, tmp_path):
        spiller = HookOutputSpiller(output_dir=tmp_path / "out")
        contexts = ["short", _LONG_TEXT, "also short"]
        result = await spill_hook_contexts(contexts, session_id="test", spiller=spiller)

        assert result[0] == "short"
        assert "Full hook output saved to:" in result[1]
        assert result[2] == "also short"


class TestThresholdConstant:
    """Verify threshold matches codex-cli."""

    def test_threshold_value(self):
        assert HOOK_OUTPUT_TOKEN_LIMIT == 2500
