"""GitHub 技能搜索源

通过 GitHub Search API 搜索包含 SKILL.md 的仓库。
同时提供 parse_github_url() 用于智能解析各种 GitHub URL 格式。

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- GitHubSkillSource: class — Git Hub Skill Source
- GitHubRef: Parsed GitHub repository reference.
- parse_github_url: Parse a GitHub URL or shorthand into a GitHubRef.
- analyze_github_url: Smart GitHub URL penetration parser.

[POS]
Provides GitHubSkillSource, GitHubRef, parse_github_url.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import yaml

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_SEARCH_TIMEOUT = 15.0
GITHUB_SKILL_QUERY_SUFFIX = "SKILL.md in:path"


class GitHubSkillSource:
    """GitHub 技能数据源

    通过 GitHub Code/Repository Search API 搜索技能。
    搜索策略：query + "SKILL.md in:path" 确保结果包含 SKILL.md。
    """

    def __init__(self, token: str | None = None):
        self._token = token

    @property
    def source_name(self) -> str:
        return "github"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        search_query = f"{query} {GITHUB_SKILL_QUERY_SUFFIX}"
        headers = self._build_headers()

        try:
            async with httpx.AsyncClient(timeout=GITHUB_SEARCH_TIMEOUT) as client:
                resp = await client.get(
                    f"{GITHUB_API_BASE}/search/code",
                    params={"q": search_query, "per_page": min(limit * 2, 30)},
                    headers=headers,
                )
                if resp.status_code == 403:
                    logger.warning("GitHub API rate limit exceeded")
                    return []
                if resp.status_code != 200:
                    logger.warning(f"GitHub search failed: {resp.status_code}")
                    return []

                data = resp.json()
                return self._parse_code_search_results(data, limit)

        except httpx.TimeoutException:
            logger.warning("GitHub search timed out")
            return []
        except Exception as e:
            logger.warning(f"GitHub search error: {e}")
            return []

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        parts = skill_id.split("/", 2)
        if len(parts) < 2:
            return None

        owner, repo = parts[0], parts[1]
        subdirectory = parts[2] if len(parts) > 2 else None

        headers = self._build_headers()
        try:
            async with httpx.AsyncClient(timeout=GITHUB_SEARCH_TIMEOUT) as client:
                resp = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=headers)
                if resp.status_code != 200:
                    return None
                repo_data = resp.json()

                skill_md_content = await self._fetch_skill_md(client, owner, repo, subdirectory, headers)
                description = repo_data.get("description", "") or ""
                if skill_md_content:
                    parsed = _extract_description_from_skill_md(skill_md_content)
                    if parsed:
                        description = parsed

                return SkillSearchResult(
                    id=skill_id,
                    name=subdirectory.split("/")[-1] if subdirectory else repo,
                    description=description,
                    source="github",
                    author=owner,
                    install_url=repo_data.get("clone_url", f"https://github.com/{owner}/{repo}.git"),
                    install_method="git",
                    stars=repo_data.get("stargazers_count", 0),
                    tags=repo_data.get("topics", []),
                    readme_url=f"https://github.com/{owner}/{repo}",
                    subdirectory=subdirectory,
                )
        except Exception as e:
            logger.warning(f"GitHub get_detail error for {skill_id}: {e}")
            return None

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    def _parse_code_search_results(self, data: dict[str, object], limit: int) -> list[SkillSearchResult]:
        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        seen_repos: set[str] = set()
        results: list[SkillSearchResult] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            repo_info = item.get("repository", {})
            if not isinstance(repo_info, dict):
                continue

            full_name = str(repo_info.get("full_name", ""))
            if not full_name or full_name in seen_repos:
                continue
            seen_repos.add(full_name)

            path = str(item.get("path", ""))
            subdirectory = _extract_skill_directory(path)

            owner, repo = full_name.split("/", 1) if "/" in full_name else (full_name, "")
            skill_id = f"{full_name}/{subdirectory}" if subdirectory else full_name

            results.append(
                SkillSearchResult(
                    id=skill_id,
                    name=subdirectory.split("/")[-1] if subdirectory else repo,
                    description=str(repo_info.get("description", "")) or "",
                    source="github",
                    author=owner,
                    install_url=f"https://github.com/{full_name}.git",
                    install_method="git",
                    tags=[],
                    readme_url=f"https://github.com/{full_name}",
                    subdirectory=subdirectory,
                )
            )

            if len(results) >= limit:
                break

        return results

    async def _fetch_skill_md(
        self, client: httpx.AsyncClient, owner: str, repo: str, subdirectory: str | None, headers: dict[str, str]
    ) -> str | None:
        path = f"{subdirectory}/SKILL.md" if subdirectory else "SKILL.md"
        resp = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}",
            headers={**headers, "Accept": "application/vnd.github.v3.raw"},
        )
        if resp.status_code == 200:
            return resp.text
        return None


def _extract_skill_directory(file_path: str) -> str | None:
    """从 SKILL.md 文件路径提取技能目录

    例如：'skills/react-optimizer/SKILL.md' → 'skills/react-optimizer'
    """
    if file_path.endswith("/SKILL.md"):
        return file_path[: -len("/SKILL.md")]
    if file_path == "SKILL.md":
        return None
    return None


def _extract_description_from_skill_md(content: str) -> str | None:
    """从 SKILL.md frontmatter 中提取 description"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return None
    try:
        frontmatter = yaml.safe_load(match.group(1))
        if isinstance(frontmatter, dict):
            return str(frontmatter.get("description", ""))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# GitHub URL parser
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9\-_.]+)/"
    r"(?P<repo>[A-Za-z0-9\-_.]+?)(?:\.git)?$"
)

