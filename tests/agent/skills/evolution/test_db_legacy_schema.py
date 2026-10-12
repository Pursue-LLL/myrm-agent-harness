"""SkillStore on a database whose skills table still carries a ``traps`` column."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

_LEGACY_ID = "legacy-1"


def _record(skill_id: str, name: str, description: str) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        description=description,
        content="# body",
        path=f"skills/{name}/SKILL.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, parent_id=None),
    )


def _skills_columns(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(skills)")}


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    """A database file whose skills table has the extra column and one row that fills it."""
    db_path = tmp_path / "legacy_skills.db"
    SkillStore(db_path=db_path).close()
    now = datetime.now().isoformat()
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("ALTER TABLE skills ADD COLUMN traps TEXT NOT NULL DEFAULT '[]'")
        conn.execute(
            "INSERT INTO skills (skill_id, name, description, content, evolution_type, "
            "lineage_created_at, created_at, updated_at, traps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _LEGACY_ID,
                "legacy-skill",
                "Handles legacy data",
                "# legacy",
                EvolutionType.CAPTURED.value,
                now,
                now,
                now,
                '[{"description": "old trap"}]',
            ),
        )
        conn.commit()
    return db_path


def test_fresh_database_has_no_traps_column(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh_skills.db"
    SkillStore(db_path=db_path).close()
    assert "traps" not in _skills_columns(db_path)


def test_legacy_row_is_readable(legacy_db: Path) -> None:
    store = SkillStore(db_path=legacy_db)
    try:
        record = store.get_skill(_LEGACY_ID)
        assert record is not None
        assert record.name == "legacy-skill"
        assert [r.skill_id for r in store.get_active_skills()] == [_LEGACY_ID]
    finally:
        store.close()


def test_open_keeps_the_extra_column(legacy_db: Path) -> None:
    SkillStore(db_path=legacy_db).close()
    assert "traps" in _skills_columns(legacy_db)


@pytest.mark.asyncio
async def test_save_overwrites_legacy_row_and_inserts_new_rows(legacy_db: Path) -> None:
    store = SkillStore(db_path=legacy_db)
    try:
        await store.save_skill(_record("new-1", "new-skill", "Fresh"))
        await store.save_skill(_record(_LEGACY_ID, "legacy-skill", "Rewritten"))
        await store.save_skills_batch([_record("batch-1", "batch-skill", "Batch")])

        rewritten = store.get_skill(_LEGACY_ID)
        assert rewritten is not None
        assert rewritten.description == "Rewritten"
        assert {r.skill_id for r in store.get_active_skills()} == {_LEGACY_ID, "new-1", "batch-1"}
    finally:
        store.close()


def test_search_matches_name_and_description_only(legacy_db: Path) -> None:
    store = SkillStore(db_path=legacy_db)
    try:
        assert [r.skill_id for r in store._search_skills_sync("legacy")] == [_LEGACY_ID]
        assert store._search_skills_sync("old trap") == []
    finally:
        store.close()
