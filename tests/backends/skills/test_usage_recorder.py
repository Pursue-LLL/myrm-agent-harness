"""Unit tests for usage_recorder — skill selection stats bridge."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata
from myrm_agent_harness.backends.skills.usage_recorder import (
    flush_skill_usage_stats,
    get_injected_stats_collector,
    record_skill_selection,
    reset_turn_usage_dedupe,
    set_stats_collector,
)


@pytest.fixture(autouse=True)
def _reset_usage_recorder() -> None:
    set_stats_collector(None)
    reset_turn_usage_dedupe()
    yield
    set_stats_collector(None)
    reset_turn_usage_dedupe()


def test_record_skips_when_no_storage_path() -> None:
    skill_meta = SkillMetadata(name="orphan", description="No path")
    record_skill_selection(skill_meta, success=True)
    assert get_injected_stats_collector() is None


def test_record_skips_when_storage_path_not_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("x")
    skill_meta = SkillMetadata(
        name="bad_path",
        description="File not dir",
        storage_path=str(file_path),
    )
    collector = SkillStatsCollector(tmp_path)
    set_stats_collector(collector)
    record_skill_selection(skill_meta, success=True)
    flush_skill_usage_stats()
    assert not (file_path / ".stats.json").exists()


def test_default_collector_when_not_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "lazy_skill"
    skill_dir.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    skill_meta = SkillMetadata(
        name="lazy_skill",
        description="Uses lazy default collector",
        storage_path=str(skill_dir),
    )
    record_skill_selection(skill_meta, success=True)
    flush_skill_usage_stats()
    assert (skill_dir / ".stats.json").exists()


def test_record_swallows_collector_errors(tmp_path: Path) -> None:
    skill_dir = tmp_path / "err_skill"
    skill_dir.mkdir()
    skill_meta = SkillMetadata(
        name="err_skill",
        description="Collector throws",
        storage_path=str(skill_dir),
    )
    broken = MagicMock(spec=SkillStatsCollector)
    broken.record_usage.side_effect = RuntimeError("disk full")
    set_stats_collector(broken)

    record_skill_selection(skill_meta, success=True)
    broken.record_usage.assert_called_once()


def test_flush_noop_when_no_collector() -> None:
    flush_skill_usage_stats()
