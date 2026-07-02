"""Cloud Reranker Implementation.

Cloud API reranking backend supporting multiple providers:
- LiteLLM-supported providers: Cohere, Jina AI, Voyage AI, etc.
- OpenAI-compatible providers: direct HTTP calls (SiliconFlow, etc.)

[INPUT]
retriever.reranker.base::RerankerService (POS: Reranker contract layer)
retriever.reranker.base::RerankResult (POS: Reranker contract layer)

[OUTPUT]
CloudReranker: Concrete RerankerService backed by cloud APIs via LiteLLM or direct HTTP

[POS]
Cloud reranker backend. Translates the abstract RerankerService interface into real
API calls with support for both LiteLLM-managed and OpenAI-compatible endpoints.

"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import httpx
    from litellm.types.rerank import RerankResponse

from myrm_agent_harness.toolkits.retriever.reranker.base import RerankerService, RerankResult

logger = logging.getLogger(__name__)


class CloudReranker(RerankerService):
    """Cloud端 API 重Sortimplements

     via  LiteLLM 统一Call各种Cloud端重Sort API。
    Support Cohere、Jina AI、Voyage AI、Together AI、SiliconFlow  etc.provides商。

    Example:
        ```python
        #  using  Cohere
        service = CloudReranker(
            model="cohere/rerank-v3.5",
            api_key="xxx"
        )

        #  using  Jina AI
        service = CloudReranker(
            model="jina_ai/jina-reranker-v2-base-multilingual",
            api_key="xxx"
        )

        #  using  Voyage AI
        service = CloudReranker(
            model="voyage/rerank-2",
            api_key="xxx"
        )

        #  using  SiliconFlow
        service = CloudReranker(
            model="siliconflow/BAAI/bge-reranker-v2-m3",
            api_key="sk-xxx",
            api_base="https://api.siliconflow.cn/v1"
        )

        results = await service.rerank(
            query="What is AI?",
            documents=["AI is...", "Machine learning..."],
            top_k=5
        )
        ```
    """

    def __init__(
        self,
        model: str = "cohere/rerank-v3.5",
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        """InitializeCloud端重SortService

        Args:
            model: 模型名称（LiteLLM Format，如 "cohere/rerank-v3.5" or  "jina_ai/jina-reranker-v2-base-multilingual"）
            api_key: API Key
            api_base: custom API 端点（optional）
        """
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._http_client: httpx.AsyncClient | None = None

        logger.info(f" Cloud reranker initialized: {model}")

    async def rerank_pairs(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[float]:
        """批量重Sortoptimizedimplements

        optimizedStrategy:
        1. 按Query分组文档，减少APICall
        2. parallelExecuteAllQuery 重Sort

        性能特性：
        - Scenario：4个Query × 30个文档 = 120个pairs
        - Strategy:按Query分组，4次parallelAPICall
        - 实测：耗时 ~3秒（vs Serial 60+秒，95% 提升）

        Args:
            pairs: (query, doc) 对List

        Returns:
            Each pair  related性分数List
        """
        if not pairs:
            return []

        import asyncio
        import time

        start_time = time.time()

        # 按Query分组文档
        query_docs_map: dict[str, list[tuple[int, str]]] = {}
        for idx, (query, doc) in enumerate(pairs):
            if query not in query_docs_map:
                query_docs_map[query] = []
            query_docs_map[query].append((idx, doc))

        logger.warning(
            f" 批量重Sort: {len(pairs)} pairs → {len(query_docs_map)} Query "
            f"(model: {self._model}, api_base: {self._api_base or 'default'})"
        )

        # parallel is AllQueryCallrerank
        scores = [0.0] * len(pairs)

        async def rerank_query(query: str, doc_pairs: list[tuple[int, str]]):
            """重SortsingleQuery 文档"""
            indices, docs = zip(*doc_pairs, strict=False)
            query_start = time.time()
            results = await self.rerank(query, list(docs), top_k=len(docs))
            query_duration = time.time() - query_start
            logger.warning(f" ↳ Query '{query[:30]}...' 重Sort {len(docs)} 文档，耗时: {query_duration:.2f}s")
            return list(zip(indices, results, strict=False))

        # parallelExecuteAllQuery 重Sort
        tasks = [rerank_query(query, doc_pairs) for query, doc_pairs in query_docs_map.items()]
        all_results = await asyncio.gather(*tasks)

        # MergeResult
        for query_results in all_results:
            for idx, result in query_results:
                scores[idx] = result.score

        total_duration = time.time() - start_time
        logger.warning(f" 批量重SortComplete: 总耗时 {total_duration:.2f}s")

        return scores

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> list[RerankResult]:
        """重Sort文档

        智能路由：
        - OpenAI compatible模型（如 SiliconFlow）： directly  HTTP Call
        - LiteLLM Support 模型： via  LiteLLM Call

        Args:
            query: Querytext
            documents: 文档List
            top_k: Return前 k 个Result，None 表示ReturnAll

        Returns:
            按分数降序排列 重SortResultList

        Raises:
            ImportError: If litellm  not yet 安装
            ValueError: IfParameterInvalid or  API ReturnFormatException
        """
        if not documents:
            return []

        if top_k is None:
            top_k = len(documents)

        # 检测Whether is  OpenAI compatible模型（ need  directly  HTTP Call）
        if self._is_openai_compatible():
            return await self._rerank_openai_compatible(query, documents, top_k)
        else:
            return await self._rerank_litellm(query, documents, top_k)

    def _is_openai_compatible(self) -> bool:
        """检测Whether is  OpenAI compatible模型"""
        # OpenAI compatible 特征： has  api_base 且模型Format特殊
        if not self._api_base:
            return False

        # SiliconFlow  or Other using  openai/ Prefix 模型
        return self._model.startswith("openai/") or "siliconflow" in self._api_base.lower()

    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or Create持久 HTTP Client（Connection池optimized）"""
        if self._http_client is None:
            import httpx

            from myrm_agent_harness.infra.tls_compat import create_httpx_client

            self._http_client = create_httpx_client(
                timeout=60.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
        return self._http_client

    async def aclose(self):
        """Close HTTP ClientConnection"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _rerank_openai_compatible(
        self,
        query: str,
        documents: list[str],
        top_k: int,
    ) -> list[RerankResult]:
        """directly Call OpenAI compatible  rerank API（Connection池optimized）"""
        # Extractreal 模型名（去掉 openai/ Prefix）
        model_name = self._model.replace("openai/", "")

        url = f"{self._api_base}/rerank"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model_name,
            "query": query,
            "documents": documents,
            "top_n": top_k,
        }

        try:
            client = self._get_http_client()
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

            # ParseResponse
            results = []
            for item in data.get("results", []):
                results.append(
                    RerankResult(
                        index=item["index"],
                        score=item["relevance_score"],
                        text=documents[item["index"]],
                    )
                )
            return results

        except Exception as e:
            logger.warning(f"Failed to call OpenAI-compatible rerank API: {type(e).__name__}: {e}")
            raise

    async def _rerank_litellm(
        self,
        query: str,
        documents: list[str],
        top_k: int,
    ) -> list[RerankResult]:
        """via  LiteLLM Call rerank API"""
        try:
            import litellm
        except ImportError as e:
            raise ImportError("litellm is required for CloudReranker. Install with: uv add litellm") from e

        try:
            response = cast(
                "RerankResponse",
                await litellm.arerank(
                    model=self._model,
                    query=query,
                    documents=list(documents),
                    top_n=top_k,
                    api_key=self._api_key,
                    api_base=self._api_base,
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to call LiteLLM rerank for model {self._model}: {type(e).__name__}: {e}")
            raise

        if not response.results:
            logger.warning(f"LiteLLM rerank returned empty results for model {self._model}")
            return []

        try:
            return [
                RerankResult(
                    index=item["index"],
                    score=item["relevance_score"],
                    text=documents[item["index"]],
                )
                for item in response.results
            ]
        except (KeyError, IndexError, TypeError) as e:
            error_msg = f"Unexpected response format from LiteLLM rerank: {type(e).__name__}: {e}"
            logger.warning(error_msg)
            raise ValueError(error_msg) from e
