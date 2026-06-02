"""ClawHub 技能搜索源

通过 clawhub.ai API 搜索和获取技能详情。
ClawHub 是最大的技能生态平台，6 个主流竞品均已接入。

API 端点:
- /api/v1/search — 搜索技能
- /api/v1/skills/{slug} — 获取技能详情
- /api/v1/download — 下载技能 ZIP 包

认证: 可选，通过 CLAWHUB_TOKEN 环境变量配置。

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- ClawHubSource: class — Claw Hub Source

[POS]
Provides ClawHubSource.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

CLAWHUB_API_BASE = "https://clawhub.ai"
CLAWHUB_API_TIMEOUT = 10.0
CLAWHUB_ENRICH_MAX = 5


def _resolve_clawhub_base_url() -> str:
    url = os.environ.get("CLAWHUB_URL", "").strip().rstrip("/")
    return url or CLAWHUB_API_BASE


def _resolve_clawhub_token() -> str | None:
    token = os.environ.get("CLAWHUB_TOKEN", "").strip()
    return token or None


class ClawHubSource:
    """ClawHub 技能数据源

    通过 ClawHub 公共 API 搜索技能，支持详情获取和搜索结果丰富化（stars/downloads）。
    ZIP 下载 URL 用于安装流程。
    """

    def __init__(self) -> None:
        self._base_url = _resolve_clawhub_base_url()
        self._token = _resolve_clawhub_token()
        self._client: httpx.AsyncClient | None = None

    @property
    def source_name(self) -> str:
        return "clawhub"

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=CLAWHUB_API_TIMEOUT, headers=self._build_headers())
        return self._client

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        try:
            client = self._get_client()
            resp = await client.get(
                f"{self._base_url}/api/v1/search", params={"q": query.strip() or "*", "limit": str(limit)}
            )
            if resp.status_code != 200:
                logger.warning("ClawHub search returned %d", resp.status_code)
                return []

            data = resp.json()
            results = self._parse_search_response(data)

            if results:
                await self._enrich_results(client, results[:CLAWHUB_ENRICH_MAX])

            return results[:limit]

        except httpx.TimeoutException:
            logger.warning("ClawHub search timed out")
            return []
        except Exception as e:
            logger.warning("ClawHub search error: %s", e)
            return []

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        slug = skill_id.strip()
        if not slug:
            return None

        try:
            client = self._get_client()
            resp = await client.get(f"{self._base_url}/api/v1/skills/{_url_encode_slug(slug)}")
            if resp.status_code != 200:
                return None

            data = resp.json()
            return self._parse_detail_response(slug, data)

        except Exception as e:
            logger.warning("ClawHub get_detail error for %s: %s", skill_id, e)
            return None

    def _parse_search_response(self, data: dict[str, object] | list[dict[str, object]]) -> list[SkillSearchResult]:
        raw_results: list[dict[str, object]]

        if isinstance(data, list):
            raw_results = data
        elif isinstance(data, dict):
            results_field = data.get("results", [])
            raw_results = results_field if isinstance(results_field, list) else []
        else:
            return []

        return [
            self._search_item_to_result(item) for item in raw_results if isinstance(item, dict) and item.get("slug")
        ]

    def _search_item_to_result(self, item: dict[str, object]) -> SkillSearchResult:
        slug = str(item.get("slug", ""))
        display_name = str(item.get("displayName", item.get("display_name", slug)))
        summary = str(item.get("summary", item.get("description", "")))
        version = str(item.get("version", ""))

        download_url = f"{self._base_url}/api/v1/download?slug={_url_encode_slug(slug)}"

        return SkillSearchResult(
            id=slug,
            name=display_name,
            description=summary,
            source="clawhub",
            author=_extract_owner(slug),
            install_url=download_url,
            install_method="zip",
            version=version,
            stars=_safe_int(item.get("score", 0)),
        )

    def _parse_detail_response(self, slug: str, data: dict[str, object]) -> SkillSearchResult | None:
        skill = data.get("skill")
        if not isinstance(skill, dict):
            return None

        display_name = str(skill.get("displayName", skill.get("display_name", slug)))
        summary = str(skill.get("summary", ""))

        latest_version = data.get("latestVersion")
        version = ""
        if isinstance(latest_version, dict):
            version = str(latest_version.get("version", ""))

        stats = skill.get("stats")
        stars = 0
        downloads = 0
        if isinstance(stats, dict):
            stars = _safe_int(stats.get("stars", 0))
            downloads = _safe_int(stats.get("downloads", stats.get("installsCurrent", 0)))

        owner_data = data.get("owner")
        author = ""
        if isinstance(owner_data, dict):
            author = str(owner_data.get("handle", owner_data.get("displayName", "")))
        if not author:
            author = _extract_owner(slug)

        tags_raw = skill.get("tags")
        tags: list[str] = []
        if isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        elif isinstance(tags_raw, dict):
            tags = [str(v) for v in tags_raw.values()]

        download_url = f"{self._base_url}/api/v1/download?slug={_url_encode_slug(slug)}"

        return SkillSearchResult(
            id=slug,
            name=display_name,
            description=summary,
            source="clawhub",
            author=author,
            install_url=download_url,
            install_method="zip",
            version=version,
            stars=stars,
            downloads=downloads,
            tags=tags,
        )

    async def _enrich_results(self, client: httpx.AsyncClient, results: list[SkillSearchResult]) -> None:
        """Enrich top-N search results with detail data (stars, downloads, author).

        Best-effort: failures silently keep original values.
        """

        async def _fetch_detail(idx: int, slug: str) -> tuple[int, dict[str, object] | None]:
            try:
                resp = await client.get(f"{self._base_url}/api/v1/skills/{_url_encode_slug(slug)}")
                if resp.status_code == 200:
                    return idx, resp.json()
            except Exception:
                pass
            return idx, None

        tasks = [_fetch_detail(i, r.id) for i, r in enumerate(results)]
        done = await asyncio.gather(*tasks, return_exceptions=True)

        for item in done:
            if isinstance(item, BaseException):
                continue
            idx, data = item
            if data is None or not isinstance(data, dict):
                continue

            detail = self._parse_detail_response(results[idx].id, data)
            if detail:
                results[idx] = detail


def _url_encode_slug(slug: str) -> str:
    from urllib.parse import quote

    return quote(slug, safe="")


def _extract_owner(slug: str) -> str:
    return slug.split("/")[0] if "/" in slug else ""


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
