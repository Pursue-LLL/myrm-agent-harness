from __future__ import annotations

import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper
from myrm_agent_harness.agent.context_guard.types import ContextGuardConfig


def test_spillover_engine_under_threshold(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=100, preview_chars=20)
    engine = SpilloverEngine(config)

    content = "Small message well under threshold"
    result = engine.process_content(content, base_dir=tmp_path)

    assert not result.spilled
    assert result.sanitized_content == content
    assert result.payload is None
    assert result.original_char_count == len(content)


def test_spillover_engine_over_threshold_creates_atomic_file(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=50, preview_chars=20)
    engine = SpilloverEngine(config)

    large_content = "A" * 120 + "\nLine 2 content here\nLine 3"
    result = engine.process_content(large_content, base_dir=tmp_path, session_id="test_sess_123")

    assert result.spilled
    assert result.payload is not None
    assert result.payload.char_count == len(large_content)
    assert result.payload.line_count == 3
    assert Path(result.payload.file_path).exists()
    assert "<file_spillover" in result.sanitized_content
    assert "read_file" in result.sanitized_content

    # Verify content fidelity
    persisted_text = Path(result.payload.file_path).read_text(encoding="utf-8")
    assert persisted_text == large_content


def test_ephemeral_transient_sweeper_cleans_expired(tmp_path: Path) -> None:
    config = ContextGuardConfig(spillover_ttl_seconds=10)
    sweeper = EphemeralTransientSweeper(config)

    spill_dir = tmp_path / config.spillover_dir_name
    spill_dir.mkdir(parents=True, exist_ok=True)

    # Fresh file
    fresh_file = spill_dir / "fresh.md"
    fresh_file.write_text("fresh", encoding="utf-8")

    # Expired file
    old_file = spill_dir / "old.md"
    old_file.write_text("old", encoding="utf-8")
    old_time = time.time() - 20
    import os

    os.utime(old_file, (old_time, old_time))

    removed = sweeper.sweep_directory(tmp_path)
    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()
