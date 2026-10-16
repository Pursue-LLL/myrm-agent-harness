"""Unit tests for the ownership rules of the storage ledger (layout resolution)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from myrm_agent_harness.observability.storage_governance import StorageCategory
from myrm_agent_harness.observability.storage_governance.layout import SQLITE_SIDECAR_SUFFIXES, resolve_layout


def test_other_is_reserved_for_the_remainder_of_the_data_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="OTHER"):
        resolve_layout(tmp_path, {StorageCategory.OTHER: (tmp_path / "x",)})


def test_every_declared_category_is_listed_in_declaration_order_with_other_last(tmp_path: Path) -> None:
    declared = {
        StorageCategory.SNAPSHOTS: (tmp_path / "snapshots",),
        StorageCategory.CHECKPOINTS: (),
    }

    layout = resolve_layout(tmp_path, declared)

    assert list(layout.claims) == [StorageCategory.CHECKPOINTS, StorageCategory.SNAPSHOTS, StorageCategory.OTHER]
    assert layout.claims[StorageCategory.CHECKPOINTS] == ()
    assert layout.claims[StorageCategory.OTHER] == (tmp_path.resolve(),)


def test_a_database_file_also_claims_its_journals_but_a_directory_does_not(tmp_path: Path) -> None:
    (tmp_path / "qdrant").mkdir()
    db_file = (tmp_path / "data.db").resolve()

    layout = resolve_layout(
        tmp_path,
        {StorageCategory.SQLITE_DATABASE: (db_file,), StorageCategory.VECTOR_STORE: (tmp_path / "qdrant",)},
    )

    assert layout.claims[StorageCategory.SQLITE_DATABASE] == (
        db_file,
        *(Path(f"{db_file}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES),
    )
    assert layout.claims[StorageCategory.VECTOR_STORE] == ((tmp_path / "qdrant").resolve(),)


def test_an_explicit_declaration_beats_a_journal_claimed_by_a_database(tmp_path: Path) -> None:
    db_file = (tmp_path / "data.db").resolve()
    journal = Path(f"{db_file}-wal")

    layout = resolve_layout(
        tmp_path,
        {StorageCategory.SQLITE_DATABASE: (db_file,), StorageCategory.SQLITE_BACKUPS: (journal,)},
    )

    assert journal in layout.claims[StorageCategory.SQLITE_BACKUPS]
    assert journal not in layout.claims[StorageCategory.SQLITE_DATABASE]


def test_a_path_declared_for_two_categories_goes_to_the_first_and_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()

    with caplog.at_level(logging.WARNING):
        layout = resolve_layout(
            tmp_path,
            {StorageCategory.EVENT_LOGS: (shared,), StorageCategory.MEMORY_ARCHIVE: (shared,)},
        )

    assert layout.claims[StorageCategory.MEMORY_ARCHIVE] == (shared.resolve(),)
    assert layout.claims[StorageCategory.EVENT_LOGS] == ()
    assert "memory_archive" in caplog.text
    assert "event_logs" in caplog.text


def test_a_path_declared_twice_for_one_category_is_one_claim_and_stays_quiet(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()

    with caplog.at_level(logging.WARNING):
        layout = resolve_layout(tmp_path, {StorageCategory.EVENT_LOGS: (shared, tmp_path / "x" / ".." / "shared")})

    assert layout.claims[StorageCategory.EVENT_LOGS] == (shared.resolve(),)
    assert caplog.text == ""


def test_the_data_directory_is_owned_unless_a_category_claims_it(tmp_path: Path) -> None:
    other = resolve_layout(tmp_path, {StorageCategory.CHECKPOINTS: (tmp_path / "c.db",)})
    claimed = resolve_layout(tmp_path, {StorageCategory.MEMORY_ARCHIVE: (tmp_path,)})

    assert other.claims[StorageCategory.OTHER] == (tmp_path.resolve(),)
    assert claimed.claims[StorageCategory.OTHER] == ()
    assert os.path.normcase(tmp_path.resolve()) in other.owned
    assert os.path.normcase(tmp_path.resolve()) in claimed.owned


def test_every_claimed_path_bounds_the_walk_of_the_others(tmp_path: Path) -> None:
    (tmp_path / "harness" / ".memories").mkdir(parents=True)

    layout = resolve_layout(
        tmp_path,
        {
            StorageCategory.WORKSPACES: (tmp_path / "harness",),
            StorageCategory.MEMORY_ARCHIVE: (tmp_path / "harness" / ".memories",),
        },
    )

    root = tmp_path.resolve()
    assert layout.owned == {os.path.normcase(path) for path in (root, root / "harness", root / "harness" / ".memories")}
