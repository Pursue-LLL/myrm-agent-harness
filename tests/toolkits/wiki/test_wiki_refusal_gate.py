"""Sealed bidirectional refusal-gate benchmark for WikiQueryEngine.

Sealed confirmation set: refusal cases MUST refuse, answer cases MUST answer.
An invalid threshold configuration MUST fail closed to refused. Mirrors the
gbrain 5-question acceptance philosophy (question 5: no-evidence queries must
admit "unknown" instead of hallucinating) with machine-checked assertions.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig, WikiQueryConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine

ARTICLES = {
    "Gravity": "## Compiled Truth\nGravity attracts mass.",
    "RedisCache": "## Compiled Truth\nRedis stores session cache with TTL.",
    "BillingDB": "## Compiled Truth\nBilling postgres database stores invoices.",
}

DEFAULT_REFUSAL_FLOOR = WikiQueryConfig().min_answer_confidence


@pytest.fixture
async def indexed_fixture_vault(tmp_path: Path) -> tuple[WikiStructure, WikiConfig]:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_semantic_search=False)
    indexer = WikiIndexer(structure, config)
    for concept_name, body in ARTICLES.items():
        path = structure.get_concept_file_path(concept_name)
        path.write_text(body, encoding="utf-8")
        await indexer.upsert(concept_name, body)
    return structure, config


async def _query(
    structure: WikiStructure,
    config: WikiConfig,
    question: str,
    query_config: WikiQueryConfig | None = None,
):
    engine = WikiQueryEngine(llm=MagicMock(), structure=structure, config=config)
    return await engine.query(question, query_config=query_config)


@pytest.mark.asyncio
async def test_answer_cases_must_answer(
    indexed_fixture_vault: tuple[WikiStructure, WikiConfig],
) -> None:
    """Sealed answer set: indexed evidence questions must NOT refuse."""
    structure, config = indexed_fixture_vault
    for question in ("gravity mass", "redis session cache ttl", "billing postgres"):
        result = await _query(structure, config, question)
        assert not result.refused, f"answer case refused: {question}"


@pytest.mark.asyncio
async def test_refusal_cases_must_refuse(
    indexed_fixture_vault: tuple[WikiStructure, WikiConfig],
) -> None:
    """Sealed refusal set: zero-evidence questions must refuse."""
    structure, config = indexed_fixture_vault
    for question in ("quantum chromodynamics lattice", "homelab nginx port mapping"):
        result = await _query(structure, config, question)
        assert result.refused, f"refusal case answered: {question}"
        assert result.confidence_score < DEFAULT_REFUSAL_FLOOR


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_threshold", [-0.1, 1.5])
async def test_invalid_threshold_fails_closed(
    indexed_fixture_vault: tuple[WikiStructure, WikiConfig],
    invalid_threshold: float,
) -> None:
    """Fail-closed: an out-of-bounds threshold must refuse, never pass through."""
    structure, config = indexed_fixture_vault
    broken = WikiQueryConfig(min_answer_confidence=invalid_threshold)
    result = await _query(structure, config, "gravity mass", query_config=broken)
    assert result.refused


@pytest.mark.asyncio
async def test_high_threshold_refuses_everything(
    indexed_fixture_vault: tuple[WikiStructure, WikiConfig],
) -> None:
    """A floor of 1.0 refuses even well-evidenced answers (explicit strict mode)."""
    structure, config = indexed_fixture_vault
    strict = WikiQueryConfig(min_answer_confidence=1.0)
    result = await _query(structure, config, "gravity mass", query_config=strict)
    assert result.refused


def test_refusal_verdict_helper() -> None:
    """Direct unit contract for the fail-closed verdict helper."""
    assert not WikiQueryEngine._refused_verdict(0.9, 0.35)
    assert not WikiQueryEngine._refused_verdict(0.35, 0.35)
    assert WikiQueryEngine._refused_verdict(0.34, 0.35)
    assert WikiQueryEngine._refused_verdict(0.9, -0.1)
    assert WikiQueryEngine._refused_verdict(0.9, 1.5)


def test_default_config_contract() -> None:
    """Defaults: refusal floor 0.35, decoupled from the 0.7 archive gate."""
    query_config = WikiQueryConfig()
    assert query_config.min_answer_confidence == 0.35
    assert query_config.min_query_quality_score == 0.7
    assert query_config.min_answer_confidence < query_config.min_query_quality_score
