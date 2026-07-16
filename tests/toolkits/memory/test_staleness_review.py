"""Tests for staleness_review strategy: select_stale_candidates + StalenessReviewer.

Covers:
- Candidate selection with TTL filtering
- Protected memory exclusion (pinned, correction, recently accessed, non-active)
- Severity-based sorting and batch limit
- LLM review parsing (KEEP/EXTEND/REMOVE decisions)
- Keep cooldown mechanism
- Max removals per cycle cap
- Edge cases: empty input, malformed LLM response, min_candidates threshold
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.staleness_review import (
    StalenessAction,
    StalenessDecision,
    StalenessReviewConfig,
    StalenessReviewResult,
    StalenessReviewer,
    select_stale_candidates,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryStatus,
    MemoryType,
    SemanticMemory,
)


def _make_semantic(
    *,
    mem_id: str = "mem-1",
    content: str = "user prefers dark mode",
    days_old: int = 100,
    expected_valid_days: int | None = 30,
    pinned: bool = False,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    correction_of: str | None = None,
    last_accessed_days_ago: int | None = None,
    access_count: int = 3,
    importance: float = 0.5,
) -> SemanticMemory:
    now = datetime.now(UTC)
    created = now - timedelta(days=days_old)
    last_accessed = (
        now - timedelta(days=last_accessed_days_ago)
        if last_accessed_days_ago is not None
        else None
    )
    return SemanticMemory(
        id=mem_id,
        content=content,
        created_at=created,
        updated_at=created,
        access_count=access_count,
        last_accessed_at=last_accessed,
        pinned=pinned,
        expected_valid_days=expected_valid_days,
        status=status,
        correction_of=correction_of,
        importance=importance,
    )


class TestSelectStaleCandidates:
    def test_basic_selection(self) -> None:
        """Memories past their TTL are selected."""
        mem = _make_semantic(days_old=100, expected_valid_days=30)
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 1
        assert result[0].id == mem.id

    def test_not_expired_excluded(self) -> None:
        """Memories within their TTL are excluded."""
        mem = _make_semantic(days_old=10, expected_valid_days=30)
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_no_evd_excluded(self) -> None:
        """Memories without expected_valid_days are excluded."""
        mem = _make_semantic(expected_valid_days=None)
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_zero_evd_excluded(self) -> None:
        """Memories with expected_valid_days=0 are excluded."""
        mem = _make_semantic(expected_valid_days=0)
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_pinned_excluded(self) -> None:
        """Pinned memories are never candidates."""
        mem = _make_semantic(days_old=100, expected_valid_days=30, pinned=True)
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_non_active_excluded(self) -> None:
        """Non-active memories are excluded."""
        mem = _make_semantic(
            days_old=100, expected_valid_days=30, status=MemoryStatus.ARCHIVED
        )
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_correction_chain_excluded(self) -> None:
        """Correction-chain memories are excluded."""
        mem = _make_semantic(
            days_old=100, expected_valid_days=30, correction_of="old-mem-1"
        )
        result = select_stale_candidates([mem], StalenessReviewConfig())
        assert len(result) == 0

    def test_recently_accessed_excluded(self) -> None:
        """Recently accessed memories are protected."""
        mem = _make_semantic(
            days_old=100, expected_valid_days=30, last_accessed_days_ago=3
        )
        config = StalenessReviewConfig(recent_access_protection_days=7)
        result = select_stale_candidates([mem], config)
        assert len(result) == 0

    def test_old_access_not_protected(self) -> None:
        """Old access doesn't protect from selection."""
        mem = _make_semantic(
            days_old=100, expected_valid_days=30, last_accessed_days_ago=30
        )
        config = StalenessReviewConfig(recent_access_protection_days=7)
        result = select_stale_candidates([mem], config)
        assert len(result) == 1

    def test_severity_sorting(self) -> None:
        """Candidates are sorted by expiration severity (age - evd) descending."""
        mem_severe = _make_semantic(
            mem_id="severe", days_old=200, expected_valid_days=30
        )
        mem_mild = _make_semantic(
            mem_id="mild", days_old=40, expected_valid_days=30
        )
        result = select_stale_candidates(
            [mem_mild, mem_severe], StalenessReviewConfig()
        )
        assert result[0].id == "severe"
        assert result[1].id == "mild"

    def test_batch_limit(self) -> None:
        """max_candidates_per_cycle limits output."""
        mems = [
            _make_semantic(mem_id=f"m-{i}", days_old=100 + i, expected_valid_days=30)
            for i in range(30)
        ]
        config = StalenessReviewConfig(max_candidates_per_cycle=5)
        result = select_stale_candidates(mems, config)
        assert len(result) == 5

    def test_empty_input(self) -> None:
        """Empty input returns empty result."""
        result = select_stale_candidates([], StalenessReviewConfig())
        assert result == []


