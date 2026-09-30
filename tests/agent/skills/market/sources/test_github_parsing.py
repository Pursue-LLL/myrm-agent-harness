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
