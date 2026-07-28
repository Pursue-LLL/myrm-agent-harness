"""技能搜索引擎

复用 retriever/bm25_retrieval 的 BM25Retriever 和 preprocess_text,
为技能列表提供 BM25 和 Regex 搜索能力.

构建一次索引, 支持多次查询. 技能列表在会话内稳定, 无需重建.

多语言搜索: 通过 Prompt 引导 LLM 传入 "概念/翻译/同义词" 格式, 利用 jieba 分词的
词汇匹配能力. 特殊查询 "*" / ".*" 可返回所有技能, 用于 Fallback 兜底.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever

from .query_expansion import QueryExpander
from .types import SKILL_SEARCH_TOP_K, SkillSearchResult

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

DEFAULT_BM25_MIN_RELEVANCE_SCORE = 0.5
MCP_SKILL_TOOL_INDEX_THRESHOLD = 3
MCP_TOOL_SHORT_DESC_MAX_CHARS = 80


def _truncate_tool_desc(description: str, max_chars: int = MCP_TOOL_SHORT_DESC_MAX_CHARS) -> str:
    text = " ".join((description or "").split())
    if not text:
        return ""
    match = re.search(r"[。.\n!?]", text)
    if match and match.end() <= max_chars:
        return text[: match.end()].strip()
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0] if " " in text[:max_chars] else text[:max_chars]
    return clipped.rstrip(",;: ") + "…"


def _build_skill_index_document(skill: SkillMetadata) -> str:
    """Build BM25 index text for a skill; enrich MCP skills with tool-level tokens."""
    base = f"{skill.name.replace('_', ' ')} {skill.description}"
    if not skill.mcp or not skill.mcp.tools:
        return base
    tool_count = len(skill.mcp.tools)
    if tool_count <= MCP_SKILL_TOOL_INDEX_THRESHOLD:
        return base
    tool_schemas = skill.mcp.tool_schemas or {}
    tool_parts: list[str] = []
    for tool_name in skill.mcp.tools:
        schema_entry = tool_schemas.get(tool_name)
        if not isinstance(schema_entry, dict):
            tool_parts.append(tool_name.replace("_", " "))
            continue
        desc_raw = schema_entry.get("description")
        desc = _truncate_tool_desc(str(desc_raw)) if isinstance(desc_raw, str) else ""
        token = tool_name.replace("_", " ")
        tool_parts.append(f"{token} {desc}".strip() if desc else token)
    if not tool_parts:
        return base
    return f"{base} {' '.join(tool_parts)}"


class SkillSearchEngine:
    """技能搜索引擎

    在 agent 初始化时构建 BM25 索引, 支持:
    - BM25 自然语言搜索(中英文, 复用 jieba 分词)
    - Regex 模式匹配搜索
    """

    def __init__(
        self,
        skills: list[SkillMetadata],
        min_relevance_score: float = DEFAULT_BM25_MIN_RELEVANCE_SCORE,
        enable_query_expansion: bool = True,
    ) -> None:
        """初始化BM25搜索引擎

        Args:
            skills: 技能列表
            min_relevance_score: BM25 最低相关性阈值（anti-noise）。rank_bm25 弱匹配可为负分；
                仅返回 score >= 阈值的命中。强相关命中典型区间 [0, 10]。
            enable_query_expansion: 是否启用查询扩展（同义词、拼写纠正）
        """
        self._skills = list(skills)
        self._min_relevance_score = min_relevance_score
        self._enable_expansion = enable_query_expansion
        self._expander = QueryExpander() if enable_query_expansion else None
        # Normalize skill names: replace underscores with spaces for better tokenization
        documents = [_build_skill_index_document(s) for s in self._skills]
        self._retriever = BM25Retriever(documents)
        logger.info(
            " SkillSearchEngine 已构建(%d 个技能已索引) | BM25阈值: %.2f | 查询扩展: %s",
            len(self._skills),
            self._min_relevance_score,
            "enabled" if enable_query_expansion else "disabled",
        )

    def search_bm25(
        self, query: str, top_k: int = SKILL_SEARCH_TOP_K
    ) -> list[SkillSearchResult]:
        """BM25 自然语言搜索

        特殊查询:
        - "*" 或 "all" 返回所有技能(用于浏览全部)

        [POS]
        Supports query expansion for handling synonyms and typos when enabled.
        """
        if not query.strip():
            return []

        if query.strip() in ["*", "all"]:
            logger.info(
                " [SkillSearch] 特殊查询 '%s' -> 返回全部 %d 个技能",
                query,
                len(self._skills),
            )
            return [
                SkillSearchResult(name=s.name, description=s.description, score=1.0)
                for s in self._skills
            ]

        start_time = time.perf_counter()

        # Query expansion if enabled
        if self._enable_expansion and self._expander:
            expanded_queries = self._expander.expand(query)
            if len(expanded_queries) > 1:
                logger.info(
                    " [QueryExpansion] '%s' -> %d variations",
                    query,
                    len(expanded_queries),
                )
        else:
            expanded_queries = [query]

        # Search with all query variations and merge results
        all_results: dict[int, float] = {}  # idx -> max_score
        for expanded_query in expanded_queries:
            raw_results = self._retriever.search(
                expanded_query, top_k=top_k * 2, only_relevant=False
            )
            for idx, score in raw_results:
                if score >= self._min_relevance_score:
                    all_results[idx] = max(all_results.get(idx, 0.0), score)

        # Sort by score (desc) and skill name (asc) for stable tie-break
        sorted_results = sorted(
            all_results.items(), key=lambda x: (-x[1], self._skills[x[0]].name)
        )[:top_k]
        results = [
            SkillSearchResult(
                name=self._skills[idx].name,
                description=self._skills[idx].description,
                score=score,
            )
            for idx, score in sorted_results
        ]

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Observability: Log search outcome
        if results:
            logger.info(
                " [BM25Search] 查询 '%s' | 结果数: %d | Top-1: %s (分数: %.2f) | 耗时: %.2fms",
                query,
                len(results),
                results[0].name,
                results[0].score,
                elapsed_ms,
            )
        else:
            logger.warning(
                " [BM25Search] 查询 '%s' | 无结果 (所有分数 < %.2f) | 耗时: %.2fms",
                query,
                self._min_relevance_score,
                elapsed_ms,
            )

        return results

    def search_regex(
        self, pattern: str, top_k: int = SKILL_SEARCH_TOP_K
    ) -> list[SkillSearchResult]:
        """Regex 模式匹配搜索

        特殊模式:
        - ".*" 或 "^.*$" 返回所有技能(用于浏览全部)
        """
        if not pattern.strip():
            return []

        if pattern.strip() in [".*", "^.*$", ".+", "^.+$"]:
            logger.info(
                " [SkillSearch] 特殊模式 '%s' -> 返回全部 %d 个技能",
                pattern,
                len(self._skills),
            )
            return [
                SkillSearchResult(name=s.name, description=s.description, score=1.0)
                for s in self._skills[:top_k]
            ]

        start_time = time.perf_counter()
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            logger.warning("Invalid regex pattern %r: %s", pattern, e)
            return []

        results: list[SkillSearchResult] = []
        for skill in self._skills:
            text = f"{skill.name} {skill.description}"
            if regex.search(text):
                results.append(
                    SkillSearchResult(
                        name=skill.name, description=skill.description, score=1.0
                    )
                )
                if len(results) >= top_k:
                    break

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            " [RegexSearch] 模式 '%s' | 结果数: %d | 耗时: %.2fms",
            pattern,
            len(results),
            elapsed_ms,
        )

        return results
