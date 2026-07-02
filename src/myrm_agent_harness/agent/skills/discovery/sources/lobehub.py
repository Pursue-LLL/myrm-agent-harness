"""LobeHub 技能搜索源

LobeHub 是最大的开源 AI Agent 模板聚合平台（14,500+ agents）。
Agent 本质是 system-prompt 模板，搜索到后按 SKILL.md 格式返回。

数据源: chat-agents.lobehub.com (GitHub: lobehub/lobe-chat-agents)

[INPUT]
- backends.skills.discovery_protocols::SkillSearchResult (POS: SkillBackend SkillBackend SkillDiscoveryBackend)

[OUTPUT]
- LobeHubSource: class — Lobe Hub Source

[POS]
Provides LobeHubSource.
"""

from __future__ import annotations

import logging

import httpx

from myrm_agent_harness.infra.tls_compat import create_httpx_client

from myrm_agent_harness.backends.skills.discovery_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

LOBEHUB_INDEX_URL = "https://chat-agents.lobehub.com/index.json"
LOBEHUB_AGENT_URL = "https://chat-agents.lobehub.com/{agent_id}.json"
LOBEHUB_TIMEOUT = 15.0
LOBEHUB_INDEX_CACHE_TTL = 3600


class LobeHubSource:
    """LobeHub Agent 模板数据源

    通过 LobeHub 公开索引搜索 Agent 模板，匹配后返回 SkillSearchResult。
    install_method 为 "direct"，因为 LobeHub agent 是纯文本模板，
    由安装流程将 system prompt 转化为 SKILL.md 写入本地。
    """

    def __init__(self) -> None:
        self._index_cache: list[dict[str, object]] | None = None
        self._cache_ts: float = 0
        self._client: httpx.AsyncClient | None = None

    @property
    def source_name(self) -> str:
        return "lobehub"

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        agents = await self._load_index()
        if not agents:
            return []

        query_lower = query.lower().strip()
        if not query_lower:
            return [self._agent_to_result(a) for a in agents[:limit]]

        results: list[SkillSearchResult] = []
        for agent in agents:
            meta = agent.get("meta", agent) if isinstance(agent, dict) else {}
            if not isinstance(meta, dict):
                continue

            title = str(meta.get("title", "")).lower()
            desc = str(meta.get("description", "")).lower()
            tags = meta.get("tags", [])
            tag_str = " ".join(str(t) for t in tags) if isinstance(tags, list) else ""

            if query_lower in title or query_lower in desc or query_lower in tag_str.lower():
                results.append(self._agent_to_result(agent))
                if len(results) >= limit:
                    break

        return results

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = create_httpx_client(timeout=LOBEHUB_TIMEOUT)
        return self._client

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        agent_id = skill_id.removeprefix("lobehub/") if skill_id.startswith("lobehub/") else skill_id

        try:
            client = self._get_client()
            resp = await client.get(LOBEHUB_AGENT_URL.format(agent_id=agent_id))
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict):
                return self._agent_detail_to_result(agent_id, data)
            return None
        except Exception as e:
            logger.warning("LobeHub get_detail error for %s: %s", skill_id, e)
            return None

    async def _load_index(self) -> list[dict[str, object]]:
        """Load the LobeHub agent index with in-memory cache."""
        import time

        now = time.time()
        if self._index_cache is not None and (now - self._cache_ts) < LOBEHUB_INDEX_CACHE_TTL:
            return self._index_cache

        try:
            client = self._get_client()
            resp = await client.get(LOBEHUB_INDEX_URL)
            if resp.status_code != 200:
                logger.warning("LobeHub index returned %d", resp.status_code)
                return self._index_cache or []

            data = resp.json()
            agents: list[dict[str, object]]
            if isinstance(data, list):
                agents = data
            elif isinstance(data, dict):
                raw = data.get("agents", data.get("items", []))
                agents = raw if isinstance(raw, list) else []
            else:
                agents = []

            self._index_cache = agents
            self._cache_ts = now
            return agents

        except Exception as e:
            logger.warning("LobeHub index fetch error: %s", e)
            return self._index_cache or []

    def _agent_to_result(self, agent: object) -> SkillSearchResult:
        if not isinstance(agent, dict):
            return SkillSearchResult(
                id="unknown",
                name="unknown",
                description="",
                source="lobehub",
                author="",
                install_url="",
                install_method="direct",
            )

        meta = agent.get("meta", agent)
        if not isinstance(meta, dict):
            meta = agent

        identifier = str(agent.get("identifier", meta.get("title", "unknown")))
        title = str(meta.get("title", identifier))
        desc = str(meta.get("description", ""))[:200]
        author = str(agent.get("author", meta.get("author", "")))

        tags_raw = meta.get("tags", [])
        tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

        return SkillSearchResult(
            id=f"lobehub/{identifier}",
            name=title,
            description=desc,
            source="lobehub",
            author=author,
            install_url=LOBEHUB_AGENT_URL.format(agent_id=identifier),
            install_method="direct",
            tags=tags,
        )

    def _agent_detail_to_result(self, agent_id: str, data: dict[str, object]) -> SkillSearchResult:
        meta = data.get("meta", data)
        if not isinstance(meta, dict):
            meta = data

        title = str(meta.get("title", agent_id))
        desc = str(meta.get("description", ""))
        author = str(data.get("author", meta.get("author", "")))

        tags_raw = meta.get("tags", [])
        tags = [str(t) for t in tags_raw] if isinstance(tags_raw, list) else []

        return SkillSearchResult(
            id=f"lobehub/{agent_id}",
            name=title,
            description=desc,
            source="lobehub",
            author=author,
            install_url=LOBEHUB_AGENT_URL.format(agent_id=agent_id),
            install_method="direct",
            tags=tags,
        )
