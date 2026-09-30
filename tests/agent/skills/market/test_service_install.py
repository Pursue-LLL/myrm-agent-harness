"""Unit tests for skill market install and uninstall entry points.

[INPUT]
- myrm_agent_harness.agent.skills.market.service::BaseSkillMarketService
- myrm_agent_harness.backends.skills.market_protocols::SkillInstallResult

[OUTPUT]
- pytest suite covering the resolvable and terminal branches of install,
  and the guards that reject uninstall for non-local skills.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_service_install.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.skills.market.service import BaseSkillMarketService
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


def _detail(
    *,
    skill_id: str,
    source: str,
    install_method: str = "git",
    name: str = "Skill",
) -> SkillSearchResult:
    return SkillSearchResult(
        id=skill_id,
        name=name,
        description="d",
        source=source,
        author="a",
        install_url="https://example.invalid",
        install_method=install_method,  # type: ignore[arg-type]
    )


@pytest.fixture
def service() -> BaseSkillMarketService:
    return BaseSkillMarketService()


@pytest.mark.asyncio
async def test_install_reports_progress_through_resolution(
    service: BaseSkillMarketService,
) -> None:
    stages: list[str] = []

    with patch.object(
        BaseSkillMarketService,
        "get_detail",
        return_value=None,
    ):
        result = await service.install(
            "ghost:skill",
            "ghost",
            progress_callback=lambda _sid, stage, _msg: stages.append(stage),
        )

    assert result.success is False
    assert "ghost:skill" in (result.error or "")
    assert stages == ["resolving", "failed"]


@pytest.mark.asyncio
async def test_install_short_circuits_prebuilt_direct_skill(
    service: BaseSkillMarketService,
) -> None:
    stages: list[str] = []
    detail = _detail(skill_id="prebuilt:s", source="prebuilt", install_method="direct")

    with patch.object(BaseSkillMarketService, "get_detail", return_value=detail):
        result = await service.install(
            "prebuilt:s",
            "prebuilt",
            progress_callback=lambda _sid, stage, _msg: stages.append(stage),
        )

    assert result.success is True
    assert result.installed_path == "prebuilt (already installed)"
    assert stages == ["resolving", "completed"]


@pytest.mark.asyncio
async def test_uninstall_rejects_non_local_skill(service: BaseSkillMarketService) -> None:
    result = await service.uninstall("github:some-skill")

    assert result.success is False
    assert "local" in (result.error or "").lower()
    assert "github:some-skill" in (result.error or "")


@pytest.mark.asyncio
async def test_uninstall_reports_missing_directory(
    service: BaseSkillMarketService,
    tmp_path,
) -> None:
    from pathlib import Path

    with (
        patch(
            "myrm_agent_harness.agent.skills.market.service.resolve_local_install_dir",
            return_value=None,
        ),
        patch("myrm_agent_harness.agent.skills.market.service.LOCAL_INSTALL_DIR", Path(tmp_path)),
    ):
        result = await service.uninstall("local::absent")

    assert result.success is False
    assert "not found" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_uninstall_removes_local_skill_directory(
    service: BaseSkillMarketService,
    tmp_path,
) -> None:
    from pathlib import Path

    target = Path(tmp_path) / "alpha"
    target.mkdir()
    (target / "SKILL.md").write_text("# alpha", encoding="utf-8")

    with (
        patch(
            "myrm_agent_harness.agent.skills.market.service.resolve_local_install_dir",
            return_value=target,
        ),
        patch("myrm_agent_harness.agent.skills.market.service.LOCAL_INSTALL_DIR", Path(tmp_path)),
    ):
        result = await service.uninstall("local::alpha")

    assert result.success is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_search_aggregates_sources_and_caches(
    service: BaseSkillMarketService,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    first = MagicMock()
    first.source_name = "alpha"
    first.search = AsyncMock(return_value=[_detail(skill_id="alpha:one", source="alpha", name="Alpha")])
    second = MagicMock()
    second.source_name = "beta"
    second.search = AsyncMock(return_value=[_detail(skill_id="beta:one", source="beta", name="Beta")])
    # Isolate from the built-in network-backed sources.
    service._sources = [first, second]

    results = await service.search("widget")

    assert {r.result.source for r in results} == {"alpha", "beta"}
    first.search.assert_awaited()


@pytest.mark.asyncio
async def test_search_browse_returns_empty_without_query(service: BaseSkillMarketService) -> None:
    assert await service.search("") == []


@pytest.mark.asyncio
async def test_search_serves_second_call_from_cache(service: BaseSkillMarketService) -> None:
    from unittest.mock import AsyncMock, MagicMock

    source = MagicMock()
    source.source_name = "alpha"
    source.search = AsyncMock(return_value=[_detail(skill_id="alpha:one", source="alpha", name="Alpha")])
    service._sources = [source]

    await service.search("cached-query")
    await service.search("cached-query")

    assert source.search.await_count == 1


@pytest.mark.asyncio
async def test_preview_rejects_unknown_skill(service: BaseSkillMarketService) -> None:
    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=None),
        pytest.raises(
            ValueError,
            match="Skill not found",
        ),
    ):
        await service.preview("ghost:skill", "ghost")


@pytest.mark.asyncio
async def test_preview_returns_prebuilt_without_download(service: BaseSkillMarketService) -> None:
    detail = _detail(skill_id="prebuilt:s", source="prebuilt", install_method="direct")

    with patch.object(BaseSkillMarketService, "get_detail", return_value=detail):
        preview = await service.preview("prebuilt:s", "prebuilt")

    assert preview.skill_id == "prebuilt:s"
    assert preview.is_clean is True
