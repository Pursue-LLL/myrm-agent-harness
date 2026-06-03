"""Tests for memory retrieval evaluation framework."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from myrm_agent_harness.eval.memory_retrieval import (
    MemoryRetrievalEvalRunner,
    load_eval_cases,
)
from myrm_agent_harness.eval.memory_retrieval.protocols import (
    MemoryRetrievalEvalCase,
    MemoryRetrievalEvalSummary,
)


class _MockAdapter:
    """Test adapter that returns deterministic results based on query content."""

    def __init__(self, hit_map: dict[str, list[str]] | None = None) -> None:
        self._hit_map = hit_map or {}

    async def ingest(self, memory_id: str, content: str, *, category: str = "", language: str = "en") -> None:
        pass

    async def query(self, query_text: str, top_k: int = 10) -> list[str]:
        return self._hit_map.get(query_text, [])[:top_k]

    async def clear(self) -> None:
        pass


class TestLoadEvalCases:
    def test_loads_builtin_dataset(self) -> None:
        cases = load_eval_cases()
        assert len(cases) > 0
        for case in cases:
            assert case.id
            assert case.query
            assert len(case.gold_ids) > 0
            assert case.category

    def test_loads_custom_path(self, tmp_path: Path) -> None:
        data = {
            "cases": [
                {
                    "id": "test_1",
                    "query": "test query",
                    "gold_ids": ["mem_1"],
                    "category": "test",
                }
            ]
        }
        path = tmp_path / "custom.json"
        path.write_text(json.dumps(data))
        cases = load_eval_cases(path)
        assert len(cases) == 1
        assert cases[0].id == "test_1"

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_eval_cases("/nonexistent/path.json")


class TestMemoryRetrievalEvalRunner:
import asyncio

def test_perfect_retrieval(self) -> None:
        cases = [
            MemoryRetrievalEvalCase(id="c1", category="cat_a", query="q1", gold_ids=["m1"]),
            MemoryRetrievalEvalCase(id="c2", category="cat_a", query="q2", gold_ids=["m2"]),
        ]
        adapter = _MockAdapter(hit_map={"q1": ["m1", "x", "y"], "q2": ["m2", "x", "y"]})
        runner = MemoryRetrievalEvalRunner(adapter)
        
        # create new loop for the test since asyncio.get_event_loop() may fail if none exists in thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases))
        finally:
            loop.close()

        assert summary.total_cases == 2
        assert summary.recall_at_5 == pytest.approx(1.0)
        assert summary.mrr_score == pytest.approx(1.0)
        assert len(summary.by_category) == 1
        assert summary.by_category[0].category == "cat_a"

    def test_zero_retrieval(self) -> None:
        cases = [
            MemoryRetrievalEvalCase(id="c1", category="cat_a", query="q1", gold_ids=["m1"]),
        ]
        adapter = _MockAdapter(hit_map={"q1": ["x", "y", "z"]})
        runner = MemoryRetrievalEvalRunner(adapter)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases))
        finally:
            loop.close()

        assert summary.total_cases == 1
        assert summary.recall_at_5 == pytest.approx(0.0)
        assert summary.mrr_score == pytest.approx(0.0)

    def test_partial_retrieval_across_categories(self) -> None:
        cases = [
            MemoryRetrievalEvalCase(id="c1", category="cat_a", query="q1", gold_ids=["m1"]),
            MemoryRetrievalEvalCase(id="c2", category="cat_b", query="q2", gold_ids=["m2"]),
        ]
        adapter = _MockAdapter(hit_map={"q1": ["m1"], "q2": ["x"]})
        runner = MemoryRetrievalEvalRunner(adapter)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases))
        finally:
            loop.close()

        assert summary.total_cases == 2
        assert summary.recall_at_5 == pytest.approx(0.5)
        assert len(summary.by_category) == 2
        cat_map = {c.category: c for c in summary.by_category}
        assert cat_map["cat_a"].recall_at_5 == pytest.approx(1.0)
        assert cat_map["cat_b"].recall_at_5 == pytest.approx(0.0)

    def test_empty_cases(self) -> None:
        adapter = _MockAdapter()
        runner = MemoryRetrievalEvalRunner(adapter)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run([]))
        finally:
            loop.close()
        assert summary.total_cases == 0

    def test_with_memories_ingest_and_clear(self) -> None:
        """Test that memories are ingested and adapter is cleared after run."""
        ingested: list[tuple[str, str]] = []
        cleared = [False]

        class _TrackingAdapter:
            async def ingest(self, memory_id: str, content: str, *, category: str = "", language: str = "en") -> None:
                ingested.append((memory_id, content))

            async def query(self, query_text: str, top_k: int = 10) -> list[str]:
                return ["m1"] if "q1" in query_text else []

            async def clear(self) -> None:
                cleared[0] = True

        cases = [MemoryRetrievalEvalCase(id="c1", category="cat", query="q1", gold_ids=["m1"])]
        memories = [{"id": "m1", "content": "content 1", "category": "cat", "language": "en"}]
        runner = MemoryRetrievalEvalRunner(_TrackingAdapter())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases, memories=memories))
        finally:
            loop.close()

        assert len(ingested) == 1
        assert ingested[0] == ("m1", "content 1")
        assert cleared[0] is True
        assert summary.total_cases == 1

    def test_clear_failure_does_not_raise(self) -> None:
        """Test that adapter.clear() failure is caught gracefully."""

        class _FailClearAdapter:
            async def ingest(self, memory_id: str, content: str, *, category: str = "", language: str = "en") -> None:
                pass

            async def query(self, query_text: str, top_k: int = 10) -> list[str]:
                return []

            async def clear(self) -> None:
                raise RuntimeError("clear failed")

        cases = [MemoryRetrievalEvalCase(id="c1", category="cat", query="q1", gold_ids=["m1"])]
        memories = [{"id": "m1", "content": "test"}]
        runner = MemoryRetrievalEvalRunner(_FailClearAdapter())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases, memories=memories))
        finally:
            loop.close()
        assert summary.total_cases == 1

    def test_query_exception_returns_empty_retrieval(self) -> None:
        """Test that query failure for a case results in zero scores."""

        class _FailQueryAdapter:
            async def ingest(self, memory_id: str, content: str, *, category: str = "", language: str = "en") -> None:
                pass

            async def query(self, query_text: str, top_k: int = 10) -> list[str]:
                raise RuntimeError("query failed")

            async def clear(self) -> None:
                pass

        cases = [MemoryRetrievalEvalCase(id="c1", category="cat", query="q1", gold_ids=["m1"])]
        runner = MemoryRetrievalEvalRunner(_FailQueryAdapter())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            summary = loop.run_until_complete(runner.run(cases))
        finally:
            loop.close()
        assert summary.total_cases == 1
        assert summary.recall_at_5 == pytest.approx(0.0)
        assert summary.mrr_score == pytest.approx(0.0)


class TestMemoryRetrievalEvalSummaryToDict:
    def test_to_dict_basic(self) -> None:
        summary = MemoryRetrievalEvalSummary(
            total_cases=2,
            recall_at_5=0.75,
            recall_at_10=0.85,
            ndcg_at_10=0.6123,
            mrr_score=0.5,
            precision_at_5=0.4,
            hit_at_5=1.0,
            latency_p50_ms=12.345,
            latency_p95_ms=45.678,
        )
        d = summary.to_dict()
        assert d["total_cases"] == 2
        assert d["recall_at_5"] == 0.75
        assert d["recall_at_10"] == 0.85
        assert d["ndcg_at_10"] == 0.6123
        assert d["mrr"] == 0.5
        assert d["precision_at_5"] == 0.4
        assert d["hit_at_5"] == 1.0
        assert d["latency_p50_ms"] == 12.35
        assert d["latency_p95_ms"] == 45.68
        assert d["by_category"] == []

    def test_to_dict_with_categories(self) -> None:
        from myrm_agent_harness.eval.memory_retrieval.protocols import MemoryRetrievalCategorySummary

        summary = MemoryRetrievalEvalSummary(
            total_cases=1,
            recall_at_5=1.0,
            by_category=[
                MemoryRetrievalCategorySummary(
                    category="tech",
                    count=1,
                    recall_at_5=1.0,
                    recall_at_10=1.0,
                    ndcg_at_10=0.9,
                    mrr_score=0.8,
                )
            ],
        )
        d = summary.to_dict()
        assert len(d["by_category"]) == 1
        assert d["by_category"][0]["category"] == "tech"
        assert d["by_category"][0]["recall_at_5"] == 1.0
