"""Live integration test for ReTree FastContradictionDetector using real LLM from .env.test.

Uses real API credentials loaded from .env.test:
- BASIC_MODEL (e.g. openai-like/muse-spark-1.3-contributor)
- BASIC_BASE_URL
- BASIC_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.agent.config.litellm_routing import normalize_env_model_selection_string
from myrm_agent_harness.toolkits.llms.core.llm import create_litellm_model
from myrm_agent_harness.toolkits.memory.working_tree import (
    BoundedSummary,
    ConflictType,
    EvidenceNode,
    EvidenceSource,
    FastContradictionDetector,
)

_ENV_TEST = (
    Path(__file__).resolve().parents[4]
    / "myrm-agent"
    / "myrm-agent-server"
    / ".env.test"
)


from langchain_core.language_models.chat_models import BaseChatModel


def _get_live_llm() -> BaseChatModel:
    if not _ENV_TEST.exists():
        pytest.skip(f"{_ENV_TEST} not found")

    for line in _ENV_TEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value:
            os.environ.setdefault(key, value)

    api_key = os.environ.get("BASIC_API_KEY", "")
    base_url = os.environ.get("BASIC_BASE_URL", "")
    model = os.environ.get("BASIC_MODEL", "")

    if not all([api_key, base_url, model]):
        pytest.skip("BASIC_API_KEY / BASIC_BASE_URL / BASIC_MODEL not configured in .env.test")

    norm_model = normalize_env_model_selection_string(model)
    return create_litellm_model(norm_model, base_url=base_url, api_key=api_key, streaming=False)


class TestWorkingTreeRealLLMIntegration:
    """Live verification of FastContradictionDetector with real model configured in .env.test."""

    @pytest.mark.asyncio
    async def test_real_llm_arbitration_on_contradiction(self) -> None:
        """Run real LLM arbitration and verify model understands factual refutation."""
        llm = _get_live_llm()
        detector = FastContradictionDetector(arbitrator_llm=llm)

        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        prior_node = EvidenceNode(
            node_id="ev_live_01",
            claim="NVIDIA H100 initial pricing baseline",
            bounded_summary=BoundedSummary(
                summary="NVIDIA H100 MSRP was established at $30,000 per unit in 2023.",
                key_entities=["H100", "NVIDIA", "MSRP"],
                key_metrics={"price": "$30,000"},
            ),
            source=EvidenceSource(url="https://example.com/h100-2023"),
            dependencies=["root_plan"],
            created_at=now,
            updated_at=now,
        )

        new_claim = "NVIDIA H100 pricing refuted"
        new_summary = (
            "Recent 2026 secondary enterprise market data refutes the $30,000 baseline; "
            "standard enterprise purchase contracts are now discounted to $22,000."
        )

        verdict = await detector.acheck_conflict(
            new_claim=new_claim,
            new_summary=new_summary,
            existing_nodes=[prior_node],
        )

        # Print model response for objective evidence logging
        print(f"\n[LIVE_LLM_EVIDENCE] Model: {os.environ.get('BASIC_MODEL')}")
        print(f"[LIVE_LLM_EVIDENCE] ConflictType: {verdict.conflict_type}")
        print(f"[LIVE_LLM_EVIDENCE] ConflictingNode: {verdict.conflicting_node_id}")
        print(f"[LIVE_LLM_EVIDENCE] Reason: {verdict.reason}")
        print(f"[LIVE_LLM_EVIDENCE] Confidence: {verdict.confidence}")

        # Assertions
        assert verdict.conflict_type in (ConflictType.CONTRADICTION, ConflictType.TEMPORAL_UPDATE)
        assert verdict.conflicting_node_id == "ev_live_01"
        assert len(verdict.reason) > 5
