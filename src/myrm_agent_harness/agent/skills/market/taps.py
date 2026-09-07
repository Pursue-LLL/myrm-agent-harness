"""Tap subscription and custom GitHub repository catalog sync engine.

Provides data models and dynamic Git Tree scanner for indexing skills
from personal or enterprise private/public GitHub repositories.

[INPUT]
- backends.skills.market_protocols::SkillSearchResult
- infra.tls_compat::create_httpx_client
- agent.skills.market.sources.github::parse_github_url, GitHubRef

[OUTPUT]
- TapSubscription: Dataclass for a GitHub Tap repository subscription.
- TapDirectoryScanner: Recursive Git tree scanner for extracting SKILL.md entries.
- GitHubTapSource: Market source aggregating registered Taps.

[POS]
myrm-agent-harness/src/myrm_agent_harness/agent/skills/market/taps.py
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import time
from typing import Any

import httpx
import yaml

from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TAP_TIMEOUT = 15.0
TAP_CACHE_TTL_SEC = 300.0  # 5 minutes in-memory cache for scanned tree


@dataclass(frozen=True, slots=True)
class TapSubscription:
    """Subscription configuration for an external GitHub skill repository tap."""

    repo: str  # e.g. "owner/repo" or "https://github.com/owner/repo"
    path: str = "skills/"  # subdirectory to look for skills
    auth_token: str | None = None
    branch: str = "main"
    label: str = ""

    def get_canonical_name(self) -> str:
        clean = self.repo.strip()
        if "github.com/" in clean:
            clean = clean.split("github.com/", 1)[-1].rstrip(".git").strip("/")
        return clean

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.auth_token:
            # Mask token in serialization
            data["auth_token"] = "***"
        return data


@dataclass(slots=True)
class TapCatalogCache:
    skills: list[SkillSearchResult] = field(default_factory=list)
    cached_at: float = 0.0
    commit_sha: str = ""


class TapDirectoryScanner:
    """Recursively scans GitHub repository Git Tree for SKILL.md files."""

    def __init__(self, tap: TapSubscription) -> None:
        self.tap = tap
        self._cache = TapCatalogCache()

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Myrm-Agent-Taps/1.0",
        }
        if self.tap.auth_token:
            headers["Authorization"] = f"Bearer {self.tap.auth_token}"
        return headers

    async def scan_skills(self, force_refresh: bool = False) -> list[SkillSearchResult]:
        now = time.monotonic()
        if not force_refresh and self._cache.skills and (now - self._cache.cached_at < TAP_CACHE_TTL_SEC):
            return self._cache.skills

        canonical_repo = self.tap.get_canonical_name()
        parts = canonical_repo.split("/", 1)
        if len(parts) != 2:
            logger.warning("Invalid tap repository format: %s", self.tap.repo)
            return []

        owner, repo_name = parts[0], parts[1]
        headers = self._build_headers()
        tree_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/git/trees/{self.tap.branch}?recursive=1"

        try:
            async with create_httpx_client(timeout=DEFAULT_TAP_TIMEOUT) as client:
                resp = await client.get(tree_url, headers=headers)
                if resp.status_code == 404 and self.tap.branch == "main":
                    # Fallback to master branch
                    tree_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo_name}/git/trees/master?recursive=1"
                    resp = await client.get(tree_url, headers=headers)

                if resp.status_code != 200:
                    logger.warning("Failed to fetch git tree for tap %s: HTTP %s", canonical_repo, resp.status_code)
                    return self._cache.skills

                data = resp.json()
                tree_items = data.get("tree", [])
                sha = str(data.get("sha", ""))

                prefix = self.tap.path.strip("/")
                if prefix:
                    prefix = f"{prefix}/"

                results: list[SkillSearchResult] = []
                for item in tree_items:
                    item_path = str(item.get("path", ""))
                    if not item_path.endswith("SKILL.md") and not item_path.endswith("skill.yaml"):
                        continue
                    if prefix and not item_path.startswith(prefix):
                        continue

                    # Determine skill subdirectory & name
                    skill_subpath = item_path.rsplit("/", 1)[0] if "/" in item_path else ""
                    skill_name = skill_subpath.rsplit("/", 1)[-1] if skill_subpath else repo_name

                    skill_id = f"{canonical_repo}/{skill_subpath}" if skill_subpath else canonical_repo
                    desc = f"Skill from tap {self.tap.label or canonical_repo}"

                    results.append(
                        SkillSearchResult(
                            id=skill_id,
                            name=skill_name,
                            description=desc,
                            source="github-tap",
                            author=owner,
                            stars=0,
                            forks=0,
                            url=f"https://github.com/{canonical_repo}/tree/{self.tap.branch}/{skill_subpath}",
                            extra={
                                "tap_repo": canonical_repo,
                                "tap_path": self.tap.path,
                                "branch": self.tap.branch,
                                "manifest_path": item_path,
                            },
                        )
                    )

                self._cache.skills = results
                self._cache.cached_at = now
                self._cache.commit_sha = sha
                return results

        except Exception as exc:
            logger.warning("Error scanning skills for tap %s: %s", canonical_repo, exc)
            return self._cache.skills


class GitHubTapSource:
    """SkillMarketBackend-compatible source for user registered GitHub Taps."""

    def __init__(self, taps: list[TapSubscription] | None = None) -> None:
        self._taps: dict[str, TapDirectoryScanner] = {}
        if taps:
            for tap in taps:
                self.register_tap(tap)

    @property
    def source_name(self) -> str:
        return "github-tap"

    def register_tap(self, tap: TapSubscription) -> None:
        self._taps[tap.get_canonical_name()] = TapDirectoryScanner(tap)

    def remove_tap(self, repo: str) -> bool:
        canonical = TapSubscription(repo=repo).get_canonical_name()
        return self._taps.pop(canonical, None) is not None

    def list_taps(self) -> list[TapSubscription]:
        return [scanner.tap for scanner in self._taps.values()]

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        all_skills: list[SkillSearchResult] = []
        for scanner in self._taps.values():
            skills = await scanner.scan_skills()
            all_skills.extend(skills)

        if not query.strip():
            return all_skills[:limit]

        query_lower = query.lower().strip()
        matched: list[SkillSearchResult] = []
        for s in all_skills:
            if query_lower in s.name.lower() or query_lower in s.description.lower() or query_lower in s.id.lower():
                matched.append(s)

        return matched[:limit]