_GITHUB_TREE_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9\-_.]+)/"
    r"(?P<repo>[A-Za-z0-9\-_.]+)/"
    r"(?:tree|blob)/"
    r"(?P<ref>[^/]+)"
    r"(?:/(?P<path>.+))?$"
)

_SHORT_RE = re.compile(r"^(?P<owner>[A-Za-z0-9\-_.]+)/(?P<repo>[A-Za-z0-9\-_.]+)(?:/(?P<path>.+))?$")


@dataclass(frozen=True)
class GitHubRef:
    """Parsed GitHub repository reference."""

    owner: str
    repo: str
    ref: str | None = None
    subdirectory: str | None = None

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}.git"

    @property
    def skill_id(self) -> str:
        base = f"{self.owner}/{self.repo}"
        return f"{base}/{self.subdirectory}" if self.subdirectory else base


def parse_github_url(url: str) -> GitHubRef:
    """Parse a GitHub URL or shorthand into a GitHubRef.

    Supported formats:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - https://github.com/owner/repo/tree/main/skills/my-skill
        - https://github.com/owner/repo/blob/v2/SKILL.md
        - owner/repo
        - owner/repo/skills/my-skill

    Raises:
        ValueError: If the URL cannot be parsed or contains path traversal.
    """
    raw = url.strip().rstrip("/")
    if not raw:
        raise ValueError("Empty URL")

    # Full URL with tree/blob (branch + optional path)
    m = _GITHUB_TREE_RE.match(raw)
    if m:
        subdir = _sanitize_path(m.group("path"))
        return GitHubRef(owner=m.group("owner"), repo=m.group("repo"), ref=m.group("ref"), subdirectory=subdir)

    # Full URL without tree/blob
    m = _GITHUB_URL_RE.match(raw)
    if m:
        return GitHubRef(owner=m.group("owner"), repo=m.group("repo"))

    # Reject other full URLs (non-GitHub hosts)
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        raise ValueError(f"Only github.com URLs are supported, got: {parsed.netloc}")

    # Short format: owner/repo or owner/repo/path
    m = _SHORT_RE.match(raw)
    if m:
        subdir = _sanitize_path(m.group("path"))
        return GitHubRef(owner=m.group("owner"), repo=m.group("repo"), subdirectory=subdir)

    raise ValueError(f"Cannot parse GitHub reference: {url}")


