"""Unit tests for GitHubTapSkillSource."""

import time
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from httpx import Response

from myrm_agent_harness.agent.skills.market.sources.github_tap import GitHubTapSkillSource
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


@pytest.mark.asyncio
async def test_github_tap_source_properties() -> None:
    source = GitHubTapSkillSource("https://github.com/my-org/sec-skills", subdirectory="skills")
    assert source.owner == "my-org"
    assert source.repo == "sec-skills"
    assert source.subdirectory == "skills"
    assert source.source_name == "github-tap:my-org/sec-skills/skills"


@pytest.mark.asyncio
async def test_github_tap_probe_success() -> None:
    source = GitHubTapSkillSource("my-org/sec-skills", subdirectory="skills")

    tree_response = {
        "tree": [
            {"path": "skills/audit/SKILL.md", "type": "blob"},
            {"path": "skills/k8s-fix/SKILL.md", "type": "blob"},
            {"path": "README.md", "type": "blob"},
        ]
    }

    skill_audit_content = """---
name: Audit Skill
description: Security auditing tool
tags: [security, audit]
requirements:
  binaries: [git, curl]
---
# Audit Skill Content
"""

    skill_k8s_content = """---
name: K8s Fix Skill
description: Auto-remediation for kubernetes
tags: [k8s, devops]
---
# K8s Fix Content
"""

    with respx.mock(assert_all_mocked=False) as respx_mock:
        respx_mock.get("https://api.github.com/repos/my-org/sec-skills/git/trees/HEAD?recursive=1").mock(
            return_value=Response(200, json=tree_response)
        )
        respx_mock.get("https://raw.githubusercontent.com/my-org/sec-skills/HEAD/skills/audit/SKILL.md").mock(
            return_value=Response(200, text=skill_audit_content)
        )
        respx_mock.get("https://raw.githubusercontent.com/my-org/sec-skills/HEAD/skills/k8s-fix/SKILL.md").mock(
            return_value=Response(200, text=skill_k8s_content)
        )

        reachable, count = await source.probe()
        assert reachable is True
        assert count == 2

        results = await source.search("Audit")
        assert len(results) == 1
        assert results[0].name == "Audit Skill"
        assert results[0].prerequisites == {"binaries": ["git", "curl"]}


@pytest.mark.asyncio
async def test_github_tap_probe_not_found() -> None:
    source = GitHubTapSkillSource("my-org/non-existent-repo")

    with respx.mock(assert_all_mocked=False) as respx_mock:
        respx_mock.get("https://api.github.com/repos/my-org/non-existent-repo/git/trees/HEAD?recursive=1").mock(
            return_value=Response(404, json={"message": "Not Found"})
        )

        reachable, count = await source.probe()
        assert reachable is False
        assert count == 0


def _tree_response(paths: list[str], sha: str = "s") -> Response:
    return Response(200, json={"sha": sha, "tree": [{"path": p, "type": "blob"} for p in paths]})


