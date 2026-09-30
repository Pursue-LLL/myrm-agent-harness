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

import pytest

from myrm_agent_harness.agent.skills.market.sources.github import (
    GitHubSkillSource,
    _extract_skill_directory,
)


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
