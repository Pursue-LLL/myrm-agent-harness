"""GitHub code search fast-path.

Direct search via GitHub REST API (/search/code), providing real production-grade
source code fragments directly to the Agent without requiring extra web fetching turns.
Triggered when SearchIntent.CODE is detected for targeted code/implementation queries.

Returns structured SearchResult list containing repository names, file paths,
programming languages, and exact code snippet fragments with line attributions.

[INPUT]
- web_search.core.common::SearchResult (POS: Unified search result dataclass)

[OUTPUT]
- search_github_code: Async GitHub code search returning SearchResult list or None
- build_github_code_query: Helper to sanitize and normalize code search query

[POS]
Domain-specific code search fast-path under providers/. Returns structured SearchResult
list via GitHub REST API; returns None on failure or rate-limit to trigger seamless fallback.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult

logger = logging.getLogger(__name__)

_GITHUB_CODE_SEARCH_API = "https://api.github.com/search/code"
_REQUEST_TIMEOUT = 5.0
_DEFAULT_HEADERS = {
    "Accept": "application/vnd.github.text-match+json",
    "User-Agent": "Myrm-CodeSearch/1.0",
}

_NOISE_TOKENS = {
    "github",
    "code",
    "implementation",
    "source",
    "example",
    "how",
    "to",
    "find",
    "search",
    "实现",
    "源码",
    "代码",
    "开源",
    "仓库",
    "项目",
    "例子",
    "怎么写",
}


def build_github_code_query(keyword: str) -> str:
    """Sanitize and normalize query string for GitHub code search endpoint.

    Extracts core symbols, language qualifiers, and strips natural language conversational noise.
    """
    raw_query = keyword.strip()
    if not raw_query:
        return ""

    tokens = raw_query.split()
    meaningful_tokens: list[str] = []
    lang_qualifier: str | None = None

    lang_map: dict[str, str] = {
        "python": "language:python",
        "rust": "language:rust",
        "go": "language:go",
        "golang": "language:go",
        "typescript": "language:typescript",
        "javascript": "language:javascript",
        "c++": "language:cpp",
        "cpp": "language:cpp",
        "java": "language:java",
        "c#": "language:csharp",
        "csharp": "language:csharp",
    }

    for tok in tokens:
        cleaned = tok.strip(" ,，。:：\"'").lower()
        if cleaned in lang_map and not lang_qualifier:
            lang_qualifier = lang_map[cleaned]
            continue
        if cleaned in _NOISE_TOKENS:
            continue
        meaningful_tokens.append(tok)

    query_parts: list[str] = []
    if meaningful_tokens:
        query_parts.append(" ".join(meaningful_tokens))
    if lang_qualifier:
        query_parts.append(lang_qualifier)

    return " ".join(query_parts).strip() or raw_query


async def search_github_code(
    keyword: str,
    max_results: int = 5,
    *,
    api_token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[SearchResult] | None:
    """Execute GitHub REST code search and return structured code snippets.

    Args:
        keyword: The search query string.
        max_results: Max items to fetch (capped between 1 and 10).
        api_token: Optional GitHub Personal Access Token (defaults to GITHUB_TOKEN env).
        client: Optional httpx.AsyncClient instance for connection reuse or testing.

    Returns:
        List of SearchResult on success, or None on failure/rate-limit (triggers fallback).
    """
    effective_query = build_github_code_query(keyword)
    if not effective_query:
        return None

    count = max(1, min(max_results, 10))
    token = api_token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    headers = dict(_DEFAULT_HEADERS)
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"

    params: dict[str, str | int] = {
        "q": effective_query,
        "per_page": count,
    }

    own_client = client is None
    async_client = client or create_httpx_client(timeout=_REQUEST_TIMEOUT)

    try:
        resp = await async_client.get(_GITHUB_CODE_SEARCH_API, headers=headers, params=params)
        if resp.status_code in (401, 403, 429):
            logger.info("GitHub code search rate limit or auth constraint encountered (status=%s)", resp.status_code)
            return None
        if resp.status_code != 200:
            logger.info("GitHub code search API returned status %s for query '%s'", resp.status_code, effective_query[:40])
            return None

        data = resp.json()
        items = data.get("items")
        if not items or not isinstance(items, list):
            logger.info("GitHub code search returned 0 items for query: %s", effective_query[:40])
            return None

        results: list[SearchResult] = []
        for item in items[:count]:
            if not isinstance(item, dict):
                continue
            repo_info = item.get("repository") if isinstance(item.get("repository"), dict) else {}
            repo_name = str(repo_info.get("full_name") or "unknown/repo")
            file_path = str(item.get("path") or item.get("name") or "unknown_file")
            html_url = str(item.get("html_url") or "")

            snippet_parts: list[str] = [
                f"Repository: {repo_name}",
                f"File: {file_path}",
            ]

            # Extract code text match fragments
            text_matches = item.get("text_matches")
            if isinstance(text_matches, list) and text_matches:
                fragments: list[str] = []
                for match in text_matches:
                    if isinstance(match, dict) and match.get("fragment"):
                        frag = str(match["fragment"]).strip()
                        if frag:
                            fragments.append(frag)
                if fragments:
                    combined_fragments = "\n---\n".join(fragments[:3])
                    snippet_parts.append(f"Code Fragment:\n```\n{combined_fragments}\n```")
            else:
                snippet_parts.append(f"Direct link: {html_url}")

            results.append(
                SearchResult(
                    title=f"{repo_name}: {file_path}",
                    link=html_url,
                    snippet="\n".join(snippet_parts),
                    engines=["github_code"],
                )
            )

        return results if results else None

    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.info("GitHub code search request failed gracefully: %s", type(exc).__name__)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected error during GitHub code search: %s", exc)
        return None
    finally:
        if own_client:
            await async_client.aclose()
