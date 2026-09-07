"""Unit tests for GitHub Tap subscriptions and directory sync engine.

[INPUT]
- myrm_agent_harness.agent.skills.market.taps
- myrm_agent_harness.agent.skills.market.sources.github

[OUTPUT]
- pytest suite covering TapSubscription parsing, Git Trees recursive scanning,
  and GitHubSkillSource extra_taps aggregation.

[POS]
myrm-agent-harness/tests/agent/skills/market/test_taps.py
"""

from unittest.mock import AsyncMock, patch
import pytest

from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource
from myrm_agent_harness.agent.skills.market.taps import (
    GitHubTapSource,
    TapDirectoryScanner,
    TapSubscription,
)


def test_tap_subscription_canonical_name() -> None:
    tap1 = TapSubscription(repo="owner/repo", path="skills/")
    assert tap1.get_canonical_name() == "owner/repo"

    tap2 = TapSubscription(repo="https://github.com/myorg/awesome-skills.git", path="custom/")
    assert tap2.get_canonical_name() == "myorg/awesome-skills"


@pytest.mark.asyncio
async def test_tap_directory_scanner_success() -> None:
    tap = TapSubscription(repo="myorg/skills-repo", path="skills/")
    scanner = TapDirectoryScanner(tap)

    mock_tree_payload = {
        "sha": "abcdef123456",
        "tree": [
            {"path": "README.md", "type": "blob"},
            {"path": "skills/pdf-parser/SKILL.md", "type": "blob"},
            {"path": "skills/data-analysis/SKILL.md", "type": "blob"},
            {"path": "other/ignored/SKILL.md", "type": "blob"},
        ],
    }

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_tree_payload

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        skills = await scanner.scan_skills(force_refresh=True)
        assert len(skills) == 2
        skill_ids = {s.id for s in skills}
        assert "myorg/skills-repo/skills/pdf-parser" in skill_ids
        assert "myorg/skills-repo/skills/data-analysis" in skill_ids
        assert all(s.source == "github-tap" for s in skills)


@pytest.mark.asyncio
async def test_github_tap_source_search() -> None:
    tap = TapSubscription(repo="myorg/skills-repo", path="skills/")
    tap_source = GitHubTapSource([tap])

    mock_tree_payload = {
        "sha": "123456",
        "tree": [
            {"path": "skills/ocr-tool/SKILL.md", "type": "blob"},
            {"path": "skills/web-scraper/SKILL.md", "type": "blob"},
        ],
    }

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_tree_payload

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        results = await tap_source.search("ocr", limit=10)
        assert len(results) == 1
        assert results[0].name == "ocr-tool"


@pytest.mark.asyncio
async def test_github_skill_source_with_extra_taps() -> None:
    tap = TapSubscription(repo="myorg/skills-repo", path="skills/")
    gh_source = GitHubSkillSource(token=None, extra_taps=[tap])

    mock_tree_payload = {
        "sha": "123456",
        "tree": [
            {"path": "skills/unique-tap-skill/SKILL.md", "type": "blob"},
        ],
    }

    mock_resp_tree = AsyncMock()
    mock_resp_tree.status_code = 200
    mock_resp_tree.json.return_value = mock_tree_payload

    mock_resp_search = AsyncMock()
    mock_resp_search.status_code = 200
    mock_resp_search.json.return_value = {"items": []}

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as mock_tap_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp_tree
        mock_client.__aenter__.return_value = mock_client
        mock_tap_client_cls.return_value = mock_client

        with patch("myrm_agent_harness.agent.skills.market.sources.github.create_httpx_client") as mock_gh_client_cls:
            mock_gh_client = AsyncMock()
            mock_gh_client.get.return_value = mock_resp_search
            mock_gh_client.__aenter__.return_value = mock_gh_client
            mock_gh_client_cls.return_value = mock_gh_client

            results = await gh_source.search("unique", limit=10)
            assert len(results) == 1
            assert results[0].name == "unique-tap-skill"
            assert results[0].source == "github-tap"
