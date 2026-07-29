"""CI gate for wiki retrieval benchmark regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.diagnostics.recall_benchmark import (
    WikiRecallBenchmarkCase,
    run_wiki_recall_benchmark,
    summarize_wiki_recall_benchmark,
)

MIN_RECALL_AT_K = 0.8


@pytest.fixture
async def indexed_fixture_vault(tmp_path: Path) -> tuple[WikiStructure, WikiConfig]:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_semantic_search=False)

    articles = {
        "Gravity": ("gravity mass weight", "## Compiled Truth\nGravity attracts mass."),
        "RedisCache": ("redis session cache ttl", "## Compiled Truth\nRedis stores session cache with TTL."),
        "BillingDB": (
            "billing postgres database",
            "## Compiled Truth\nBilling postgres database stores invoices.",
        ),
    }
    from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

    indexer = WikiIndexer(structure, config)
    for concept_name, (_query_hint, body) in articles.items():
        path = structure.get_concept_file_path(concept_name)
        path.write_text(body, encoding="utf-8")
        await indexer.upsert(concept_name, body)

    return structure, config


@pytest.mark.asyncio
async def test_wiki_recall_benchmark_gate_meets_baseline(
    indexed_fixture_vault: tuple[WikiStructure, WikiConfig],
) -> None:
    structure, config = indexed_fixture_vault
    cases = [
        WikiRecallBenchmarkCase(case_id="en_gravity", query="gravity mass", expected_concept_name="Gravity"),
        WikiRecallBenchmarkCase(case_id="en_redis", query="redis session cache", expected_concept_name="RedisCache"),
        WikiRecallBenchmarkCase(
            case_id="en_billing",
            query="billing postgres database",
            expected_concept_name="BillingDB",
        ),
    ]

    results = await run_wiki_recall_benchmark(structure, config, cases)
    summary = summarize_wiki_recall_benchmark(results)

    assert summary.case_count == 3
    assert summary.recall_at_k >= MIN_RECALL_AT_K, (
        f"recall@k={summary.recall_at_k:.3f} below baseline {MIN_RECALL_AT_K}"
    )
    assert summary.status in {"ready", "warning"}
