"""Volcengine Doubao Web Search adapter (Search Infinity / Torchlight API).

Uses API Key auth against the official feedcoop search endpoint.
Reference: bytedance/agentkit-samples skills/byted-web-search/scripts/web_search.py

[INPUT]
- infra.tls_compat::create_httpx_client (POS: TLS-compatible httpx client factory)
- web_search.common::SearchResult (POS: Unified search result dataclass)

[OUTPUT]
- VolcengineDoubaoSearch: native search client for slug volcengine_doubao

[POS]
Native search provider adapter alongside litellm_search.py (not a separate toolkit).
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client
from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.error_handling import (
    build_search_error_context,
)
from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError

logger = logging.getLogger(__name__)

_API_KEY_URL = "https://open.feedcoopapi.com/search_api/web_search"
_TRAFFIC_TAG_HEADER = "X-Traffic-Tag"
_TRAFFIC_TAG_VALUE = "myrm_web_search"
_MAX_WEB_COUNT = 50


class VolcengineDoubaoSearch:
    """Volcengine Search Infinity client (API Key authentication)."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: int | None = 20,
        api_base: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("volcengine_doubao search requires api_key")
        self.api_key = api_key.strip()
        self.api_base = (api_base or _API_KEY_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or 20

    async def search(self, query: str, num_results: int = 5, **kwargs: object) -> list[SearchResult]:
        count = min(max(num_results, 1), _MAX_WEB_COUNT)
        body = self._build_body(query=query, count=count, extra=kwargs)
        payload = await self._post_search(body)
        return self._parse_results(payload)

    def _build_body(self, *, query: str, count: int, extra: dict[str, object]) -> dict[str, object]:
        search_type = str(extra.get("search_type") or extra.get("SearchType") or "web")
        body: dict[str, object] = {
            "Query": query,
            "SearchType": search_type,
            "Count": count,
        }
        if search_type == "web":
            need_summary = extra.get("need_summary", extra.get("NeedSummary", True))
            body["NeedSummary"] = bool(need_summary)

        time_range = extra.get("time_range") or extra.get("TimeRange")
        if isinstance(time_range, str) and time_range.strip():
            body["TimeRange"] = time_range.strip()

        auth_level = extra.get("auth_level") or extra.get("AuthInfoLevel")
        if isinstance(auth_level, int) and auth_level > 0:
            body["Filter"] = {"AuthInfoLevel": auth_level}

        query_rewrite = extra.get("query_rewrite") or extra.get("QueryRewrite")
        if query_rewrite is True:
            body["QueryControl"] = {"QueryRewrite": True}

        return body

    async def _post_search(self, body: dict[str, object]) -> dict[str, object]:
        headers = {
            "Content-Type": "application/json",
            _TRAFFIC_TAG_HEADER: _TRAFFIC_TAG_VALUE,
            "Authorization": f"Bearer {self.api_key}",
        }
        body_str = json.dumps(body, ensure_ascii=False)
        try:
            async with create_httpx_client(timeout=float(self.timeout_seconds)) as client:
                response = await client.post(
                    self.api_base,
                    headers=headers,
                    content=body_str.encode("utf-8"),
                )
        except httpx.TimeoutException as exc:
            ctx = build_search_error_context(
                exc,
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
            )
            raise SearchAPIError("Volcengine search request timed out", context=ctx) from exc
        except httpx.HTTPError as exc:
            ctx = build_search_error_context(
                exc,
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
            )
            raise SearchAPIError(f"Volcengine search HTTP error: {exc}", context=ctx) from exc

        if response.status_code == 429:
            ctx = build_search_error_context(
                Exception(f"HTTP 429 rate limit: {response.text[:500]}"),
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
                error_code="429",
            )
            ctx = replace(ctx, status_code=429)
            raise SearchAPIError("Volcengine search rate limited (429)", context=ctx)

        if response.status_code >= 400:
            ctx = build_search_error_context(
                Exception(response.text[:500]),
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
                error_code=str(response.status_code),
            )
            raise SearchAPIError(
                f"Volcengine search failed with HTTP {response.status_code}",
                context=ctx,
            )

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            ctx = build_search_error_context(
                exc,
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
            )
            raise SearchAPIError("Volcengine search returned invalid JSON", context=ctx) from exc

        if not isinstance(data, dict):
            ctx = build_search_error_context(
                Exception("non-object JSON"),
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
            )
            raise SearchAPIError("Volcengine search returned unexpected payload", context=ctx)

        error_meta = data.get("ResponseMetadata")
        if isinstance(error_meta, dict):
            error = error_meta.get("Error")
        else:
            error = None
        if isinstance(error, dict):
            code = str(error.get("Code", ""))
            message = str(error.get("Message", ""))
            ctx = build_search_error_context(
                Exception(f"API Error [{code}]: {message}"),
                query=str(body.get("Query", "")),
                provider="volcengine_doubao",
                attempt_index=0,
                error_code=code or None,
            )
            raise SearchAPIError(f"Volcengine search API error [{code}]: {message}", context=ctx)

        return data

    def _parse_results(self, data: dict[str, object]) -> list[SearchResult]:
        result_block = data.get("Result")
        if not isinstance(result_block, dict):
            return []

        web_results = result_block.get("WebResults")
        if not isinstance(web_results, list):
            return []

        parsed: list[SearchResult] = []
        for item in web_results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("Title") or "Untitled")
            link = str(item.get("Url") or "")
            snippet = str(item.get("Snippet") or "")
            summary_raw = item.get("Summary")
            summary = str(summary_raw).strip() if summary_raw else None
            if not snippet and summary:
                snippet = summary[:500]
            publish_time = item.get("PublishTime") or item.get("PublishedTime")
            date = str(publish_time).strip() if publish_time else None

            site_name_raw = item.get("SiteName")
            site_name = str(site_name_raw).strip() if site_name_raw else None
            auth_raw = item.get("AuthInfoDes")
            authority_description = str(auth_raw).strip() if auth_raw else None

            parsed.append(
                SearchResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    date=date,
                    summary=summary,
                    site_name=site_name,
                    authority_description=authority_description,
                )
            )
        return parsed
