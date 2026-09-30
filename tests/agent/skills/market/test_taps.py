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

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource
from myrm_agent_harness.agent.skills.market.taps import (
    GitHubTapSource,
    TapDirectoryScanner,
    TapSubscription,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


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

    mock_resp = MagicMock()
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

    mock_resp = MagicMock()
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

    mock_resp_tree = MagicMock()
    mock_resp_tree.status_code = 200
    mock_resp_tree.json.return_value = mock_tree_payload

    mock_resp_search = MagicMock()
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


def test_github_skill_source_accepts_tap_mapping() -> None:
    """A tap given as a plain mapping is normalised into a TapSubscription."""
    source = GitHubSkillSource(
        token=None,
        extra_taps=[{"repo": "myorg/skills-repo", "path": "skills/"}],
    )
    taps = source._tap_source._taps
    assert set(taps) == {"myorg/skills-repo"}


def test_github_skill_source_without_taps_has_no_tap_source() -> None:
    source = GitHubSkillSource(token=None)
    assert source._tap_source is None


@pytest.mark.asyncio
async def test_scan_skills_degrades_on_httpx_error() -> None:
    """Network failures keep the cached-result fallback rather than raising."""
    scanner = TapDirectoryScanner(TapSubscription(repo="myorg/skills-repo"))
    boom = httpx.ConnectError("network down")

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as client_cls:
        client = AsyncMock()
        client.get.side_effect = boom
        client.__aenter__.return_value = client
        client_cls.return_value = client

        assert await scanner.scan_skills(force_refresh=True) == []


@pytest.mark.asyncio
async def test_scan_skills_degrades_on_contract_error() -> None:
    """A malformed payload is a data error, so it degrades instead of raising."""
    scanner = TapDirectoryScanner(TapSubscription(repo="myorg/skills-repo"))

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"tree": [{"path": "skills/a/SKILL.md", "type": "blob"}], "sha": "s"}

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as client_cls:
        client = AsyncMock()
        client.get.return_value = resp
        client.__aenter__.return_value = client
        client_cls.return_value = client

        # Constructing a result from a malformed item raises TypeError.
        resp.json.return_value = {
            "tree": [{"path": "skills/a/SKILL.md", "type": "blob"}],
            "sha": "s",
        }

        with patch(
            "myrm_agent_harness.agent.skills.market.taps.SkillSearchResult",
            side_effect=TypeError("bad payload"),
        ):
            assert await scanner.scan_skills(force_refresh=True) == []


@pytest.mark.asyncio
async def test_scan_skills_propagates_unexpected_error() -> None:
    """Programming errors are not disguised as an empty catalog."""
    scanner = TapDirectoryScanner(TapSubscription(repo="myorg/skills-repo"))

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"tree": [{"path": "skills/a/SKILL.md", "type": "blob"}], "sha": "s"}

    with patch("myrm_agent_harness.agent.skills.market.taps.create_httpx_client") as client_cls:
        client = AsyncMock()
        client.get.return_value = resp
        client.__aenter__.return_value = client
        client_cls.return_value = client

        # An unexpected error class must surface instead of faking an empty catalog.
        resp.json.return_value = {
            "tree": [{"path": "skills/a/SKILL.md", "type": "blob"}],
            "sha": "s",
        }

        with (
            patch(
                "myrm_agent_harness.agent.skills.market.taps.SkillSearchResult",
                side_effect=RuntimeError("genuine bug"),
            ),
            pytest.raises(RuntimeError, match="genuine bug"),
        ):
            await scanner.scan_skills(force_refresh=True)