class TestStalenessReviewer:
    @pytest.mark.asyncio
    async def test_below_min_candidates_skips(self) -> None:
        """Review is skipped if candidates < min_candidates."""
        llm = AsyncMock()
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)
        assert result.reviewed_count == 0
        llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_keep_decision(self) -> None:
        """KEEP decision increments kept_count and adds cooldown update."""
        llm_response = json.dumps([
            {"id": "m-1", "action": "keep", "reason": "still valid"},
            {"id": "m-2", "action": "keep", "reason": "still valid"},
            {"id": "m-3", "action": "keep", "reason": "still valid"},
        ])
        llm = AsyncMock(return_value=llm_response)
        config = StalenessReviewConfig(
            min_candidates=3, keep_cooldown_days=30
        )
        reviewer = StalenessReviewer(llm, config)
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.kept_count == 3
        assert result.removed_count == 0
        assert result.extended_count == 0
        assert len(result.keep_cooldown_updates) == 3
        assert result.keep_cooldown_updates[0] == ("m-1", 60)

    @pytest.mark.asyncio
    async def test_extend_decision(self) -> None:
        """EXTEND decision records extension days."""
        llm_response = json.dumps([
            {"id": "m-1", "action": "extend", "reason": "long-term preference", "extend_by_days": 180},
            {"id": "m-2", "action": "extend", "reason": "stable habit", "extend_by_days": 365},
            {"id": "m-3", "action": "keep", "reason": "still valid"},
        ])
        llm = AsyncMock(return_value=llm_response)
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.extended_count == 2
        assert ("m-1", 180) in result.extended_updates
        assert ("m-2", 365) in result.extended_updates

    @pytest.mark.asyncio
    async def test_remove_decision(self) -> None:
        """REMOVE decision is capped by max_removals_per_cycle."""
        llm_response = json.dumps([
            {"id": f"m-{i}", "action": "remove", "reason": "outdated"}
            for i in range(10)
        ])
        llm = AsyncMock(return_value=llm_response)
        config = StalenessReviewConfig(min_candidates=3, max_removals_per_cycle=5)
        reviewer = StalenessReviewer(llm, config)
        candidates = [
            _make_semantic(mem_id=f"m-{i}", days_old=200, expected_valid_days=30)
            for i in range(10)
        ]
        result = await reviewer.review(candidates)

        assert result.removed_count == 5
        assert len(result.removed_ids) == 5

    @pytest.mark.asyncio
    async def test_max_extension_days_cap(self) -> None:
        """extend_by_days is capped at max_extension_days."""
        llm_response = json.dumps([
            {"id": "m-1", "action": "extend", "reason": "stable", "extend_by_days": 9999},
            {"id": "m-2", "action": "keep", "reason": "ok"},
            {"id": "m-3", "action": "keep", "reason": "ok"},
        ])
        llm = AsyncMock(return_value=llm_response)
        config = StalenessReviewConfig(
            min_candidates=3, max_extension_days=730
        )
        reviewer = StalenessReviewer(llm, config)
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.extended_updates[0] == ("m-1", 730)

    @pytest.mark.asyncio
    async def test_malformed_llm_response_handled(self) -> None:
        """Malformed LLM output doesn't crash; returns empty result."""
        llm = AsyncMock(return_value="This is not JSON at all.")
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id=f"m-{i}", days_old=60, expected_valid_days=30)
            for i in range(3)
        ]
        result = await reviewer.review(candidates)

        assert result.reviewed_count == 0
        assert result.removed_count == 0

    @pytest.mark.asyncio
    async def test_llm_exception_handled(self) -> None:
        """LLM call exception doesn't crash."""
        llm = AsyncMock(side_effect=RuntimeError("API timeout"))
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id=f"m-{i}", days_old=60, expected_valid_days=30)
            for i in range(3)
        ]
        result = await reviewer.review(candidates)

        assert result.candidates_found == 3
        assert result.reviewed_count == 0

    @pytest.mark.asyncio
    async def test_invalid_ids_in_response_ignored(self) -> None:
        """LLM returning IDs not in candidates are ignored."""
        llm_response = json.dumps([
            {"id": "m-1", "action": "keep", "reason": "valid"},
            {"id": "FAKE-ID", "action": "remove", "reason": "fake"},
            {"id": "m-2", "action": "keep", "reason": "valid"},
            {"id": "m-3", "action": "keep", "reason": "valid"},
        ])
        llm = AsyncMock(return_value=llm_response)
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.reviewed_count == 3
        assert result.removed_count == 0

    @pytest.mark.asyncio
    async def test_json_wrapped_in_text(self) -> None:
        """LLM response with surrounding text is still parsed."""
        llm_response = (
            'Here are my decisions:\n```json\n'
            + json.dumps([
                {"id": "m-1", "action": "remove", "reason": "outdated"},
                {"id": "m-2", "action": "keep", "reason": "valid"},
                {"id": "m-3", "action": "extend", "reason": "stable", "extend_by_days": 90},
            ])
            + '\n```\nThat is all.'
        )
        llm = AsyncMock(return_value=llm_response)
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.reviewed_count == 3
        assert result.removed_count == 1
        assert result.extended_count == 1
        assert result.kept_count == 1

    @pytest.mark.asyncio
    async def test_invalid_action_defaults_to_keep(self) -> None:
        """Unknown action string defaults to KEEP."""
        llm_response = json.dumps([
            {"id": "m-1", "action": "unknown_action", "reason": "??"},
            {"id": "m-2", "action": "keep", "reason": "ok"},
            {"id": "m-3", "action": "keep", "reason": "ok"},
        ])
        llm = AsyncMock(return_value=llm_response)
        reviewer = StalenessReviewer(llm, StalenessReviewConfig(min_candidates=3))
        candidates = [
            _make_semantic(mem_id="m-1", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-2", days_old=60, expected_valid_days=30),
            _make_semantic(mem_id="m-3", days_old=60, expected_valid_days=30),
        ]
        result = await reviewer.review(candidates)

        assert result.kept_count == 3
        assert result.removed_count == 0
