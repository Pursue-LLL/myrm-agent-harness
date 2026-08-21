"""Integration & unit tests for skill quarantine installation version guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.market import service as market_service_module
from myrm_agent_harness.agent.skills.market.helpers import read_origin, write_origin
from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService


@pytest.fixture
def isolated_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(market_service_module, "LOCAL_INSTALL_DIR", skills_dir)
    return skills_dir


@pytest.mark.asyncio
async def test_quarantine_install_first_time(isolated_skills_dir: Path) -> None:
    svc = BaseSkillMarketService()
    files = {
        "SKILL.md": b"---\nname: demo-skill\ndescription: Demo skill description\nversion: 1.0.0\n---\n# Demo\n",
    }
    res = await svc._quarantine_install(
        "local::demo-skill", "demo-skill", files, source="test"
    )
    assert res.success is True
    target = isolated_skills_dir / "demo-skill"
    assert target.is_dir()
    origin = read_origin(target)
    assert origin.get("version") == "1.0.0"


@pytest.mark.asyncio
async def test_quarantine_install_upgrade(isolated_skills_dir: Path) -> None:
    svc = BaseSkillMarketService()
    target = isolated_skills_dir / "demo-skill"
    target.mkdir(parents=True, exist_ok=True)
    write_origin(target, source="test", skill_id="local::demo-skill", version="1.0.0")
    (target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill description\nversion: 1.0.0\n---\n", encoding="utf-8"
    )

    files = {
        "SKILL.md": b"---\nname: demo-skill\ndescription: Demo skill description\nversion: 1.1.0\n---\n# Demo v1.1\n",
    }
    res = await svc._quarantine_install(
        "local::demo-skill", "demo-skill", files, source="test"
    )
    assert res.success is True
    origin = read_origin(target)
    assert origin.get("version") == "1.1.0"


@pytest.mark.asyncio
async def test_quarantine_install_downgrade_blocked(isolated_skills_dir: Path) -> None:
    svc = BaseSkillMarketService()
    target = isolated_skills_dir / "demo-skill"
    target.mkdir(parents=True, exist_ok=True)
    write_origin(target, source="test", skill_id="local::demo-skill", version="2.0.0")
    (target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill description\nversion: 2.0.0\n---\n", encoding="utf-8"
    )

    files = {
        "SKILL.md": b"---\nname: demo-skill\ndescription: Demo skill description\nversion: 1.0.0\n---\n# Demo v1.0\n",
    }
    res = await svc._quarantine_install(
        "local::demo-skill", "demo-skill", files, source="test", allow_downgrade=False
    )
    assert res.success is False
    assert res.error_code == "DOWNGRADE_BLOCKED"
    assert "downgrade blocked" in res.error

    # Ensure existing version was NOT overwritten
    origin = read_origin(target)
    assert origin.get("version") == "2.0.0"


@pytest.mark.asyncio
async def test_quarantine_install_downgrade_forced(isolated_skills_dir: Path) -> None:
    svc = BaseSkillMarketService()
    target = isolated_skills_dir / "demo-skill"
    target.mkdir(parents=True, exist_ok=True)
    write_origin(target, source="test", skill_id="local::demo-skill", version="2.0.0")
    (target / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo skill description\nversion: 2.0.0\n---\n", encoding="utf-8"
    )

    files = {
        "SKILL.md": b"---\nname: demo-skill\ndescription: Demo skill description\nversion: 1.0.0\n---\n# Demo v1.0\n",
    }
    res = await svc._quarantine_install(
        "local::demo-skill", "demo-skill", files, source="test", allow_downgrade=True
    )
    assert res.success is True
    origin = read_origin(target)
    assert origin.get("version") == "1.0.0"
