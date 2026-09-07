from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.types import ContextGuardConfig


def test_spillover_short_text_no_spill() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = SpilloverEngine(ContextGuardConfig(max_message_chars=100))
        res = engine.process_content("hello world", base_dir=tmpdir)
        assert res.spilled is False
        assert res.sanitized_content == "hello world"
        assert res.original_char_count == 11


def test_spillover_long_text_spilled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = SpilloverEngine(ContextGuardConfig(max_message_chars=20))
        long_content = "This is a very long text that definitely exceeds twenty characters limit."
        res = engine.process_content(long_content, base_dir=tmpdir)
        assert res.spilled is True
        assert res.payload is not None
        assert Path(res.payload.file_path).exists()
        assert Path(res.payload.file_path).read_text(encoding="utf-8") == long_content


def test_spillover_multimodal_list_content() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = SpilloverEngine(ContextGuardConfig(max_message_chars=20))
        parts = [
            {"type": "text", "text": "Part one content"},
            {"type": "text", "text": "Part two content"},
        ]
        res = engine.process_content(parts, base_dir=tmpdir)
        assert res.spilled is True
        assert "Part one content\nPart two content" in Path(res.payload.file_path).read_text(encoding="utf-8")