class TestHeadersAndSubdirectory:
    def test_token_authorization(self) -> None:
        source = GitHubTapSkillSource("my-org/repo", token="tk")
        assert source._build_headers()["Authorization"] == "token tk"

    def test_without_token_no_authorization(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        assert "Authorization" not in source._build_headers()

    def test_subdirectory_from_url_when_arg_absent(self) -> None:
        source = GitHubTapSkillSource("https://github.com/my-org/repo/tree/main/skills/pdf")
        assert source.subdirectory == "skills/pdf"

    def test_explicit_subdirectory_wins(self) -> None:
        source = GitHubTapSkillSource("https://github.com/my-org/repo/tree/main/skills/pdf", subdirectory="other")
        assert source.subdirectory == "other"

    def test_source_name_without_subdirectory(self) -> None:
        assert GitHubTapSkillSource("my-org/repo").source_name == "github-tap:my-org/repo"


class TestFetchAllSkillsErrors:
    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_repo_raises_value_error(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=Response(404)
        )
        source = GitHubTapSkillSource("my-org/repo")
        with pytest.raises(ValueError, match="not found"):
            await source._fetch_all_skills()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unauthorized_raises_permission_error(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=Response(401)
        )
        source = GitHubTapSkillSource("my-org/repo")
        with pytest.raises(PermissionError):
            await source._fetch_all_skills()

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limited_raises_permission_error(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=Response(403)
        )
        source = GitHubTapSkillSource("my-org/repo")
        with pytest.raises(PermissionError):
            await source._fetch_all_skills()

    @pytest.mark.asyncio
    @respx.mock
    async def test_server_error_surfaces_as_http_status(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=Response(500)
        )
        source = GitHubTapSkillSource("my-org/repo")
        with pytest.raises(httpx.HTTPStatusError):
            await source._fetch_all_skills()


class TestSearchAndDetail:
    @pytest.mark.asyncio
    async def test_blank_query_returns_all(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._cached_skills = [
            SkillSearchResult(
                id="my-org/repo/skills/a",
                name="a",
                description="alpha",
                source="github-tap",
                author="my-org",
                install_url="https://github.com/my-org/repo",
                install_method="git",
            )
        ]
        source._cache_timestamp = time.monotonic()
        assert len(await source.search("  ")) == 1

    @pytest.mark.asyncio
    async def test_search_matches_tag(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._cached_skills = [
            SkillSearchResult(
                id="my-org/repo/skills/a",
                name="a",
                description="alpha",
                source="github-tap",
                author="my-org",
                install_url="https://github.com/my-org/repo",
                install_method="git",
                tags=["security"],
            )
        ]
        source._cache_timestamp = time.monotonic()
        assert len(await source.search("security")) == 1
        assert await source.search("absent") == []

    @pytest.mark.asyncio
    async def test_search_respects_limit(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._cached_skills = [
            SkillSearchResult(
                id=f"my-org/repo/skills/{n}",
                name=n,
                description="alpha",
                source="github-tap",
                author="my-org",
                install_url="https://github.com/my-org/repo",
                install_method="git",
            )
            for n in ("a", "b", "c")
        ]
        source._cache_timestamp = time.monotonic()
        assert len(await source.search("alpha", limit=2)) == 2

    @pytest.mark.asyncio
    async def test_search_swallows_fetch_errors(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._fetch_all_skills = AsyncMock(side_effect=PermissionError("nope"))
        assert await source.search("a") == []

    @pytest.mark.asyncio
    async def test_get_detail_finds_and_misses(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        skill = SkillSearchResult(
            id="my-org/repo/skills/a",
            name="a",
            description="alpha",
            source="github-tap",
            author="my-org",
            install_url="https://github.com/my-org/repo",
            install_method="git",
        )
        source._cached_skills = [skill]
        source._cache_timestamp = time.monotonic()
        assert await source.get_detail("my-org/repo/skills/a") is skill
        assert await source.get_detail("other") is None

    @pytest.mark.asyncio
    async def test_get_detail_swallows_errors(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._fetch_all_skills = AsyncMock(side_effect=ValueError("gone"))
        assert await source.get_detail("my-org/repo/skills/a") is None

    @pytest.mark.asyncio
    async def test_probe_reports_failure(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._fetch_all_skills = AsyncMock(side_effect=ValueError("gone"))
        assert await source.probe() == (False, 0)

    @pytest.mark.asyncio
    async def test_probe_reports_success(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        source._cached_skills = [
            SkillSearchResult(
                id="a",
                name="a",
                description="d",
                source="github-tap",
                author="my-org",
                install_url="u",
                install_method="git",
            )
        ]
        source._fetch_all_skills = AsyncMock(return_value=source._cached_skills)
        assert await source.probe() == (True, 1)


class TestCacheAndParsing:
    @pytest.mark.asyncio
    @respx.mock
    async def test_second_fetch_uses_cache(self) -> None:
        route = respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=_tree_response([])
        )
        source = GitHubTapSkillSource("my-org/repo")
        await source._fetch_all_skills()
        await source._fetch_all_skills()
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_force_refresh_bypasses_cache(self) -> None:
        route = respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=_tree_response([])
        )
        source = GitHubTapSkillSource("my-org/repo")
        await source._fetch_all_skills()
        await source._fetch_all_skills(force_refresh=True)
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_skips_non_blob_entries(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=Response(
                200,
                json={"tree": [{"path": "skills/a/SKILL.md", "type": "tree"}]},
            )
        )
        respx.get(url__startswith="https://raw.githubusercontent.com/").mock(
            return_value=Response(200, text="no frontmatter")
        )
        assert await GitHubTapSkillSource("my-org/repo")._fetch_all_skills() == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_raw_file_skipped(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=_tree_response(["skills/a/SKILL.md"])
        )
        respx.get(url__startswith="https://raw.githubusercontent.com/").mock(return_value=Response(404))
        assert await GitHubTapSkillSource("my-org/repo")._fetch_all_skills() == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_raw_fetch_error_skipped(self) -> None:
        respx.get(url__startswith="https://api.github.com/repos/my-org/repo/git/trees/").mock(
            return_value=_tree_response(["skills/a/SKILL.md"])
        )
        respx.get(url__startswith="https://raw.githubusercontent.com/").mock(side_effect=httpx.TimeoutException("slow"))
        assert await GitHubTapSkillSource("my-org/repo")._fetch_all_skills() == []

    @pytest.mark.parametrize(
        ("content", "expected_tags_contain"),
        [
            ("---\nname: A\n---\n", ["tap", "my-org"]),
            ("---\ntags: [x, y]\n---\n", ["x", "y"]),
            ("---\ntags: notalist\n---\n", ["tap", "my-org"]),
            ("no frontmatter", ["tap", "my-org"]),
            ("---\nbroken: [\n---\n", ["tap", "my-org"]),
        ],
    )
    def test_parse_skill_content_tags(self, content: str, expected_tags_contain: list[str]) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        _, _, tags, _ = source._parse_skill_content(content, fallback_name="fb")
        for tag in expected_tags_contain:
            assert tag in tags

    def test_parse_skill_content_requirements_alias(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        _, _, _, prereqs = source._parse_skill_content(
            "---\ndependencies:\n  binaries: [git]\n---\n", fallback_name="fb"
        )
        assert prereqs == {"binaries": ["git"]}

    def test_parse_skill_content_fallback_description(self) -> None:
        source = GitHubTapSkillSource("my-org/repo")
        name, description, _, prereqs = source._parse_skill_content("body", fallback_name="fb")
        assert name == "fb"
        assert description == "Skill from tap my-org/repo"
        assert prereqs is None
