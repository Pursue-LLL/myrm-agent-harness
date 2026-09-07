"""Unit tests for ContextGuard SpilloverEngine and EphemeralTransientSweeper."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from myrm_agent_harness.agent.context_guard import (
    ContextGuardConfig,
    EphemeralTransientSweeper,
    SpilloverEngine,
)


def test_spillover_engine_under_limit(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=100)
    engine = SpilloverEngine(config=config)

    content = "Hello, world! This is a short prompt."
    result = engine.process_content(content, base_dir=tmp_path)

    assert not result.spilled
    assert result.sanitized_content == content
    assert result.original_char_count == len(content)
    assert result.payload is None


def test_spillover_engine_over_limit_triggers_spill(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=50, preview_chars=20)
    engine = SpilloverEngine(config=config)

    large_text = "Line 1: System crash log data\n" * 10
    result = engine.process_content(large_text, base_dir=tmp_path, role="user")

    assert result.spilled
    assert result.original_char_count == len(large_text)
    assert result.payload is not None
    assert Path(result.payload.file_path).exists()
    assert Path(result.payload.file_path).read_text(encoding="utf-8") == large_text
    assert result.payload.char_count == len(large_text)
    assert result.payload.line_count == large_text.count("\n") + 1
    assert "System Notice" in result.sanitized_content
    assert result.payload.file_path in result.sanitized_content


def test_spillover_engine_multimodal_list_extraction(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=40)
    engine = SpilloverEngine(config=config)

    complex_content = [
        {"type": "text", "text": "Header block: "},
        {"type": "text", "text": "Detailed log trace information exceeding forty characters here."},
    ]
    result = engine.process_content(complex_content, base_dir=tmp_path)

    assert result.spilled
    assert result.payload is not None
    assert "Detailed log trace" in Path(result.payload.file_path).read_text(encoding="utf-8")


def test_ephemeral_transient_sweeper(tmp_path: Path) -> None:
    config = ContextGuardConfig(spillover_ttl_seconds=1.0)
    sweeper = EphemeralTransientSweeper(config=config)

    spill_dir = tmp_path / config.spillover_dir_name
    spill_dir.mkdir(parents=True, exist_ok=True)

    file_old = spill_dir / "payload_old.md"
    file_old.write_text("old data", encoding="utf-8")
    # Set modification time back 10 seconds
    past_time = time.time() - 10.0
    os.utime(file_old, (past_time, past_time))

    file_fresh = spill_dir / "payload_fresh.md"
    file_fresh.write_text("fresh data", encoding="utf-8")

    removed = sweeper.sweep_directory(tmp_path)
    assert removed == 1
    assert not file_old.exists()
    assert file_fresh.exists()
