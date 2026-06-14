"""ModelScope 技能搜索源

通过魔搭社区公开 OpenAPI 搜索 MCP 技能（80K+），无需认证即可搜索。
API: GET https://www.modelscope.cn/openapi/v1/skills?search=&page_number=&page_size=

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- ModelScopeSource: class — ModelScope Skill Source

[POS]
Provides ModelScopeSource.
"""

from __future__ import annotations

import logging
import urllib.parse

import httpx

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.modelscope.cn"
_SEARCH_PATH = "/openapi/v1/skills"
_TIMEOUT = 15.0
_MAX_PAGE_SIZE = 100


class ModelScopeSource:
    """魔搭社区技能数据源

    通过 ModelScope OpenAPI 搜索中国最大的 MCP 技能库。
    搜索无需认证，结果包含 install_command 字段。
    """

    @property
    def source_name(self) -> str:
        return "modelscope"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        page_size = max(1, min(limit, _MAX_PAGE_SIZE))
        params: dict[str, str | int] = {"page_number": 1, "page_size": page_size}
        if query.strip():
            params["search"] = query.strip()

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE_URL}{_SEARCH_PATH}", params=params)
                if resp.status_code != 200:
                    logger.warning("ModelScope search returned %d", resp.status_code)
                    return []
                body = resp.json()
        except httpx.TimeoutException:
            logger.warning("ModelScope search timed out")
            return []
        except Exception as e:
            logger.warning("ModelScope search error: %s", e)
            return []

        if not isinstance(body, dict) or not body.get("success", True):
            return []

        data = body.get("data")
        if not isinstance(data, dict):
            return []

        items = data.get("skills", [])
        if not isinstance(items, list):
            return []

        results: list[SkillSearchResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_item(item)
            if parsed:
                results.append(parsed)

        return results[:limit]

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        detail_path = f"{_SEARCH_PATH}/{urllib.parse.quote(skill_id, safe='@/')}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE_URL}{detail_path}")
                if resp.status_code != 200:
                    return None
                body = resp.json()
        except Exception as e:
            logger.warning("ModelScope get_detail error for %s: %s", skill_id, e)
            return None

        if not isinstance(body, dict) or not body.get("success", True):
            return None

        data = body.get("data")
        if not isinstance(data, dict):
            return None

        return self._parse_item(data)

    def _parse_item(self, item: dict[str, object]) -> SkillSearchResult | None:
        skill_id = _str(item.get("id"))
        if not skill_id:
            return None

        name = _str(item.get("display_name")) or skill_id
        description = self._localized(item, "description") or _str(item.get("description"))

        developer = _str(item.get("developer")) or _str(item.get("owner"))
        if not developer and skill_id.startswith("@") and "/" in skill_id:
            developer = skill_id.split("/", 1)[0].lstrip("@")

        quoted_id = urllib.parse.quote(skill_id, safe="@/")
        source_url = f"https://modelscope.cn/skills/{quoted_id}"

        downloads = _int(item.get("downloads"))
        views = _int(item.get("view_count"))

        tags: list[str] = []
        category = self._localized(item, "category") or _str(item.get("category"))
        if category:
            tags.append(category)

        return SkillSearchResult(
            id=skill_id,
            name=name,
            description=description,
            source="modelscope",
            author=developer,
            install_url=source_url,
            install_method="direct",
            version=_str(item.get("version")),
            stars=views,
            downloads=downloads,
            tags=tags,
            readme_url=source_url,
        )

    @staticmethod
    def _localized(item: dict[str, object], field: str) -> str:
        """Extract localized text, preferring zh then en."""
        locales = item.get("locales")
        if not isinstance(locales, dict):
            return ""
        for lang in ("zh", "en"):
            entry = locales.get(lang)
            if isinstance(entry, dict):
                text = _str(entry.get(field))
                if text:
                    return text
        return ""


def _str(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
