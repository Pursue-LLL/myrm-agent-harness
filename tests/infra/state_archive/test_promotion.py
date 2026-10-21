"""Promotion journal: swap, rollback on failure, and crash recovery."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from myrm_agent_harness.infra.state_archive import (
    PromotionPhase,
    PromotionPlan,
    promote,
    recover_interrupted,
)
from myrm_agent_harness.infra.state_archive import promotion as promotion_module


def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _read(root: Path, rel: str) -> str | None:
    target = root / rel
    return target.read_text(encoding="utf-8") if target.is_file() else None


def _plan(tmp_path: Path, entries: tuple[str, ...]) -> PromotionPlan:
    return PromotionPlan(
        live_root=tmp_path / "live",
        staging_root=tmp_path / "live" / ".staging",
        aside_root=tmp_path / "live" / ".aside",
        journal_path=tmp_path / "live" / ".journal.json",
        entries=entries,
    )


@pytest.fixture
def scenario(tmp_path: Path) -> PromotionPlan:
    _tree(
        tmp_path / "live",
        {
            "data.db": "old-db",
            "data.db-wal": "old-wal",
            "wiki/a.md": "old-wiki",
            "live_only/x.txt": "stale",
            "keep.txt": "untouched",
        },
    )
    _tree(
        tmp_path / "live" / ".staging",
        {"data.db": "new-db", "wiki/a.md": "new-wiki", "fresh/y.txt": "brand-new"},
    )
    return _plan(tmp_path, ("data.db", "data.db-wal", "data.db-shm", "wiki", "live_only", "fresh"))


def test_commit_swaps_entries_and_keeps_previous_state_aside(scenario: PromotionPlan) -> None:
    journal = promote(scenario)

    assert journal.phase is PromotionPhase.COMMITTED
    live = scenario.live_root
    assert _read(live, "data.db") == "new-db"
    assert _read(live, "data.db-wal") is None, "stale WAL must never sit next to a promoted database"
    assert _read(live, "wiki/a.md") == "new-wiki"
    assert _read(live, "fresh/y.txt") == "brand-new"
    assert not (live / "live_only").exists(), "data entries absent from the archive are replaced, not merged"
    assert _read(live, "keep.txt") == "untouched"
    aside = scenario.aside_root
    assert _read(aside, "data.db") == "old-db"
    assert _read(aside, "data.db-wal") == "old-wal"
    assert _read(aside, "live_only/x.txt") == "stale"


def _fail_on_nth_replace(monkeypatch: pytest.MonkeyPatch, n: int, exc: BaseException) -> None:
    real: Callable[..., None] = os.replace
    calls = {"count": 0}

    def flaky(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls["count"] += 1
        if calls["count"] == n:
            raise exc
        real(src, dst)

    monkeypatch.setattr(promotion_module.os, "replace", flaky)


def test_filesystem_failure_rolls_everything_back(scenario: PromotionPlan, monkeypatch: pytest.MonkeyPatch) -> None:
    _fail_on_nth_replace(monkeypatch, 5, OSError("disk says no"))

    journal = promote(scenario)

    assert journal.phase is PromotionPhase.ROLLED_BACK
    assert journal.error == "disk says no"
    live = scenario.live_root
    assert _read(live, "data.db") == "old-db"
    assert _read(live, "data.db-wal") == "old-wal"
    assert _read(live, "wiki/a.md") == "old-wiki"
    assert _read(live, "live_only/x.txt") == "stale"
    assert not (live / "fresh").exists()
    assert _read(scenario.staging_root, "data.db") == "new-db", "staged copy must survive for a retry"
    assert _read(scenario.staging_root, "fresh/y.txt") == "brand-new"


# os.replace call #1 persists the journal, #2-#8 are the seven moves, #9 persists the commit.
@pytest.mark.parametrize("crash_at", range(2, 10))
def test_crash_at_any_move_is_recovered_on_next_boot(
    scenario: PromotionPlan, monkeypatch: pytest.MonkeyPatch, crash_at: int
) -> None:
    _fail_on_nth_replace(monkeypatch, crash_at, SystemExit("power loss"))
    with pytest.raises(SystemExit):
        promote(scenario)
    monkeypatch.undo()

    recovered = recover_interrupted(scenario.journal_path)

    assert recovered is not None
    assert recovered.phase is PromotionPhase.ROLLED_BACK
    live = scenario.live_root
    assert _read(live, "data.db") == "old-db"
    assert _read(live, "data.db-wal") == "old-wal"
    assert _read(live, "wiki/a.md") == "old-wiki"
    assert _read(live, "live_only/x.txt") == "stale"
    assert not (live / "fresh").exists()
    assert recover_interrupted(scenario.journal_path) is None, "recovery must be idempotent"


def test_crash_before_the_journal_exists_changes_nothing(
    scenario: PromotionPlan, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_on_nth_replace(monkeypatch, 1, SystemExit("power loss"))
    with pytest.raises(SystemExit):
        promote(scenario)
    monkeypatch.undo()

    assert recover_interrupted(scenario.journal_path) is None
    assert _read(scenario.live_root, "data.db") == "old-db"
    assert _read(scenario.staging_root, "data.db") == "new-db"


def test_recover_ignores_missing_or_committed_journal(scenario: PromotionPlan) -> None:
    assert recover_interrupted(scenario.journal_path) is None
    promote(scenario)
    assert recover_interrupted(scenario.journal_path) is None


def test_non_top_level_entry_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="top-level"):
        promote(_plan(tmp_path, ("a/b",)))
