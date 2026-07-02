"""skills.sh 技能搜索源

通过 skills.sh 生态搜索社区技能。
skills.sh 是 Vercel Labs 维护的开源技能注册表。

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- SkillsShSource: class — Skills Sh Source

[POS]
Provides SkillsShSource.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

SKILLS_SH_API_BASE = "https://skills.sh"
SKILLS_SH_API_TIMEOUT = 15.0

_VALID_INSTALL_METHODS: dict[str, Literal["git", "zip", "direct"]] = {
    "git": "git",
    "zip": "zip",
    "direct": "direct",
}


class SkillsShSource:
    """skills.sh 技能数据源

    通过 skills.sh API 搜索社区贡献的技能。
    作为 GitHub 搜索的补充，提供更结构化的技能索引。
    """

    @property
    def source_name(self) -> str:
        return "skills_sh"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        try:
            async with create_httpx_client(timeout=SKILLS_SH_API_TIMEOUT) as client:
                resp = await client.get(f"{SKILLS_SH_API_BASE}/api/search", params={"q": query, "limit": limit})
                if resp.status_code != 200:
                    logger.warning(f"skills.sh search returned {resp.status_code}, trying fallback")
                    return await self._search_fallback(client, query, limit)

                data = resp.json()
                return self._parse_search_results(data)

        except httpx.TimeoutException:
            logger.warning("skills.sh search timed out")
            return []
        except Exception as e:
            logger.warning(f"skills.sh search error: {e}")
            return []

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        try:
            async with create_httpx_client(timeout=SKILLS_SH_API_TIMEOUT) as client:
                resp = await client.get(f"{SKILLS_SH_API_BASE}/api/skills/{skill_id}")
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if isinstance(data, dict):
                    return self._item_to_result(data)
                return None
        except Exception as e:
            logger.warning(f"skills.sh get_detail error for {skill_id}: {e}")
            return None

    async def _search_fallback(self, client: httpx.AsyncClient, query: str, limit: int) -> list[SkillSearchResult]:
        """回退搜索：尝试通过 GitHub 搜索 skills 仓库"""
        try:
            resp = await client.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"{query} skill agent SKILL.md",
                    "sort": "stars",
                    "per_page": limit,
                },
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get("items", [])
            if not isinstance(items, list):
                return []

            results: list[SkillSearchResult] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                full_name = str(item.get("full_name", ""))
                results.append(
                    SkillSearchResult(
                        id=full_name,
                        name=str(item.get("name", "")),
                        description=str(item.get("description", "")) or "",
                        source="skills_sh",
                        author=full_name.split("/")[0] if "/" in full_name else "",
                        install_url=str(item.get("clone_url", "")),
                        install_method="git",
                        stars=int(item.get("stargazers_count", 0)),
                        tags=item.get("topics", []) if isinstance(item.get("topics"), list) else [],
                        readme_url=str(item.get("html_url", "")),
                    )
                )
            return results[:limit]

        except Exception as e:
            logger.warning(f"skills.sh fallback search error: {e}")
            return []

    def _parse_search_results(self, data: dict[str, object] | list[dict[str, object]]) -> list[SkillSearchResult]:
        items: list[dict[str, object]]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            raw = data.get("results", data.get("skills", data.get("items", [])))
            items = raw if isinstance(raw, list) else []
        else:
            return []

        return [self._item_to_result(item) for item in items if isinstance(item, dict)]

    def _item_to_result(self, item: dict[str, object]) -> SkillSearchResult:
        skill_id = str(item.get("id", item.get("name", item.get("slug", ""))))
        name = str(item.get("name", skill_id))

        repo_url = str(item.get("repo_url", item.get("url", item.get("install_url", ""))))
        subdirectory = str(item.get("subdirectory")) if item.get("subdirectory") else None

        if not repo_url:
            repo_url, subdirectory = self._derive_github_url(skill_id, item)

        install_method = _VALID_INSTALL_METHODS.get(
            str(item.get("install_method", "")), "zip" if repo_url.endswith(".zip") else "git"
        )

        tags_raw = item.get("tags", item.get("categories", []))
        tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

        repo_source = str(item.get("source", ""))
        author = str(item.get("author", item.get("owner", "")))
        if not author and repo_source:
            author = repo_source.split("/")[0]

        return SkillSearchResult(
            id=skill_id,
            name=name,
            description=str(item.get("description", "")),
            source="skills_sh",
            author=author,
            install_url=repo_url,
            install_method=install_method,
            version=str(item.get("version", "")),
            stars=int(item.get("stars", item.get("downloads", 0))),
            downloads=int(item.get("downloads", item.get("installs", 0))),
            tags=tags,
            readme_url=str(item.get("readme_url", item.get("url", ""))),
            subdirectory=subdirectory,
        )

    @staticmethod
    def _derive_github_url(skill_id: str, item: dict[str, object]) -> tuple[str, str | None]:
        """Derive GitHub clone URL and subdirectory from skills.sh id/source.

        skills.sh id format: "{owner}/{repo}/{skill-name}"
        skills.sh source field: "{owner}/{repo}"
        """
        repo_source = str(item.get("source", ""))
        if repo_source and "/" in repo_source:
            owner_repo = repo_source
        else:
            parts = skill_id.split("/")
            if len(parts) >= 2:
                owner_repo = f"{parts[0]}/{parts[1]}"
            else:
                return "", None

        clone_url = f"https://github.com/{owner_repo}.git"

        skill_name = str(item.get("skillId", item.get("name", "")))
        if not skill_name:
            parts = skill_id.split("/")
            skill_name = parts[-1] if len(parts) >= 3 else ""

        subdirectory = skill_name if skill_name else None
        return clone_url, subdirectory