class TestTapSubscriptionHelpers:
    def test_canonical_name_strips_url_and_suffix(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapSubscription

        assert TapSubscription(repo="https://github.com/acme/taps.git").get_canonical_name() == "acme/taps"

    def test_to_dict_masks_auth_token(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapSubscription

        data = TapSubscription(repo="acme/taps", auth_token="secret-token").to_dict()
        assert data["auth_token"] == "***"
        assert "secret-token" not in str(data)

    def test_to_dict_omits_absent_auth_token(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapSubscription

        assert TapSubscription(repo="acme/taps").to_dict()["auth_token"] is None


class TestTapDirectoryScannerBranches:
    def test_bearer_auth_header(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        scanner = TapDirectoryScanner(TapSubscription(repo="acme/taps", auth_token="tk"))
        assert scanner._build_headers()["Authorization"] == "Bearer tk"

    def test_no_auth_header_without_token(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        scanner = TapDirectoryScanner(TapSubscription(repo="acme/taps"))
        assert "Authorization" not in scanner._build_headers()

    @pytest.mark.asyncio
    async def test_rejects_malformed_repo_name(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        assert await TapDirectoryScanner(TapSubscription(repo="noslash")).scan_skills() == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_non_200_returns_cached_skills(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        scanner = TapDirectoryScanner(TapSubscription(repo="acme/taps"))
        cached = scanner._cache.skills
        respx.get(url__startswith="https://api.github.com/repos/acme/taps/git/trees/").mock(
            return_value=httpx.Response(500)
        )
        assert await scanner.scan_skills() == cached

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_master_branch(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        respx.get("https://api.github.com/repos/acme/taps/git/trees/main").mock(return_value=httpx.Response(404))
        master = respx.get("https://api.github.com/repos/acme/taps/git/trees/master").mock(
            return_value=httpx.Response(
                200,
                json={"sha": "abc123", "tree": [{"path": "skills/pdf/SKILL.md", "type": "blob"}]},
            )
        )
        results = await TapDirectoryScanner(TapSubscription(repo="acme/taps")).scan_skills()

        assert master.called
        assert [r.id for r in results] == ["acme/taps/skills/pdf"]
        assert results[0].source == "github-tap"
        assert results[0].extra_manifest["tap_repo"] == "acme/taps"

    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_by_path_prefix_and_skill_yaml(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        respx.get(url__startswith="https://api.github.com/repos/acme/taps/git/trees/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sha": "s",
                    "tree": [
                        {"path": "other/nope/SKILL.md"},
                        {"path": "docs/readme.md"},
                        {"path": "skills/img/skill.yaml"},
                    ],
                },
            )
        )
        results = await TapDirectoryScanner(TapSubscription(repo="acme/taps")).scan_skills()
        assert [r.name for r in results] == ["img"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_second_scan_uses_cache(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        route = respx.get(url__startswith="https://api.github.com/repos/acme/taps/git/trees/").mock(
            return_value=httpx.Response(200, json={"sha": "s", "tree": []})
        )
        scanner = TapDirectoryScanner(TapSubscription(repo="acme/taps"))
        await scanner.scan_skills()
        await scanner.scan_skills()

        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_force_refresh_bypasses_cache(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import TapDirectoryScanner, TapSubscription

        route = respx.get(url__startswith="https://api.github.com/repos/acme/taps/git/trees/").mock(
            return_value=httpx.Response(200, json={"sha": "s", "tree": []})
        )
        scanner = TapDirectoryScanner(TapSubscription(repo="acme/taps"))
        await scanner.scan_skills()
        await scanner.scan_skills(force_refresh=True)

        assert route.call_count == 2


class TestGitHubTapSourceRegistry:
    def test_register_list_and_remove(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import GitHubTapSource, TapSubscription

        source = GitHubTapSource()
        source.register_tap(TapSubscription(repo="acme/taps"))
        source.register_tap(TapSubscription(repo="https://github.com/other/ones.git"))

        assert len(source.list_taps()) == 2
        assert source.remove_tap("acme/taps") is True
        assert source.remove_tap("acme/taps") is False
        assert len(source.list_taps()) == 1

    def test_register_twice_replaces(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import GitHubTapSource, TapSubscription

        source = GitHubTapSource()
        source.register_tap(TapSubscription(repo="acme/taps", branch="main"))
        source.register_tap(TapSubscription(repo="acme/taps", branch="dev"))

        assert len(source.list_taps()) == 1
        assert source.list_taps()[0].branch == "dev"

    def test_source_name(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import GitHubTapSource

        assert GitHubTapSource().source_name == "github-tap"

    @pytest.mark.asyncio
    async def test_search_matches_name_description_and_id(self) -> None:
        from myrm_agent_harness.agent.skills.market.taps import GitHubTapSource, TapSubscription

        source = GitHubTapSource()
        source.register_tap(TapSubscription(repo="acme/taps"))

        results = [
            SkillSearchResult(
                id="acme/taps/skills/pdf",
                name="pdf",
                description="extract text",
                source="github-tap",
                author="acme",
                install_url="https://github.com/acme/taps",
                install_method="git",
            ),
            SkillSearchResult(
                id="acme/taps/skills/img",
                name="img",
                description="resize pictures",
                source="github-tap",
                author="acme",
                install_url="https://github.com/acme/taps",
                install_method="git",
            ),
        ]
        with respx.mock:
            respx.get(url__startswith="https://api.github.com/repos/acme/taps/git/trees/").mock(
                return_value=httpx.Response(200, json={"sha": "s", "tree": []})
            )
            source._taps["acme/taps"]._cache.skills = results
            source._taps["acme/taps"]._cache.cached_at = time.monotonic()

            assert [r.name for r in await source.search("pdf")] == ["pdf"]
            assert [r.name for r in await source.search("text")] == ["pdf"]
            assert [r.name for r in await source.search("acme/taps/skills/img")] == ["img"]
            assert len(await source.search("   ")) == 2
            assert await source.search("nomatch") == []
