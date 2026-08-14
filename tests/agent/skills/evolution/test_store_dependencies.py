"""Tests for persistent skill dependency tracking in SkillStore."""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore


def _record(skill_id: str, name: str, content: str) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        name=name,
        description=f"desc for {name}",
        content=content,
        path=f"skills/{name}.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
    )


@pytest.fixture
def temp_db_path(tmp_path: Path):
    return tmp_path / "deps.db"


@pytest.mark.asyncio
async def test_persist_and_query_dependents(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    base = _record(
        "http-client",
        "http-client",
        "---\nname: http-client\ndescription: http\ndependencies: []\n---\nplain",
    )
    scraper = _record(
        "web-scraper",
        "web-scraper",
        '---\nname: web-scraper\ndescription: scrape\ndependencies:\n  - http-client\n---\n@tool_use("browser_navigate")\n',
    )
    await store.save_skill(base)
    await store.save_skill(scraper)

    assert store.get_dependents("http-client") == ["web-scraper"]
    assert store.get_dependents("web-scraper") == []
    assert store.get_dependents("unknown") == []

    assert store.get_dependents_map(["http-client", "web-scraper", "nope"]) == {
        "http-client": ["web-scraper"],
        "web-scraper": [],
        "nope": [],
    }

    assert store.get_skill_dependencies("web-scraper") == ["http-client"]
    assert store.get_skill_dependencies("http-client") == []

    store.close()


@pytest.mark.asyncio
async def test_dependencies_survive_reopen(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    base = _record("b", "b", "---\nname: b\ndescription: b\n---\nplain")
    a = _record("a", "a", "---\nname: a\ndescription: a\ndependencies: [b]\n---\nplain")
    await store.save_skill(base)
    await store.save_skill(a)
    store.close()

    store = SkillStore(db_path=temp_db_path)
    assert store.get_dependents("b") == ["a"]
    store.close()


@pytest.mark.asyncio
async def test_update_content_rebuilds_edges(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    base = _record("b", "b", "---\nname: b\ndescription: b\n---\nplain")
    a = _record("a", "a", "---\nname: a\ndescription: a\ndependencies: [b]\n---\nplain")
    await store.save_skill(base)
    await store.save_skill(a)
    assert store.get_dependents("b") == ["a"]

    updated_a = _record("a", "a", "---\nname: a\ndescription: a\ndependencies: []\n---\nplain")
    await store.save_skill(updated_a)
    assert store.get_dependents("b") == []
    store.close()


@pytest.mark.asyncio
async def test_delete_skill_removes_edges(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    base = _record("b", "b", "---\nname: b\ndescription: b\n---\nplain")
    a = _record("a", "a", "---\nname: a\ndescription: a\ndependencies: [b]\n---\nplain")
    await store.save_skill(base)
    await store.save_skill(a)
    assert store.get_dependents("b") == ["a"]

    await store.delete_skill("a")
    assert store.get_dependents("b") == []

    await store.delete_skill("b")
    assert store.get_dependents("b") == []
    store.close()


@pytest.mark.asyncio
async def test_unresolved_frontmatter_deps_are_dropped(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    # Depends on a skill that is not in the library: edge must not appear.
    solo = _record("solo", "solo", "---\nname: solo\ndescription: solo\ndependencies: [ghost]\n---\nplain")
    await store.save_skill(solo)
    assert store.get_skill_dependencies("solo") == []
    assert store.get_dependents("ghost") == []
    store.close()


@pytest.mark.asyncio
async def test_edges_use_skill_ids_when_name_differs_from_id(temp_db_path):
    """Impact queries must key by skill_id even when a skill's name differs.

    Regression: edges used to store the resolved *name* while impact queries
    matched on skill_id, so dependents silently disappeared for skills whose
    name differs from their ID (e.g. prefixed ``local::`` IDs).
    """
    store = SkillStore(db_path=temp_db_path)
    base = _record("local::http-client", "http-client", "---\nname: http-client\ndescription: http\n---\nplain")
    scraper = _record(
        "local::web-scraper",
        "web-scraper",
        "---\nname: web-scraper\ndescription: scrape\ndependencies: [http-client]\n---\nplain",
    )
    await store.save_skill(base)
    await store.save_skill(scraper)

    assert store.get_dependents("local::http-client") == ["local::web-scraper"]
    assert store.get_dependents_map(["local::http-client", "nope"]) == {
        "local::http-client": ["local::web-scraper"],
        "nope": [],
    }
    assert store.get_skill_dependencies("local::web-scraper") == ["local::http-client"]
    assert store.get_dependents("http-client") == []
    assert store.get_skill_dependencies("web-scraper") == []
    store.close()


@pytest.mark.asyncio
async def test_closed_flag_reflects_lifecycle(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    assert store.closed is False
    store.close()
    assert store.closed is True
