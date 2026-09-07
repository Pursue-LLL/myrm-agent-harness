"""GitHub Tap (Custom Repository) Skill Source.

Allows users and enterprise organizations to subscribe to custom GitHub repositories as skill taps.
Recursively inspects the repository file tree (optionally under a subdirectory like `skills/`)
to discover and index valid `SKILL.md` skill definitions, with support for authentication tokens,
in-memory TTL caching, and graceful offline fallback.

[INPUT]
- backends.skills.market_protocols::SkillSearchResult (POS: Unified search result data class)
- infra.tls_compat::create_httpx_client (POS: Resilient HTTP client creation)
- agent.skills.market.sources.github::parse_github_url, GitHubRef (POS: GitHub URL parsing)

[OUTPUT]
- GitHubTapSkillSource: High-performance GitHub Tap skill data source.

[POS]
Provides GitHubTapSkillSource for custom private and organization skill repository subscriptions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final
from urllib.parse import urlparse

import httpx
import yaml

from myrm_agent_harness.agent.skills.market.sources.github import parse_github_url
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

GITHUB_API_BASE: Final[str] = "https://api.github.com"
DEFAULT_PROBE_TIMEOUT: Final[float] = 10.0
DEFAULT_FETCH_TIMEOUT: Final[float] = 15.0
DEFAULT_CACHE_TTL: Final[float] = 300.0  # 5 minutes in-memory cache


class GitHubTapSkillSource:
    """Discover skills from a subscribed GitHub repository (Tap).

    Supports public and private repositories (via Personal Access Token),
    scanning for `SKILL.md` files at repository root or inside a designated subdirectory (e.g. `skills/`).
    """

    def __init__(
        self,
        repo_url: str,
        token: str | None = None,
        subdirectory: str | None = None,
        ttl_seconds: float = DEFAULT_CACHE_TTL,
    ) -> None:
        ref = parse_github_url(repo_url)
        self._owner: str = ref.owner
        self._repo: str = ref.repo
        self._ref: str = ref.ref or "HEAD"
        # Subdirectory precedence: explicit arg > path parsed from URL > None
        self._subdirectory: str | None = subdirectory or ref.subdirectory
        if self._subdirectory:
            self._subdirectory = self._subdirectory.strip("/")
        self._token: str | None = token
        self._ttl_seconds: float = ttl_seconds

        self._cached_skills: list[SkillSearchResult] | None = None
        self._cache_timestamp: float = 0.0

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def repo(self) -> str:
        return self._repo

    @property
    def subdirectory(self) -> str | None:
        return self._subdirectory

    @property
    def source_name(self) -> str:
        sub = f"/{self._subdirectory}" if self._subdirectory else ""
        return f"github-tap:{self._owner}/{self._repo}{sub}"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Myrm-Agent-Harness",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"
        return headers

    async def probe(self) -> tuple[bool, int]:
        """Probe repository reachability and count discoverable skills.

        Returns:
            Tuple of (reachable, skill_count).
        """
        try:
            skills = await self._fetch_all_skills(force_refresh=True)
            return True, len(skills)
        except Exception as exc:
            logger.warning("GitHub Tap probe failed for %s/%s: %s", self._owner, self._repo, exc)
            return False, 0

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        """Search skills within this Tap by matching name and description."""
        try:
            skills = await self._fetch_all_skills(force_refresh=False)
        except Exception as exc:
            logger.warning("Failed to fetch skills from GitHub Tap %s: %s", self.source_name, exc)
            return []

        if not query.strip():
            return skills[:limit]

        query_lower = query.lower().strip()
        matched: list[SkillSearchResult] = []
        for skill in skills:
            if (
                query_lower in skill.name.lower()
                or query_lower in skill.description.lower()
                or any(query_lower in t.lower() for t in skill.tags)
            ):
                matched.append(skill)
                if len(matched) >= limit:
                    break
        return matched

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        """Get detail of a skill by its skill_id."""
        try:
            skills = await self._fetch_all_skills(force_refresh=False)
            for skill in skills:
                if skill.skill_id == skill_id:
                    return skill
        except Exception as exc:
            logger.warning("Failed to get detail for %s from GitHub Tap: %s", skill_id, exc)
        return None

    async def _fetch_all_skills(self, force_refresh: bool = False) -> list[SkillSearchResult]:
        """Fetch and parse all SKILL.md entries from the repository tree."""
        now = time.monotonic()
        if not force_refresh and self._cached_skills is not None and (now - self._cache_timestamp < self._ttl_seconds):
            return self._cached_skills

        headers = self._build_headers()
        tree_url = f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/git/trees/{self._ref}?recursive=1"

        async with create_httpx_client(timeout=DEFAULT_FETCH_TIMEOUT) as client:
            resp = await client.get(tree_url, headers=headers)
            if resp.status_code == 404:
                raise ValueError(f"Repository {self._owner}/{self._repo} not found")
            if resp.status_code == 401 or resp.status_code == 403:
                raise PermissionError(f"Authentication failed or rate limit exceeded for {self._owner}/{self._repo}")
            resp.raise_for_status()
            data = resp.json()

        tree = data.get("tree", [])
        skill_files: list[str] = []
        prefix = f"{self._subdirectory}/" if self._subdirectory else ""

        for item in tree:
            if item.get("type") == "blob":
                path = item.get("path", "")
                if path.endswith("SKILL.md"):
                    if not prefix or path.startswith(prefix):
                        skill_files.append(path)

        results: list[SkillSearchResult] = []
        for path in skill_files:
            skill = await self._fetch_skill_detail(path)
            if skill:
                results.append(skill)

        self._cached_skills = results
        self._cache_timestamp = now
        return results

    async def _fetch_skill_detail(self, file_path: str) -> SkillSearchResult | None:
        """Fetch raw content of a specific SKILL.md and construct SkillSearchResult."""
        raw_url = f"https://raw.githubusercontent.com/{self._owner}/{self._repo}/{self._ref}/{file_path}"
        headers = {}
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        try:
            async with create_httpx_client(timeout=DEFAULT_PROBE_TIMEOUT) as client:
                resp = await client.get(raw_url, headers=headers)
                if resp.status_code != 200:
                    return None
                content = resp.text
        except Exception as exc:
            logger.debug("Failed to fetch raw SKILL.md at %s: %s", raw_url, exc)
            return None

        # Determine skill directory and skill_id
        parent_dir = "/".join(file_path.split("/")[:-1])
        skill_name = file_path.split("/")[-2] if "/" in file_path else self._repo
        skill_id = f"{self._owner}/{self._repo}/{parent_dir}" if parent_dir else f"{self._owner}/{self._repo}"

        name, description, tags, prereqs = self._parse_skill_content(content, fallback_name=skill_name)
        install_url = f"https://github.com/{self._owner}/{self._repo}"
        if parent_dir:
            install_url = f"{install_url}/tree/{self._ref}/{parent_dir}"

        return SkillSearchResult(
            skill_id=skill_id,
            name=name,
            description=description,
            author=self._owner,
            source=self.source_name,
            install_url=install_url,
            tags=tags,
            prerequisites=prereqs,
        )

    def _parse_skill_content(
        self, content: str, fallback_name: str
    ) -> tuple[str, str, list[str], dict[str, object] | None]:
        """Extract metadata from YAML frontmatter in SKILL.md."""
        name = fallback_name
        description = f"Skill from tap {self._owner}/{self._repo}"
        tags: list[str] = ["tap", self._owner]
        prereqs: dict[str, object] | None = None

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1])
                    if isinstance(meta, dict):
                        name = str(meta.get("name", name))
                        description = str(meta.get("description", description))
                        raw_tags = meta.get("tags", [])
                        if isinstance(raw_tags, list):
                            tags.extend(str(t) for t in raw_tags if t)
                        # Extract prerequisite dependencies if specified
                        req_data = meta.get("requirements") or meta.get("dependencies")
                        if isinstance(req_data, dict):
                            prereqs = dict(req_data)
                except Exception as exc:
                    logger.debug("YAML frontmatter parse error in SKILL.md: %s", exc)

        return name, description, list(set(tags)), prereqs
