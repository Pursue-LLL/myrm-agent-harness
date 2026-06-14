"""阿里云灵积 AgentExplorer 技能搜索源

通过阿里云 AgentExplorer REST API (ACS3-HMAC-SHA256 签名) 搜索技能。
需要环境变量 ALIBABA_CLOUD_ACCESS_KEY_ID 和 ALIBABA_CLOUD_ACCESS_KEY_SECRET。
当凭据不可用时静默禁用，不影响其他源正常工作。

API:
  GET /openapi/skills?keyword=&maxResults=  — SearchSkills
  GET /openapi/skills/{skillName}           — GetSkillContent

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult

[OUTPUT]
- AliyunSource: class — Aliyun AgentExplorer Skill Source

[POS]
Provides AliyunSource.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

_ENDPOINT = os.environ.get(
    "ALIYUN_AGENTEXPLORER_ENDPOINT",
    "agentexplorer.aliyuncs.com",
)
_API_VERSION = "2026-03-17"
_DETAIL_URL_BASE = "https://api.aliyun.com/agentexplorer/skills"
_TIMEOUT = 15.0
_UPSTREAM_PAGE_SIZE = 100

_CRED_ENV_KEYS = (
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
)


class AliyunSource:
    """阿里云灵积 AgentExplorer 技能数据源

    使用阿里云 SDK 签名请求。凭据不可用时 search/get_detail 返回空结果。
    """

    @property
    def source_name(self) -> str:
        return "aliyun"

    def _credentials_available(self) -> bool:
        return all(os.environ.get(k) for k in _CRED_ENV_KEYS)

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        if not self._credentials_available():
            return []

        max_results = max(1, min(limit, _UPSTREAM_PAGE_SIZE))
        params: dict[str, Any] = {"maxResults": max_results}
        if query.strip():
            params["keyword"] = query.strip()

        try:
            resp_body = await self._call_api(
                action="SearchSkills",
                pathname="/openapi/skills",
                query=params,
            )
        except Exception as e:
            logger.warning("Aliyun SearchSkills error: %s", e)
            return []

        items = _extract_skill_items(resp_body)
        results: list[SkillSearchResult] = []
        for item in items:
            parsed = _to_search_result(item)
            if parsed:
                results.append(parsed)

        return results[:limit]

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        if not self._credentials_available():
            return None

        pathname = f"/openapi/skills/{quote(skill_id, safe='')}"
        try:
            resp_body = await self._call_api(
                action="GetSkillContent",
                pathname=pathname,
            )
        except Exception as e:
            logger.warning("Aliyun GetSkillContent error for %s: %s", skill_id, e)
            return None

        if not isinstance(resp_body, dict):
            return None
        return _to_search_result(resp_body)

    async def _call_api(
        self,
        action: str,
        pathname: str,
        method: str = "GET",
        query: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a signed request via alibabacloud-tea-openapi SDK."""
        try:
            from alibabacloud_credentials.client import Client as CredentialClient
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_openapi.client import Client as OpenApiClient
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            logger.warning("Aliyun SDK not installed: %s", exc)
            raise

        config = open_api_models.Config(credential=CredentialClient())
        config.endpoint = _ENDPOINT
        config.signature_algorithm = "ACS3-HMAC-SHA256"
        client = OpenApiClient(config)

        params = open_api_models.Params(
            action=action,
            version=_API_VERSION,
            protocol="HTTPS",
            pathname=pathname,
            method=method,
            auth_type="AK",
            style="ROA",
            req_body_type="json",
            body_type="json",
        )

        runtime = util_models.RuntimeOptions(
            read_timeout=int(_TIMEOUT * 1000),
            connect_timeout=int(_TIMEOUT * 1000),
            autoretry=False,
        )

        string_query = {k: str(v) for k, v in (query or {}).items() if v is not None}
        request = open_api_models.OpenApiRequest(query=string_query)
        resp = await client.do_request_async(params, request, runtime)
        return _unwrap(resp)


def _unwrap(resp: Any) -> Any:
    if isinstance(resp, dict) and "body" in resp:
        return resp["body"]
    return resp


def _extract_skill_items(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return [v for v in body["data"] if isinstance(v, dict)]
    return []


def _to_search_result(item: dict[str, Any]) -> SkillSearchResult | None:
    skill_name = _str(item.get("skillName"))
    display_name = _str(item.get("displayName"))
    if not skill_name and not display_name:
        return None

    slug = skill_name or display_name
    detail_url = f"{_DETAIL_URL_BASE}/{quote(slug, safe='')}"

    installs = _opt_int(item.get("installCount")) or 0
    likes = _opt_int(item.get("likeCount")) or 0

    tags: list[str] = []
    category = _str(item.get("categoryName"))
    sub_category = _str(item.get("subCategoryName"))
    if category:
        tags.append(category)
    if sub_category and sub_category != category:
        tags.append(sub_category)

    return SkillSearchResult(
        id=slug,
        name=display_name or skill_name,
        description=_str(item.get("description")),
        source="aliyun",
        author=_str(item.get("provider")) or _str(item.get("owner")),
        install_url=detail_url,
        install_method="direct",
        version=_str(item.get("version")),
        stars=likes,
        downloads=installs,
        tags=tags,
        readme_url=detail_url,
    )


def _str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
