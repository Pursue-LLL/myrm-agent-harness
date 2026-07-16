"""Integration test: StalenessReviewer with real LLM.

Verifies the end-to-end flow:
1. Construct stale memory candidates
2. Send to real LLM for review
3. Parse response into valid decisions
4. Verify KEEP/EXTEND/REMOVE logic

Requires: LITE_API_KEY, LITE_BASE_URL, LITE_MODEL env vars (from .env.test).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.strategies.staleness_review import (
    StalenessAction,
    StalenessReviewConfig,
    StalenessReviewer,
    select_stale_candidates,
)
from myrm_agent_harness.toolkits.memory.types import MemoryStatus, SemanticMemory

pytestmark = [pytest.mark.integration, pytest.mark.timeout(30)]


def _get_lite_llm_config() -> tuple[str, str, str]:
    api_key = os.environ.get("LITE_API_KEY", "")
    base_url = os.environ.get("LITE_BASE_URL", "")
    model = os.environ.get("LITE_MODEL", "")
    if not all([api_key, base_url, model]):
        pytest.skip("LITE_API_KEY/LITE_BASE_URL/LITE_MODEL not configured")
    return api_key, base_url, model


def _make_stale_memory(
    mem_id: str,
    content: str,
    days_old: int,
    expected_valid_days: int,
) -> SemanticMemory:
    now = datetime.now(UTC)
    return SemanticMemory(
        id=mem_id,
        content=content,
        created_at=now - timedelta(days=days_old),
        updated_at=now - timedelta(days=days_old),
        access_count=2,
        importance=0.5,
        expected_valid_days=expected_valid_days,
        status=MemoryStatus.ACTIVE,
    )


@pytest.mark.asyncio
async def test_staleness_review_real_llm_produces_valid_decisions() -> None:
    """Real LLM returns parseable JSON decisions for stale memories."""
    api_key, base_url, model = _get_lite_llm_config()

    async def llm_func(system: str, prompt: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model.split("/", 1)[-1] if "/" in model else model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    candidates = [
        _make_stale_memory(
            "mem-outdated-1",
            "User is currently studying Python basics on Coursera",
            days_old=400,
            expected_valid_days=90,
        ),
        _make_stale_memory(
            "mem-stable-1",
            "User prefers dark mode in all applications",
            days_old=200,
            expected_valid_days=60,
        ),
        _make_stale_memory(
            "mem-project-1",
            "User is working on a React e-commerce project called ShopFlow",
            days_old=300,
            expected_valid_days=60,
        ),
    ]

    config = StalenessReviewConfig(min_candidates=3, max_removals_per_cycle=5)
    reviewer = StalenessReviewer(llm_func, config)
    result = await reviewer.review(candidates)

    assert result.candidates_found == 3
    assert result.reviewed_count >= 1, "LLM should return at least one parseable decision"

    total_decisions = result.kept_count + result.extended_count + result.removed_count
    assert total_decisions == result.reviewed_count

    for mid, days in result.extended_updates:
        assert days > 0
        assert days <= config.max_extension_days

    assert len(result.removed_ids) <= config.max_removals_per_cycle


@pytest.mark.asyncio
async def test_select_stale_candidates_with_real_data() -> None:
    """Integration: select candidates correctly from a realistic memory set."""
    now = datetime.now(UTC)
    memories = [
        SemanticMemory(
            id="fresh-1",
            content="User likes coffee",
            created_at=now - timedelta(days=5),
            expected_valid_days=30,
            status=MemoryStatus.ACTIVE,
        ),
        SemanticMemory(
            id="stale-1",
            content="User is learning Rust",
            created_at=now - timedelta(days=100),
            expected_valid_days=30,
            status=MemoryStatus.ACTIVE,
        ),
        SemanticMemory(
            id="stale-2",
            content="User works at company X",
            created_at=now - timedelta(days=200),
            expected_valid_days=90,
            status=MemoryStatus.ACTIVE,
        ),
        SemanticMemory(
            id="pinned-1",
            content="User name is John",
            created_at=now - timedelta(days=500),
            expected_valid_days=30,
            pinned=True,
            status=MemoryStatus.ACTIVE,
        ),
        SemanticMemory(
            id="archived-1",
            content="Old fact",
            created_at=now - timedelta(days=300),
            expected_valid_days=30,
            status=MemoryStatus.ARCHIVED,
        ),
    ]

    config = StalenessReviewConfig()
    candidates = select_stale_candidates(memories, config)

    candidate_ids = {c.id for c in candidates}
    assert "stale-1" in candidate_ids
    assert "stale-2" in candidate_ids
    assert "fresh-1" not in candidate_ids
    assert "pinned-1" not in candidate_ids
    assert "archived-1" not in candidate_ids
