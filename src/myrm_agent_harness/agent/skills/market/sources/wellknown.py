""".well-known/skills/ endpoint skill source.

Discovers skills from domains exposing the standard /.well-known/skills/index.json endpoint.
Any website or enterprise internal server can publish skills by serving this JSON.

[INPUT]
- backends.skills.market_protocols::SkillSearchResult

[OUTPUT]
- WellKnownSkillSource: class — Well-Known Skills Endpoint Source

[POS]
Provides WellKnownSkillSource.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

_INDEX_PATH = "/.well-known/skills/index.json"
_REQUEST_TIMEOUT = 10.0


class WellKnownSkillSource:
    """Discover skills from a domain's /.well-known/skills/index.json endpoint.

    Protocol: HTTP GET <base_url>/.well-known/skills/index.json
    Expected response: {"skills": [{"name": ..., "description": ..., ...}, ...]}

    Designed for enterprise internal skill registries and third-party service providers.
    """

    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url.rstrip("/"))
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid base_url: must include scheme and host: {base_url}")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._index_url = f"{self._base_url}{_INDEX_PATH}"

    @property
    def source_name(self) -> str:
        return f"well-known:{self._base_url}"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        """Search skills by keyword matching against the index."""
        index = await self._fetch_index()
        if not index:
            return []

        query_lower = query.lower().strip()
        results: list[SkillSearchResult] = []

        for entry in index:
            name = entry.get("name", "")
            description = entry.get("description", "")
            tags = entry.get("tags", [])

            if query_lower and not self._matches(query_lower, name, description, tags):
                continue

            results.append(self._to_search_result(entry))
            if len(results) >= limit:
                break

        return results

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        """Get skill detail by ID (format: well-known:<base_url>/<skill_name>)."""
        prefix = f"well-known:{self._base_url}/"
        if not skill_id.startswith(prefix):
            return None

        skill_name = skill_id[len(prefix) :]
        index = await self._fetch_index()
        if not index:
            return None

        for entry in index:
            if entry.get("name", "") == skill_name:
                return self._to_search_result(entry)
        return None

    async def probe(self) -> tuple[bool, int]:
        """Probe the endpoint for reachability and return (reachable, skill_count)."""
        index = await self._fetch_index()
        if index is None:
            return False, 0
        return True, len(index)

    async def _fetch_index(self) -> list[dict[str, object]] | None:
        """Fetch and parse the index.json from the well-known endpoint."""
        try:
            async with create_httpx_client(timeout=_REQUEST_TIMEOUT) as client:
                resp = await client.get(self._index_url)
                if resp.status_code != 200:
                    logger.debug("Well-known index returned %d: %s", resp.status_code, self._index_url)
                    return None

                data = resp.json()
                skills = data.get("skills", [])
                if not isinstance(skills, list):
                    logger.warning("Well-known index 'skills' field is not a list: %s", self._index_url)
                    return None
                return skills
        except httpx.TimeoutException:
            logger.debug("Well-known index timed out: %s", self._index_url)
            return None
        except Exception as e:
            logger.debug("Well-known index fetch failed: %s — %s", self._index_url, e)
            return None

    def _to_search_result(self, entry: dict[str, object]) -> SkillSearchResult:
        name = str(entry.get("name", ""))
        install_url = str(entry.get("install_url", ""))
        if not install_url:
            install_url = f"{self._base_url}/.well-known/skills/{name}/SKILL.md"

        raw_pkg = str(entry.get("package_type", entry.get("packageType", "")))
        pkg_type = "agent_plugin" if raw_pkg == "agent_plugin" else "skill"
        keywords = [str(k) for k in entry.get("keywords", []) if isinstance(k, str)]

        return SkillSearchResult(
            id=f"well-known:{self._base_url}/{name}",
            name=name,
            description=str(entry.get("description", "")),
            source=f"well-known:{self._base_url}",
            author=str(entry.get("author", "")),
            install_url=install_url,
            install_method="git" if install_url.endswith(".git") else "zip",
            version=str(entry.get("version", "")),
            stars=int(entry.get("stars", 0) or 0),
            downloads=int(entry.get("downloads", 0) or 0),
            tags=list(entry.get("tags", []) or []),
            readme_url=str(entry.get("readme_url", "")) or None,
            package_type=pkg_type,
            keywords=keywords,
        )

    @staticmethod
    def _matches(query: str, name: str, description: str, tags: list[str]) -> bool:
        searchable = f"{name} {description} {' '.join(tags)}".lower()
        return all(term in searchable for term in query.split())
