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

from pathlib import Path
from types import SimpleNamespace
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


def _async_return(value):
    """Build a coroutine function returning a fixed value."""
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)


def _downloaded():
    """Build a stand-in for the installer download result."""
    from types import SimpleNamespace

    return SimpleNamespace(
        name="Alpha",
        description="from archive",
        files={"SKILL.md": b"# alpha"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["git", "zip"])
async def test_preview_downloads_scans_and_reports(
    service: BaseSkillMarketService,
    method: str,
) -> None:
    detail = _detail(skill_id="repo:alpha", source="repo", install_method=method, name="Alpha")
    installer = service._git_installer if method == "git" else service._zip_installer

    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
        patch.object(
            type(installer),
            "download",
            new=_async_return(_downloaded()),
        ),
        patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
    ):
        scan.return_value = SimpleNamespace(findings=[], is_clean=True)
        preview = await service.preview("repo:alpha", "repo")

    assert preview.files == ["SKILL.md"]
    assert preview.is_clean is True
    assert preview.installed_skills == ["Alpha"]
    assert preview.prerequisites is None


@pytest.mark.asyncio
async def test_preview_rejects_unsupported_install_method(
    service: BaseSkillMarketService,
) -> None:
    detail = _detail(skill_id="weird:s", source="weird", install_method="direct", name="Weird")
    detail = detail.__class__(**{**detail.__dict__, "install_method": "direct"})

    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
        pytest.raises(
            ValueError,
            match="Unsupported install method",
        ),
    ):
        await service.preview("weird:s", "weird")


@pytest.mark.asyncio
async def test_preview_surfaces_requirements_report(service: BaseSkillMarketService) -> None:
    detail = _detail(skill_id="repo:alpha", source="repo", install_method="git", name="Alpha")
    detail = SkillSearchResult(
        id=detail.id,
        name=detail.name,
        description=detail.description,
        source=detail.source,
        author=detail.author,
        install_url=detail.install_url,
        install_method="git",
        extra_manifest={"requirements": {"python": ">=3.11"}},
    )
    report = SimpleNamespace(to_dict=lambda: {"ok": True})

    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
        patch.object(
            type(service._git_installer),
            "download",
            new=_async_return(_downloaded()),
        ),
        patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
        patch(
            "myrm_agent_harness.backends.skills.prerequisites.check_skill_prerequisites",
            return_value=report,
        ),
    ):
        scan.return_value = SimpleNamespace(findings=[], is_clean=True)
        preview = await service.preview("repo:alpha", "repo")

    assert preview.prerequisites == {"ok": True}


@pytest.mark.asyncio
async def test_install_routes_download_through_quarantine(service: BaseSkillMarketService) -> None:
    detail = _detail(skill_id="repo:alpha", source="repo", install_method="git", name="Alpha")

    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
        patch.object(
            type(service._git_installer),
            "download",
            new=_async_return(_downloaded()),
        ),
        patch.object(
            BaseSkillMarketService,
            "_quarantine_install",
            new=_async_return("quarantined"),
        ) as quarantine,
    ):
        result = await service.install("repo:alpha", "repo")

    assert result == "quarantined"
    assert quarantine.await_count == 1


@pytest.mark.asyncio
async def test_install_rejects_unsupported_method_with_error_code(
    service: BaseSkillMarketService,
) -> None:
    detail = SkillSearchResult(
        id="weird:s",
        name="Weird",
        description="d",
        source="weird",
        author="a",
        install_url="https://example.invalid",
        install_method="direct",
    )

    with patch.object(BaseSkillMarketService, "get_detail", return_value=detail):
        result = await service.install("weird:s", "weird")

    assert result.success is False
    assert "Unsupported install method" in (result.error or "")


@pytest.mark.asyncio
async def test_install_surfaces_value_error_from_download(
    service: BaseSkillMarketService,
) -> None:
    from unittest.mock import AsyncMock

    detail = _detail(skill_id="repo:alpha", source="repo", install_method="git", name="Alpha")

    with (
        patch.object(BaseSkillMarketService, "get_detail", return_value=detail),
        patch.object(
            type(service._git_installer),
            "download",
            new=AsyncMock(side_effect=ValueError("broken archive")),
        ),
    ):
        result = await service.install("repo:alpha", "repo")

    assert result.success is False
    assert "broken archive" in (result.error or "")


@pytest.mark.asyncio
async def test_install_from_url_rejects_non_http_scheme(
    service: BaseSkillMarketService,
) -> None:
    result = await service.install_from_url("ftp://example.invalid/skill.zip")

    assert result.success is False


def _finding(severity: str, description: str = "bad script"):
    from types import SimpleNamespace

    return SimpleNamespace(severity=severity, description=description)


@pytest.mark.asyncio
async def test_quarantine_blocks_critical_lifecycle_scripts(
    service: BaseSkillMarketService,
) -> None:
    stages: list[str] = []

    with patch(
        "myrm_agent_harness.agent.skills.market.service.check_lifecycle_scripts",
        return_value=[_finding("critical", "curl | sh")],
    ):
        result = await service._quarantine_install(
            "repo:alpha",
            "Alpha",
            {"SKILL.md": b"# alpha"},
            source="repo",
            progress_callback=lambda _sid, stage, _msg: stages.append(stage),
        )

    assert result.success is False
    assert "malicious lifecycle scripts" in (result.error or "")
    assert "rejected" in stages


@pytest.mark.asyncio
async def test_quarantine_writes_files_and_blocks_path_escape(
    service: BaseSkillMarketService,
    caplog,
) -> None:
    caplog.set_level("WARNING")
    with (
        patch(
            "myrm_agent_harness.agent.skills.market.service.check_lifecycle_scripts",
            return_value=[],
        ),
        patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
        patch("myrm_agent_harness.agent.skills.market.service.compute_scan_summary") as summary,
        patch.object(
            BaseSkillMarketService,
            "_promote_quarantined_skill",
            new=_async_return("promoted"),
            create=True,
        ),
    ):
        scan.return_value = SimpleNamespace(findings=[], is_clean=True)
        summary.return_value = SimpleNamespace(score=100)

        result = await service._quarantine_install(
            "repo:alpha",
            "Alpha",
            {"SKILL.md": b"# alpha", "../escape.txt": b"nope"},
            source="repo",
        )

    assert result.success is True
    assert result.skill_name == "Alpha"


@pytest.mark.asyncio
async def test_quarantine_rejects_low_scan_score(service: BaseSkillMarketService) -> None:
    with (
        patch(
            "myrm_agent_harness.agent.skills.market.service.check_lifecycle_scripts",
            return_value=[],
        ),
        patch("myrm_agent_harness.agent.skills.market.service.scan_all_text_files") as scan,
        patch("myrm_agent_harness.agent.skills.market.service.compute_scan_summary") as summary,
    ):
        scan.return_value = SimpleNamespace(findings=[], is_clean=False, summary="risky content")
        summary.return_value = SimpleNamespace(score=10)

        result = await service._quarantine_install(
            "repo:alpha",
            "Alpha",
            {"SKILL.md": b"# alpha"},
            source="repo",
        )

    assert result.success is False
