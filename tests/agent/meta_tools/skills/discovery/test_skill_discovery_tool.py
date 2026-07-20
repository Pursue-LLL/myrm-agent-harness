"""Unit tests for skill_discovery_tool marketplace actions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.skills.discovery.skill_discovery_tool import (
    create_skill_discovery_tool,
)
from myrm_agent_harness.backends.skills.discovery_protocols import (
    SkillInstallResult,
    SkillSearchResult,
)

_DISCOVER_CAPABILITY_TOOL = "discover_capability_tool"


def _user_config(user_id: str = "test_user") -> dict:
    return {"configurable": {"context": {"user_id": user_id}}}


@pytest.fixture
def discovery_backend() -> MagicMock:
    backend = MagicMock()
    backend.search = AsyncMock(return_value=[])
    backend.install = AsyncMock(
        return_value=SkillInstallResult(success=True, skill_name="demo_skill", skill_id="demo", installed_path="/tmp/demo")
    )
    return backend


@pytest.fixture
def marketplace_tool(discovery_backend: MagicMock):
    install_from_url = AsyncMock(
        return_value=SkillInstallResult(
            success=True,
            skill_name="url_skill",
            skill_id="url-skill",
            installed_path="/tmp/url",
            scan_summary="clean",
        )
    )
    uninstall = AsyncMock(
        return_value=SkillInstallResult(success=True, skill_name="demo_skill", skill_id="demo")
    )
    return create_skill_discovery_tool(
        discovery_backend,
        install_from_url_fn=install_from_url,
        uninstall_fn=uninstall,
    )


@pytest.mark.asyncio
async def test_description_points_to_discover_capability_tool(marketplace_tool) -> None:
    description = marketplace_tool.description
    assert _DISCOVER_CAPABILITY_TOOL in description
    assert "already bound" in description.lower() or "bound to this agent" in description.lower()


@pytest.mark.asyncio
async def test_search_requires_query(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke({"action": "search", "query": "  "})
    assert "query' is required" in result


@pytest.mark.asyncio
async def test_search_no_results(marketplace_tool, discovery_backend: MagicMock) -> None:
    result = await marketplace_tool.ainvoke({"action": "search", "query": "nonexistent"})
    assert "No skills found" in result
    discovery_backend.search.assert_awaited_once_with("nonexistent", limit=8)


@pytest.mark.asyncio
async def test_search_formats_results(marketplace_tool, discovery_backend: MagicMock) -> None:
    discovery_backend.search.return_value = [
        SkillSearchResult(
            id="gh-1",
            name="rss-monitor",
            description="Monitor RSS feeds",
            source="github",
            author="alice",
            install_url="https://example.com",
            install_method="git",
            stars=42,
        )
    ]
    result = await marketplace_tool.ainvoke({"action": "search", "query": "rss"})
    assert "Found 1 skill(s)" in result
    assert "rss-monitor" in result
    assert "GitHub" in result
    assert "(42 stars)" in result
    assert 'skill_id="gh-1"' in result


@pytest.mark.asyncio
async def test_install_requires_ids(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "install", "skill_id": "", "source": ""},
        config=_user_config(),
    )
    assert "skill_id' and 'source' are required" in result


@pytest.mark.asyncio
async def test_install_success(marketplace_tool, discovery_backend: MagicMock) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "install", "skill_id": "demo", "source": "github"},
        config=_user_config(),
    )
    assert "Successfully installed skill 'demo_skill'" in result
    discovery_backend.install.assert_awaited_once_with("demo", "github", "test_user")


@pytest.mark.asyncio
async def test_install_failure(discovery_backend: MagicMock) -> None:
    discovery_backend.install.return_value = SkillInstallResult(success=False, error="network down")
    tool = create_skill_discovery_tool(discovery_backend)
    result = await tool.ainvoke(
        {"action": "install", "skill_id": "demo", "source": "github"},
        config=_user_config(),
    )
    assert "Installation failed: network down" in result


@pytest.mark.asyncio
async def test_install_from_url_requires_url(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "install_from_url", "url": ""},
        config=_user_config(),
    )
    assert "url' is required" in result


@pytest.mark.asyncio
async def test_install_from_url_without_backend_fn(discovery_backend: MagicMock) -> None:
    tool = create_skill_discovery_tool(discovery_backend)
    result = await tool.ainvoke(
        {"action": "install_from_url", "url": "https://github.com/o/r"},
        config=_user_config(),
    )
    assert "Direct URL installation is not supported" in result


@pytest.mark.asyncio
async def test_install_from_url_success(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "install_from_url", "url": "https://github.com/o/r"},
        config=_user_config(),
    )
    assert "Successfully installed skill 'url_skill' from URL" in result
    assert "Security scan: clean" in result


@pytest.mark.asyncio
async def test_uninstall_requires_skill_id(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "uninstall", "skill_id": ""},
        config=_user_config(),
    )
    assert "skill_id' is required" in result


@pytest.mark.asyncio
async def test_uninstall_without_backend_fn(discovery_backend: MagicMock) -> None:
    tool = create_skill_discovery_tool(discovery_backend)
    result = await tool.ainvoke(
        {"action": "uninstall", "skill_id": "demo"},
        config=_user_config(),
    )
    assert "Uninstall is not supported" in result


@pytest.mark.asyncio
async def test_uninstall_success(marketplace_tool) -> None:
    result = await marketplace_tool.ainvoke(
        {"action": "uninstall", "skill_id": "demo"},
        config=_user_config(),
    )
    assert "Successfully uninstalled skill 'demo_skill'" in result


@pytest.mark.asyncio
async def test_install_requires_user_id_in_config(discovery_backend: MagicMock) -> None:
    tool = create_skill_discovery_tool(discovery_backend)
    with pytest.raises(ValueError, match="user_id is required"):
        await tool.ainvoke(
            {"action": "install", "skill_id": "demo", "source": "github"},
            config={"configurable": {"context": {}}},
        )


@pytest.mark.asyncio
async def test_install_includes_scan_summary(discovery_backend: MagicMock) -> None:
    discovery_backend.install.return_value = SkillInstallResult(
        success=True,
        skill_name="demo_skill",
        skill_id="demo",
        installed_path="/tmp/demo",
        scan_summary="1 warning",
    )
    tool = create_skill_discovery_tool(discovery_backend)
    result = await tool.ainvoke(
        {"action": "install", "skill_id": "demo", "source": "github"},
        config=_user_config(),
    )
    assert "Security scan: 1 warning" in result


@pytest.mark.asyncio
async def test_install_from_url_failure(discovery_backend: MagicMock) -> None:
    install_from_url = AsyncMock(return_value=SkillInstallResult(success=False, error="bad zip"))
    tool = create_skill_discovery_tool(discovery_backend, install_from_url_fn=install_from_url)
    result = await tool.ainvoke(
        {"action": "install_from_url", "url": "https://github.com/o/r"},
        config=_user_config(),
    )
    assert "Installation from URL failed: bad zip" in result


@pytest.mark.asyncio
async def test_uninstall_failure(discovery_backend: MagicMock) -> None:
    uninstall = AsyncMock(return_value=SkillInstallResult(success=False, error="not found"))
    tool = create_skill_discovery_tool(discovery_backend, uninstall_fn=uninstall)
    result = await tool.ainvoke(
        {"action": "uninstall", "skill_id": "demo"},
        config=_user_config(),
    )
    assert "Uninstall failed: not found" in result
