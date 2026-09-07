from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_guard import (
    ContextGuardConfig,
    EphemeralTransientSweeper,
    SpilloverEngine,
    SpilloverPayload,
    SpilloverResult,
)


def test_spillover_engine_under_threshold(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=100)
    engine = SpilloverEngine(config=config)

    short_content = "Hello, this is a short message."
    result = engine.process_content(short_content, base_dir=tmp_path)

    assert not result.spilled
    assert result.sanitized_content == short_content
    assert result.original_char_count == len(short_content)
    assert result.payload is None


def test_spillover_engine_over_threshold_creates_file(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=50, preview_chars=20)
    engine = SpilloverEngine(config=config)

    long_content = "A" * 120 + "\nLine 2 content here\nLine 3"
    result = engine.process_content(long_content, base_dir=tmp_path, role="user")

    assert result.spilled
    assert result.original_char_count == len(long_content)
    assert result.payload is not None
    assert isinstance(result.payload, SpilloverPayload)
    assert result.payload.char_count == len(long_content)
    assert result.payload.line_count == 3
    assert result.payload.sha256_digest == hashlib.sha256(long_content.encode("utf-8")).hexdigest()

    # Check file existence and content
    target_path = Path(result.payload.file_path)
    assert target_path.exists()
    assert target_path.read_text(encoding="utf-8") == long_content

    # Check sanitized prompt contains preview and path
    assert result.payload.file_path in result.sanitized_content
    assert "read_file" in result.sanitized_content
    assert "System Notice:" in result.sanitized_content


def test_spillover_multimodal_list_content(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=40)
    engine = SpilloverEngine(config=config)

    multimodal_content: list[dict[str, object] | str] = [
        {"type": "text", "text": "This is part 1 of the prompt. "},
        {"type": "text", "text": "And this is part 2 which makes it overflow beyond 40 characters."},
    ]
    result = engine.process_content(multimodal_content, base_dir=tmp_path)

    assert result.spilled
    assert result.payload is not None
    assert Path(result.payload.file_path).exists()
    assert "part 1" in Path(result.payload.file_path).read_text(encoding="utf-8")


def test_ephemeral_sweeper_cleans_stale_files(tmp_path: Path) -> None:
    config = ContextGuardConfig(spillover_ttl_seconds=10)
    sweeper = EphemeralTransientSweeper(config=config)

    spill_dir = tmp_path / config.spillover_dir_name
    spill_dir.mkdir(parents=True, exist_ok=True)

    file_old = spill_dir / "old_payload.md"
    file_old.write_text("old content", encoding="utf-8")

    file_fresh = spill_dir / "fresh_payload.md"
    file_fresh.write_text("fresh content", encoding="utf-8")

    # Mock mtime
    past_time = time.time() - 100
    import os
    os.utime(file_old, (past_time, past_time))

    removed = sweeper.sweep_directory(tmp_path)
    assert removed == 1
    assert not file_old.exists()
    assert file_fresh.exists()