def _sanitize_path(path: str | None) -> str | None:
    """Validate and sanitize a subdirectory path (prevent path traversal)."""
    if not path:
        return None
    clean = path.strip("/")
    if not clean:
        return None
    if ".." in clean.split("/"):
        raise ValueError(f"Path traversal detected in subdirectory: {path}")
    return clean


async def analyze_github_url(url: str, token: str | None = None) -> list[GitHubRef]:
    """Smart GitHub URL penetration parser.

    Takes a broad URL (e.g. repo root) and deeply scans it using the GitHub Tree API
    to find all subdirectories containing SKILL.md or agent.yaml.
    Returns a list of specific GitHubRefs ready for installation.
    If the original URL already points to a specific valid skill, it may just return that.
    If rate-limited or tree is too large, it raises an exception to trigger a fallback.

    Args:
        url: The GitHub repository URL or shorthand.
        token: Optional GitHub PAT to increase rate limits.
    """
    ref = parse_github_url(url)

    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Step 1: Resolve the default branch if ref is missing
        branch = ref.ref
        if not branch:
            resp = await client.get(f"{GITHUB_API_BASE}/repos/{ref.owner}/{ref.repo}", headers=headers)
            if resp.status_code == 403:
                raise Exception("GitHub API rate limit exceeded.")
            if resp.status_code != 200:
                # If repository not found, just return the parsed ref as-is
                return [ref]
            repo_data = resp.json()
            branch = str(repo_data.get("default_branch", "main"))

        # Step 2: Use Tree API with recursive=1 to scan the repository
        tree_url = f"{GITHUB_API_BASE}/repos/{ref.owner}/{ref.repo}/git/trees/{branch}?recursive=1"
        resp = await client.get(tree_url, headers=headers)
        if resp.status_code == 403:
            raise Exception("GitHub API rate limit exceeded during tree traversal.")
        if resp.status_code != 200:
            return [ref]

        tree_data = resp.json()
        if tree_data.get("truncated"):
            # Tree too large, cannot safely scan everything. Fallback to just the original ref.
            return [ref]

        tree_items = tree_data.get("tree", [])
        if not isinstance(tree_items, list):
            return [ref]

        # Step 3: Find all files matching SKILL.md or agent.yaml
        found_subdirs: set[str] = set()

        # If the user provided a subdirectory, we only care about skills inside that subdirectory
        prefix = f"{ref.subdirectory}/" if ref.subdirectory else ""
        max_skills_per_repo = 100

        for item in tree_items:
            path = str(item.get("path", ""))
            if item.get("type") != "blob":
                continue

            # Filter hidden directories and files
            if "/." in path or path.startswith("."):
                continue

            if prefix and not path.startswith(prefix):
                continue

            name = path.split("/")[-1].lower()
            if name in ("skill.md", "agent.yaml", "agent.yml"):
                # Extract subdirectory
                parts = path.split("/")
                subdir = "/".join(parts[:-1]) if len(parts) > 1 else ""
                found_subdirs.add(subdir)

                if len(found_subdirs) >= max_skills_per_repo:
                    logger.warning(f"Reached max limit of {max_skills_per_repo} skills per repo. Truncating.")
                    break

        # If nothing found, return original ref so the user can still try to install it
        # (in case it's a valid structure we didn't recognize)
        if not found_subdirs:
            return [ref]

        # Return a list of specific GitHubRefs
        results = []
        for subdir in sorted(found_subdirs):
            results.append(
                GitHubRef(owner=ref.owner, repo=ref.repo, ref=branch, subdirectory=subdir if subdir else None)
            )

        return results
