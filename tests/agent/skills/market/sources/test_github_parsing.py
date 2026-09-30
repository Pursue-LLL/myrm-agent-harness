"""Unit tests for GitHub skill source payload parsing.

[INPUT]
- myrm_agent_harness.agent.skills.market.sources.github

[OUTPUT]
- pytest suite covering repository-search parsing, skill-id construction,
  deduplication, plugin detection, and path helpers.

[POS]
myrm-agent-harness/tests/agent/skills/market/sources/test_github_parsing.py
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from myrm_agent_harness.agent.skills.market.sources.github import (
    GitHubSkillSource,
    _extract_skill_directory,
    analyze_github_url,
)
from myrm_agent_harness.agent.skills.market.taps import TapSubscription
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult


def _repo(full_name: str, *, path: str) -> dict:
    """Build a code-search item; the parser reads the repo name from ``repository``."""
    return {
        "repository": {
            "full_name": full_name,
            "name": full_name.split("/")[-1],
            "stargazers_count": 3,
            "description": "d",
        },
        "path": path,
    }


def _search_payload(items: list[dict]) -> dict:
    return {"items": items, "total_count": len(items)}


class TestRepositoryParsing:
    def test_builds_skill_id_from_repo_and_subdirectory(self) -> None:
        source = GitHubSkillSource()
        results = source._parse_code_search_results(
            _search_payload([_repo("acme/tools", path="skills/pdf/SKILL.md")]),
            limit=10,
        )

        assert [r.id for r in results] == ["acme/tools/skills/pdf"]
        assert results[0].name == "pdf"
        assert results[0].source == "github"

    def test_repo_without_subdirectory_uses_repo_name(self) -> None:
        source = GitHubSkillSource()
        results = source._parse_code_search_results(
            _search_payload([_repo("acme/solo", path="SKILL.md")]),
            limit=10,
        )

        assert [r.id for r in results] == ["acme/solo"]
        assert results[0].name == "solo"

    def test_plugin_json_marks_agent_plugin(self) -> None:
        source = GitHubSkillSource()
        results = source._parse_code_search_results(
            _search_payload([_repo("acme/ext", path="plugin.json")]),
            limit=10,
        )

        assert results[0].package_type == "agent_plugin"
        assert "plugin" in results[0].tags

    def test_skips_non_dict_and_duplicates(self) -> None:
        source = GitHubSkillSource()
        results = source._parse_code_search_results(
            _search_payload(
                [
                    "junk",
                    _repo("acme/tools", path="skills/pdf/SKILL.md"),
                    _repo("acme/tools", path="skills/pdf/SKILL.md"),
                ]
            ),
            limit=10,
        )

        assert len(results) == 1

    def test_honours_limit(self) -> None:
        source = GitHubSkillSource()
        results = source._parse_code_search_results(
            _search_payload(
                [
                    _repo("acme/a", path="skills/a/SKILL.md"),
                    _repo("acme/b", path="skills/b/SKILL.md"),
                ]
            ),
            limit=1,
        )

        assert len(results) == 1

    def test_empty_payload_returns_empty_list(self) -> None:
        source = GitHubSkillSource()
        assert source._parse_code_search_results({}, limit=5) == []


class TestPathHelpers:
    @pytest.mark.parametrize(
        ("file_path", "expected"),
        [
            ("skills/pdf/SKILL.md", "skills/pdf"),
            ("SKILL.md", None),
            ("skills/pdf/README.md", None),
            ("skill.yaml", None),
        ],
    )
    def test_extract_skill_directory(self, file_path: str, expected: str | None) -> None:
        assert _extract_skill_directory(file_path) == expected


class TestGitHubRefUrlParsing:
    def test_ref_skill_id_includes_subdirectory(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import GitHubRef

        ref = GitHubRef(owner="acme", repo="tools", subdirectory="skills/pdf")
        assert ref.skill_id == "acme/tools/skills/pdf"
        assert ref.clone_url == "https://github.com/acme/tools.git"

    def test_ref_without_subdirectory_uses_base(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import GitHubRef

        assert GitHubRef(owner="acme", repo="tools").skill_id == "acme/tools"

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/acme/tools",
            "https://github.com/acme/tools.git",
            "acme/tools",
        ],
    )
    def test_parses_owner_repo_forms(self, url: str) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        ref = parse_github_url(url)
        assert (ref.owner, ref.repo) == ("acme", "tools")

    def test_parses_tree_url_with_subdirectory(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        ref = parse_github_url("https://github.com/acme/tools/tree/main/skills/pdf")
        assert ref.subdirectory == "skills/pdf"

    @pytest.mark.parametrize(
        ("url", "ref", "subdir"),
        [
            ("acme/tools/tree/v2", "v2", None),
            ("acme/tools/tree/main/skills/pdf", "main", "skills/pdf"),
            ("acme/tools/blob/v2/SKILL.md", "v2", "SKILL.md"),
        ],
    )
    def test_parses_shorthand_tree_forms(self, url: str, ref: str, subdir: str | None) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        parsed = parse_github_url(url)
        assert parsed.ref == ref
        assert parsed.subdirectory == subdir

    def test_shorthand_tree_rejects_traversal(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        with pytest.raises(ValueError, match="traversal"):
            parse_github_url("acme/tools/tree/main/../etc")

    def test_shorthand_subdirectory_without_tree_still_works(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        parsed = parse_github_url("acme/tools/skills/pdf")
        assert parsed.ref is None
        assert parsed.subdirectory == "skills/pdf"

    def test_parses_shorthand_with_subdirectory(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        assert parse_github_url("acme/tools/skills/pdf").subdirectory == "skills/pdf"

    @pytest.mark.parametrize("url", ["", "   "])
    def test_rejects_empty_url(self, url: str) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        with pytest.raises(ValueError, match="Empty URL"):
            parse_github_url(url)

    def test_rejects_path_traversal(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url

        with pytest.raises(ValueError):
            parse_github_url("https://github.com/acme/tools/tree/main/../../etc")


class TestFrontmatterDescription:
    def test_extracts_description_from_frontmatter(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import (
            _extract_description_from_skill_md,
        )

        content = "---\nname: Alpha\ndescription: does alpha things\n---\n# body"
        assert _extract_description_from_skill_md(content) == "does alpha things"

    @pytest.mark.parametrize(
        "content",
        ["no frontmatter at all", "---\nnot: [valid\n---\nbody", ""],
    )
    def test_returns_none_without_usable_frontmatter(self, content: str) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import (
            _extract_description_from_skill_md,
        )

        assert _extract_description_from_skill_md(content) is None


class TestSkillMarkdownFetch:
    @pytest.mark.asyncio
    async def test_fetches_skill_md(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource

        resp = MagicMock()
        resp.status_code = 200
        resp.text = "# alpha"
        client = AsyncMock()
        client.get.return_value = resp
        client.__aenter__.return_value = client

        with patch("myrm_agent_harness.agent.skills.market.sources.github.create_httpx_client") as cls:
            cls.return_value = client
            content = await GitHubSkillSource()._fetch_skill_md(
                client, "acme", "tools", "skills/pdf", {"Accept": "raw"}
            )

        assert content == "# alpha"
        assert "skills/pdf/SKILL.md" in client.get.await_args.args[0]

    @pytest.mark.asyncio
    async def test_returns_none_on_non_200(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource

        resp = MagicMock()
        resp.status_code = 404
        client = AsyncMock()
        client.get.return_value = resp
        client.__aenter__.return_value = client

        with patch("myrm_agent_harness.agent.skills.market.sources.github.create_httpx_client") as cls:
            cls.return_value = client
            content = await GitHubSkillSource()._fetch_skill_md(client, "acme", "tools", None, {"Accept": "raw"})

        assert content is None
        assert client.get.await_args.args[0].endswith("/SKILL.md")


class TestTokenHeader:
    def test_no_token_omits_authorization(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource

        assert "Authorization" not in GitHubSkillSource()._build_headers()

    def test_token_adds_authorization(self) -> None:
        from myrm_agent_harness.agent.skills.market.sources.github import GitHubSkillSource

        headers = GitHubSkillSource(token="t0k3n")._build_headers()
        assert headers["Authorization"] == "token t0k3n"


class TestSearchHttpBranches:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_results_on_success(self) -> None:
        route = respx.get("https://api.github.com/search/code").mock(
            return_value=httpx.Response(
                200,
                json=_search_payload([_repo("acme/tools", path="skills/pdf/SKILL.md")]),
            )
        )
        results = await GitHubSkillSource().search("pdf")

        assert [r.id for r in results] == ["acme/tools/skills/pdf"]
        assert route.calls.last.request.url.params["q"].endswith("SKILL.md in:path")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_returns_empty(self) -> None:
        respx.get("https://api.github.com/search/code").mock(return_value=httpx.Response(403))
        assert await GitHubSkillSource().search("pdf") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_server_error_returns_empty(self) -> None:
        respx.get("https://api.github.com/search/code").mock(return_value=httpx.Response(500))
        assert await GitHubSkillSource().search("pdf") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_timeout_returns_empty(self) -> None:
        respx.get("https://api.github.com/search/code").mock(side_effect=httpx.TimeoutException("slow"))
        assert await GitHubSkillSource().search("pdf") == []

    @pytest.mark.asyncio
    @respx.mock
    async def test_unexpected_error_returns_empty(self) -> None:
        respx.get("https://api.github.com/search/code").mock(side_effect=ValueError("bad payload"))
        assert await GitHubSkillSource().search("pdf") == []

    @pytest.mark.asyncio
    async def test_failing_tap_source_does_not_break_search(self) -> None:
        source = GitHubSkillSource(extra_taps=[{"repo": "acme/tap"}])
        source._tap_source = AsyncMock()
        source._tap_source.search.side_effect = RuntimeError("tap down")

        with respx.mock:
            respx.get("https://api.github.com/search/code").mock(
                return_value=httpx.Response(
                    200, json=_search_payload([_repo("acme/tools", path="skills/pdf/SKILL.md")])
                )
            )
            results = await source.search("pdf")

        assert [r.id for r in results] == ["acme/tools/skills/pdf"]

    @pytest.mark.asyncio
    async def test_tap_results_take_priority_and_dedup(self) -> None:
        tap_result = SkillSearchResult(
            id="acme/tools/skills/pdf",
            name="pdf",
            description="tap skill",
            source="tap",
            author="acme",
            install_url="https://github.com/acme/tools/tree/main/skills/pdf",
            install_method="git",
        )
        source = GitHubSkillSource(extra_taps=[{"repo": "acme/tap"}])
        source._tap_source = AsyncMock()
        source._tap_source.search.return_value = [tap_result]

        with respx.mock:
            respx.get("https://api.github.com/search/code").mock(
                return_value=httpx.Response(
                    200,
                    json=_search_payload(
                        [
                            _repo("acme/tools", path="skills/pdf/SKILL.md"),
                            _repo("acme/other", path="skills/other/SKILL.md"),
                        ]
                    ),
                )
            )
            results = await source.search("pdf", limit=5)

        assert [r.id for r in results] == ["acme/tools/skills/pdf", "acme/other/skills/other"]

    @pytest.mark.asyncio
    async def test_rate_limit_still_returns_tap_results(self) -> None:
        tap_result = SkillSearchResult(
            id="tap/one",
            name="one",
            description="tap skill",
            source="tap",
            author="acme",
            install_url="https://github.com/acme/tap/tree/main/skills/one",
            install_method="git",
        )
        source = GitHubSkillSource(extra_taps=[{"repo": "acme/tap"}])
        source._tap_source = AsyncMock()
        source._tap_source.search.return_value = [tap_result]

        with respx.mock:
            respx.get("https://api.github.com/search/code").mock(return_value=httpx.Response(403))
            results = await source.search("pdf")

        assert [r.id for r in results] == ["tap/one"]

    def test_extra_taps_accepts_mapping_and_instance(self) -> None:
        mapping_source = GitHubSkillSource(extra_taps=[{"repo": "acme/tap"}])
        instance_source = GitHubSkillSource(extra_taps=[TapSubscription(repo="acme/tap")])
        assert mapping_source._tap_source is not None
        assert instance_source._tap_source is not None

    def test_source_name(self) -> None:
        assert GitHubSkillSource().source_name == "github"


class TestGetDetail:
    @pytest.mark.asyncio
    async def test_returns_none_for_malformed_id(self) -> None:
        assert await GitHubSkillSource().get_detail("noslash") is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_none_on_missing_repo(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(return_value=httpx.Response(404))
        assert await GitHubSkillSource().get_detail("acme/tools") is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_prefers_skill_md_description(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(
            return_value=httpx.Response(
                200,
                json={
                    "description": "repo level",
                    "clone_url": "https://github.com/acme/tools.git",
                    "stargazers_count": 12,
                    "topics": ["pdf"],
                },
            )
        )
        respx.get(url__startswith="https://api.github.com/repos/acme/tools/contents/").mock(
            return_value=httpx.Response(200, text="---\ndescription: skill level\n---\n# body")
        )
        result = await GitHubSkillSource().get_detail("acme/tools/skills/pdf")

        assert result is not None
        assert result.description == "skill level"
        assert result.name == "pdf"
        assert result.stars == 12
        assert result.install_method == "git"
        assert result.subdirectory == "skills/pdf"

    @pytest.mark.asyncio
    @respx.mock
    async def test_falls_back_to_repo_description(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(
            return_value=httpx.Response(200, json={"description": "repo level"})
        )
        respx.get(url__startswith="https://api.github.com/repos/acme/tools/contents/").mock(
            return_value=httpx.Response(404)
        )
        result = await GitHubSkillSource().get_detail("acme/tools")

        assert result is not None
        assert result.description == "repo level"
        assert result.name == "tools"
        assert result.install_url == "https://github.com/acme/tools.git"
        assert result.subdirectory is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_error_returns_none(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(side_effect=httpx.TimeoutException("slow"))
        assert await GitHubSkillSource().get_detail("acme/tools") is None


class TestAnalyzeGitHubUrl:
    @staticmethod
    def _repo_main() -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )

    @staticmethod
    def _tree(*paths: str, truncated: bool = False, items: object = None) -> httpx.Response:
        if items is not None:
            return httpx.Response(200, json={"tree": items})
        return httpx.Response(
            200,
            json={"truncated": truncated, "tree": [{"path": p, "type": "blob"} for p in paths]},
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_resolves_default_branch_and_finds_skills(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(
            return_value=httpx.Response(200, json={"default_branch": "develop"})
        )
        route = respx.get(
            "https://api.github.com/repos/acme/tools/git/trees/develop",
            params={"recursive": "1"},
        ).mock(return_value=self._tree("skills/pdf/SKILL.md", "skills/img/agent.yml", "README.md"))

        refs = await analyze_github_url("acme/tools")

        assert route.called
        assert [r.subdirectory for r in refs] == ["skills/img", "skills/pdf"]
        assert all(r.ref == "develop" for r in refs)

    @pytest.mark.asyncio
    @respx.mock
    async def test_uses_explicit_branch_and_skips_hidden_and_non_blob(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools/git/trees/v2", params={"recursive": "1"}).mock(
            return_value=httpx.Response(
                200,
                json={
                    "tree": [
                        {"path": "skills/pdf/SKILL.md", "type": "blob"},
                        {"path": ".github/SKILL.md", "type": "blob"},
                        {"path": ".hidden", "type": "blob"},
                        {"path": "skills/img/SKILL.md", "type": "tree"},
                    ]
                },
            )
        )
        refs = await analyze_github_url("https://github.com/acme/tools/tree/v2")
        assert [r.subdirectory for r in refs] == ["skills/pdf"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_by_requested_subdirectory(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree("skills/pdf/SKILL.md", "other/img/SKILL.md")
        )
        refs = await analyze_github_url("https://github.com/acme/tools/tree/main/skills")
        assert [r.subdirectory for r in refs] == ["skills/pdf"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_root_level_skill_has_no_subdirectory(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree("SKILL.md")
        )
        refs = await analyze_github_url("acme/tools")
        assert refs[0].subdirectory is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_on_repo_lookup_raises(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(return_value=httpx.Response(403))
        with pytest.raises(Exception, match="rate limit exceeded"):
            await analyze_github_url("acme/tools")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_on_tree_raises(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=httpx.Response(403)
        )
        with pytest.raises(Exception, match="rate limit exceeded during tree traversal"):
            await analyze_github_url("acme/tools")

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_repo_returns_parsed_ref(self) -> None:
        respx.get("https://api.github.com/repos/acme/tools").mock(return_value=httpx.Response(404))
        refs = await analyze_github_url("acme/tools")
        assert [r.skill_id for r in refs] == ["acme/tools"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_tree_error_returns_parsed_ref(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=httpx.Response(500)
        )
        assert [r.skill_id for r in await analyze_github_url("acme/tools")] == ["acme/tools"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_truncated_tree_returns_parsed_ref(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree("skills/pdf/SKILL.md", truncated=True)
        )
        assert [r.skill_id for r in await analyze_github_url("acme/tools")] == ["acme/tools"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_malformed_tree_payload_returns_parsed_ref(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree(items="not-a-list")
        )
        assert [r.skill_id for r in await analyze_github_url("acme/tools")] == ["acme/tools"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_skills_found_returns_parsed_ref(self) -> None:
        self._repo_main()
        respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree("README.md", "docs/guide.md")
        )
        assert [r.skill_id for r in await analyze_github_url("acme/tools")] == ["acme/tools"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_is_sent_on_tree_request(self) -> None:
        repo = respx.get("https://api.github.com/repos/acme/tools").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        tree = respx.get("https://api.github.com/repos/acme/tools/git/trees/main", params={"recursive": "1"}).mock(
            return_value=self._tree("skills/pdf/SKILL.md")
        )

        await analyze_github_url("acme/tools", token="t0k3n")

        assert repo.calls.last.request.headers["Authorization"] == "token t0k3n"
        assert tree.calls.last.request.headers["Authorization"] == "token t0k3n"

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejects_unparseable_url(self) -> None:
        with pytest.raises(ValueError):
            await analyze_github_url("")
