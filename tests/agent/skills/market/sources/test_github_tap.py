"""Unit tests for GitHubTapSkillSource."""

import pytest
import respx
from httpx import Response

from myrm_agent_harness.agent.skills.market.sources.github_tap import GitHubTapSkillSource


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
