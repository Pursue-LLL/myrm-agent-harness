from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.discovery.sources.github import analyze_github_url


@pytest.fixture
def mock_httpx():
    with patch("httpx.AsyncClient") as mock_client:
        mock_instance = mock_client.return_value.__aenter__.return_value
        yield mock_instance

@pytest.mark.asyncio
async def test_analyze_github_url_single_skill(mock_httpx):
    # Mock default branch
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=200, json=lambda: {"default_branch": "main"}),
        AsyncMock(status_code=200, json=lambda: {
            "truncated": False,
            "tree": [
                {"path": "skills/my-skill/SKILL.md", "type": "blob"}
            ]
        })
    ]

    url = "https://github.com/owner/repo"
    refs = await analyze_github_url(url)

    assert len(refs) == 1
    assert refs[0].owner == "owner"
    assert refs[0].repo == "repo"
    assert refs[0].ref == "main"
    assert refs[0].subdirectory == "skills/my-skill"

@pytest.mark.asyncio
async def test_analyze_github_url_multiple_skills(mock_httpx):
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=200, json=lambda: {"default_branch": "master"}),
        AsyncMock(status_code=200, json=lambda: {
            "truncated": False,
            "tree": [
                {"path": "skills/skill1/SKILL.md", "type": "blob"},
                {"path": "skills/skill2/agent.yaml", "type": "blob"},
                {"path": "not-a-skill/main.py", "type": "blob"}
            ]
        })
    ]

    url = "https://github.com/owner/repo"
    refs = await analyze_github_url(url)

    assert len(refs) == 2
    subdirs = [r.subdirectory for r in refs]
    assert "skills/skill1" in subdirs
    assert "skills/skill2" in subdirs
    assert refs[0].ref == "master"

@pytest.mark.asyncio
async def test_analyze_github_url_403_rate_limit(mock_httpx):
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=403, json=lambda: {})
    ]

    url = "https://github.com/owner/repo"
    with pytest.raises(Exception, match="rate limit exceeded"):
        await analyze_github_url(url)

@pytest.mark.asyncio
async def test_analyze_github_url_truncated_tree(mock_httpx):
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=200, json=lambda: {"default_branch": "main"}),
        AsyncMock(status_code=200, json=lambda: {
            "truncated": True,
            "tree": []
        })
    ]

    url = "https://github.com/owner/repo"
    refs = await analyze_github_url(url)

    # Should fallback to original ref if truncated
    assert len(refs) == 1
    assert refs[0].owner == "owner"
    assert refs[0].repo == "repo"
    assert refs[0].subdirectory is None

@pytest.mark.asyncio
async def test_analyze_github_url_no_skills_found(mock_httpx):
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=200, json=lambda: {"default_branch": "main"}),
        AsyncMock(status_code=200, json=lambda: {
            "truncated": False,
            "tree": [
                {"path": "src/main.py", "type": "blob"}
            ]
        })
    ]

    url = "https://github.com/owner/repo"
    refs = await analyze_github_url(url)

    # Should fallback to original ref
    assert len(refs) == 1
    assert refs[0].owner == "owner"
    assert refs[0].repo == "repo"
    assert refs[0].subdirectory is None

from myrm_agent_harness.agent.skills.discovery.sources.github import (
    GitHubSkillSource,
    _extract_description_from_skill_md,
    _extract_skill_directory,
    _sanitize_path,
    parse_github_url,
)


# Test parse_github_url
def test_parse_github_url_empty():
    with pytest.raises(ValueError, match="Empty URL"):
        parse_github_url("   ")

def test_parse_github_url_tree():
    ref = parse_github_url("https://github.com/owner/repo/tree/main/subdir")
    assert ref.owner == "owner"
    assert ref.repo == "repo"
    assert ref.ref == "main"
    assert ref.subdirectory == "subdir"

def test_parse_github_url_blob():
    ref = parse_github_url("https://github.com/owner/repo/blob/main/subdir/SKILL.md")
    assert ref.owner == "owner"
    assert ref.repo == "repo"
    assert ref.ref == "main"
    assert ref.subdirectory == "subdir/SKILL.md"

def test_parse_github_url_root():
    ref = parse_github_url("https://github.com/owner/repo")
    assert ref.owner == "owner"
    assert ref.repo == "repo"
    assert ref.ref is None
    assert ref.subdirectory is None

def test_parse_github_url_short():
    ref = parse_github_url("owner/repo/subdir")
    assert ref.owner == "owner"
    assert ref.repo == "repo"
    assert ref.ref is None
    assert ref.subdirectory == "subdir"

def test_parse_github_url_invalid_host():
    with pytest.raises(ValueError, match="Only github.com URLs are supported"):
        parse_github_url("https://gitlab.com/owner/repo")

def test_parse_github_url_invalid_format():
    with pytest.raises(ValueError, match="Cannot parse GitHub reference"):
        parse_github_url("invalid_format_string")

# Test _sanitize_path
def test_sanitize_path():
    assert _sanitize_path(None) is None
    assert _sanitize_path("") is None
    assert _sanitize_path("foo/bar") == "foo/bar"
    with pytest.raises(ValueError, match="Path traversal detected"):
        _sanitize_path("foo/../bar")

# Test _extract_skill_directory
def test_extract_skill_directory():
    assert _extract_skill_directory("skills/bot/SKILL.md") == "skills/bot"
    assert _extract_skill_directory("SKILL.md") is None
    assert _extract_skill_directory("skills/bot/main.py") is None

# Test _extract_description_from_skill_md
def test_extract_description_from_skill_md():
    content = "---\nname: bot\ndescription: A test bot\n---\nbody"
    assert _extract_description_from_skill_md(content) == "A test bot"

    content2 = "no frontmatter"
    assert _extract_description_from_skill_md(content2) is None

    content3 = "---\ninvalid yaml\n---\n"
    assert _extract_description_from_skill_md(content3) is None

# Test GitHubSkillSource
@pytest.mark.asyncio
async def test_github_skill_source_search(mock_httpx):
    source = GitHubSkillSource(token="test_token")
    mock_httpx.get.return_value = AsyncMock(
        status_code=200,
        json=lambda: {
            "items": [
                {
                    "repository": {"full_name": "owner/repo", "description": "desc"},
                    "path": "skills/bot/SKILL.md"
                }
            ]
        }
    )
    results = await source.search("test query", limit=10)
    assert len(results) == 1
    assert results[0].id == "owner/repo/skills/bot"
    assert results[0].name == "bot"
    assert results[0].author == "owner"

@pytest.mark.asyncio
async def test_github_skill_source_search_403(mock_httpx):
    source = GitHubSkillSource()
    mock_httpx.get.return_value = AsyncMock(status_code=403)
    results = await source.search("test", limit=10)
    assert len(results) == 0

@pytest.mark.asyncio
async def test_github_skill_source_get_detail(mock_httpx):
    source = GitHubSkillSource()
    mock_httpx.get.side_effect = [
        AsyncMock(status_code=200, json=lambda: {"description": "repo desc", "clone_url": "url", "stargazers_count": 10, "topics": ["ai"]}),
        AsyncMock(status_code=200, text="---\ndescription: skill desc\n---\n")
    ]
    detail = await source.get_detail("owner/repo/skills/bot")
    assert detail is not None
    assert detail.id == "owner/repo/skills/bot"
    assert detail.name == "bot"
    assert detail.description == "skill desc"

@pytest.mark.asyncio
async def test_github_skill_source_get_detail_invalid_id():
    source = GitHubSkillSource()
    assert await source.get_detail("invalid_id") is None
