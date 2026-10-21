from __future__ import annotations

import time
from pathlib import Path

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper
from myrm_agent_harness.agent.context_guard.types import ContextGuardConfig


def test_spillover_engine_under_threshold(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=100)
    engine = SpilloverEngine(config=config)
    short_text = "Hello world, this is a normal length query."
    result = engine.process_content(short_text, base_dir=tmp_path)

    assert result.spilled is False
    assert result.sanitized_content == short_text
    assert result.payload is None
    assert result.original_char_count == len(short_text)


def test_spillover_engine_over_threshold_creates_file(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=50, preview_chars=20)
    engine = SpilloverEngine(config=config)
    long_text = "A" * 150
    result = engine.process_content(long_text, base_dir=tmp_path, role="user")

    assert result.spilled is True
    assert result.payload is not None
    assert result.original_char_count == 150
    assert result.payload.char_count == 150
    assert len(result.payload.sha256_digest) == 64

    # Verify file was written on disk
    target_path = Path(result.payload.file_path)
    assert target_path.exists()
    assert target_path.read_text(encoding="utf-8") == long_text

    # Verify sanitized content format
    assert "<file_spillover" in result.sanitized_content
    assert result.payload.relative_path in result.sanitized_content
    assert result.payload.sha256_digest[:16] in result.sanitized_content


def test_spillover_engine_multimodal_extraction(tmp_path: Path) -> None:
    config = ContextGuardConfig(max_message_chars=50)
    engine = SpilloverEngine(config=config)
    multimodal_payload = [
        {"type": "image_url", "url": "https://example.com/test.png"},
        {"type": "text", "text": "B" * 100},
    ]
    result = engine.process_content(multimodal_payload, base_dir=tmp_path)

    assert result.spilled is True
    assert result.original_char_count == 100
    assert result.payload is not None
    assert Path(result.payload.file_path).exists()


def test_transient_sweeper_cleans_expired_files(tmp_path: Path) -> None:
    config = ContextGuardConfig(spillover_ttl_seconds=10)
    spillover_dir = tmp_path / config.spillover_dir_name
    spillover_dir.mkdir(parents=True, exist_ok=True)

    # Create fresh file
    fresh_file = spillover_dir / "fresh_payload.md"
    fresh_file.write_text("fresh content")

    # Create expired file
    stale_file = spillover_dir / "stale_payload.md"
    stale_file.write_text("stale content")
    past_time = time.time() - 100
    stale_file.touch()
    import os
    os.utime(stale_file, (past_time, past_time))

    sweeper = EphemeralTransientSweeper(config=config)
    removed = sweeper.sweep_directory(base_dir=tmp_path)

    assert removed == 1
    assert fresh_file.exists()
    assert not stale_file.exists()
