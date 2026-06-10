"""Tests for planner archive module — PlanArchiveStore and PlanRecaller."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.planner.archive import (
    DEDUP_THRESHOLD,
    MIN_SUCCESS_RATE,
    SIMILARITY_THRESHOLD,
    VECTOR_COLLECTION,
    PlanArchiveStore,
    PlanRecaller,
    _build_embed_text,
    _build_recall_text,
)


def _make_plan(
    goal: str = "Build a web scraper",
    reasoning: str = "Need to extract data",
    num_steps: int = 3,
    completed: int = 3,
    errors: int = 0,
    decisions: int = 0,
) -> MagicMock:
    """Create a mock Plan object."""
    plan = MagicMock()
    plan.goal = goal
    plan.reasoning = reasoning

    steps = []
    for i in range(num_steps):
        step = MagicMock()
        step.description = f"Step {i+1} description for the task"
        step.status = "completed" if i < completed else "pending"
        steps.append(step)
    plan.steps = steps

    errs = []
    for i in range(errors):
        err = MagicMock()
        err.error_type = f"Error{i}"
        err.resolution = f"Fixed by doing X{i}"
        err.resolution_success = True
        errs.append(err)
    plan.errors_encountered = errs

    decs = []
    for i in range(decisions):
        dec = MagicMock()
        dec.topic = f"Topic{i}"
        dec.decision = f"Decided to do Y{i}"
        dec.status = "active"
        decs.append(dec)
    plan.decisions = decs

    return plan


class TestBuildEmbedText:
    def test_basic(self) -> None:
        result = _build_embed_text("goal", "steps")
        assert result == "goal\nsteps"

    def test_multiline(self) -> None:
        result = _build_embed_text("my goal", "step1 → step2")
        assert "my goal" in result
        assert "step1 → step2" in result


class TestBuildRecallText:
    def test_basic(self) -> None:
        result = _build_recall_text("goal", "steps", "", "")
        assert "Goal: goal" in result
        assert "Steps: steps" in result
        assert "Error Recovery" not in result
        assert "Key Decisions" not in result

    def test_with_errors_and_decisions(self) -> None:
        result = _build_recall_text("goal", "steps", "err_pat", "dec_pat")
        assert "Error Recovery: err_pat" in result
        assert "Key Decisions: dec_pat" in result


class TestPlanArchiveStore:
    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_archive.db"

    @pytest.fixture
    def store(self, db_path: Path) -> PlanArchiveStore:
        return PlanArchiveStore(db_path)

    @pytest.fixture
    def store_with_vector(self, db_path: Path) -> PlanArchiveStore:
        vector = AsyncMock()
        vector.search.return_value = []
        embedding = AsyncMock()
        embedding.embed.return_value = [0.1] * 128
        return PlanArchiveStore(db_path, vector_store=vector, embedding=embedding)

    def test_init_creates_db(self, db_path: Path) -> None:
        store = PlanArchiveStore(db_path)
        assert db_path.exists()
        assert store._db_path == db_path

    def test_init_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep_path = tmp_path / "a" / "b" / "c" / "archive.db"
        store = PlanArchiveStore(deep_path)
        assert deep_path.parent.exists()
        assert store._db_path == deep_path

    @pytest.mark.asyncio
    async def test_archive_plan_success(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(completed=3, num_steps=3)
        result = await store.archive_plan(plan)
        assert result is True

    @pytest.mark.asyncio
    async def test_archive_plan_quality_gate_rejects(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(completed=1, num_steps=5)
        result = await store.archive_plan(plan)
        assert result is False

    @pytest.mark.asyncio
    async def test_archive_plan_quality_gate_passes(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(completed=4, num_steps=5)
        result = await store.archive_plan(plan)
        assert result is True

    @pytest.mark.asyncio
    async def test_archive_plan_with_vector(self, store_with_vector: PlanArchiveStore) -> None:
        plan = _make_plan(completed=3, num_steps=3)
        result = await store_with_vector.archive_plan(plan)
        assert result is True
        store_with_vector._vector_store.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_plan_dedup(self, store_with_vector: PlanArchiveStore) -> None:
        mock_result = MagicMock()
        mock_result.score = 0.96
        store_with_vector._vector_store.search.return_value = [mock_result]

        plan = _make_plan(completed=3, num_steps=3)
        result = await store_with_vector.archive_plan(plan)
        assert result is False

    @pytest.mark.asyncio
    async def test_archive_plan_no_dedup_when_vector_unavailable(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(completed=3, num_steps=3)
        result1 = await store.archive_plan(plan)
        result2 = await store.archive_plan(plan)
        assert result1 is True
        assert result2 is True

    def test_compute_success_rate_full(self) -> None:
        plan = _make_plan(completed=5, num_steps=5)
        assert PlanArchiveStore._compute_success_rate(plan) == 1.0

    def test_compute_success_rate_partial(self) -> None:
        plan = _make_plan(completed=2, num_steps=5)
        assert PlanArchiveStore._compute_success_rate(plan) == 0.4

    def test_compute_success_rate_empty(self) -> None:
        plan = MagicMock()
        plan.steps = []
        assert PlanArchiveStore._compute_success_rate(plan) == 0.0

    def test_extract_error_patterns(self) -> None:
        plan = _make_plan(errors=2)
        result = PlanArchiveStore._extract_error_patterns(plan)
        assert "Error0" in result
        assert "Error1" in result

    def test_extract_error_patterns_empty(self) -> None:
        plan = _make_plan(errors=0)
        assert PlanArchiveStore._extract_error_patterns(plan) == ""

    def test_extract_key_decisions(self) -> None:
        plan = _make_plan(decisions=2)
        result = PlanArchiveStore._extract_key_decisions(plan)
        assert "Topic0" in result
        assert "Topic1" in result

    def test_extract_key_decisions_empty(self) -> None:
        plan = _make_plan(decisions=0)
        assert PlanArchiveStore._extract_key_decisions(plan) == ""

    @pytest.mark.asyncio
    async def test_sync_to_vector_skips_when_no_vector(self, store: PlanArchiveStore) -> None:
        await store._sync_to_vector("id", "goal", "steps")

    @pytest.mark.asyncio
    async def test_sync_to_vector_handles_exception(self, store_with_vector: PlanArchiveStore) -> None:
        store_with_vector._vector_store.upsert.side_effect = RuntimeError("connection failed")
        await store_with_vector._sync_to_vector("id", "goal", "steps")


class TestPlanRecaller:
    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "recall_archive.db"

    @pytest.fixture
    def store(self, db_path: Path) -> PlanArchiveStore:
        return PlanArchiveStore(db_path)

    @pytest.fixture
    def store_with_vector(self, db_path: Path) -> PlanArchiveStore:
        vector = AsyncMock()
        vector.search.return_value = []
        embedding = AsyncMock()
        embedding.embed.return_value = [0.1] * 128
        return PlanArchiveStore(db_path, vector_store=vector, embedding=embedding)

    @pytest.mark.asyncio
    async def test_recall_empty_db(self, store: PlanArchiveStore) -> None:
        recaller = PlanRecaller(store)
        result = await recaller.recall("build a web app")
        assert result == ""

    @pytest.mark.asyncio
    async def test_recall_fallback_with_data(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(goal="Build a web scraper for e-commerce", completed=3, num_steps=3)
        await store.archive_plan(plan)

        recaller = PlanRecaller(store)
        result = await recaller.recall("Build scraper")
        assert "Reference Plans" in result
        assert "Build a web scraper" in result

    @pytest.mark.asyncio
    async def test_recall_with_vector_search(self, store_with_vector: PlanArchiveStore) -> None:
        plan = _make_plan(goal="Analyze data pipeline", completed=3, num_steps=3)
        await store_with_vector.archive_plan(plan)

        mock_doc = MagicMock()
        mock_doc.document.id = "plan_12345"
        store_with_vector._vector_store.search.return_value = [mock_doc]

        recaller = PlanRecaller(store_with_vector)

        with patch.object(recaller, "_fetch_and_format", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = "## Reference Plans\nGoal: Test"
            result = await recaller.recall("Analyze some data")
            assert "Reference Plans" in result

    @pytest.mark.asyncio
    async def test_recall_vector_failure_fallback(self, store_with_vector: PlanArchiveStore) -> None:
        plan = _make_plan(goal="Deploy application to cloud", completed=3, num_steps=3)
        await store_with_vector.archive_plan(plan)

        store_with_vector._vector_store.search.side_effect = RuntimeError("connection lost")

        recaller = PlanRecaller(store_with_vector)
        result = await recaller.recall("Deploy application")
        assert "Reference Plans" in result or result == ""

    @pytest.mark.asyncio
    async def test_recall_returns_empty_no_match(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(goal="Build a web scraper", completed=3, num_steps=3)
        await store.archive_plan(plan)

        recaller = PlanRecaller(store)
        result = await recaller.recall("Quantum physics simulation")
        assert result == ""

    @pytest.mark.asyncio
    async def test_fetch_and_format(self, store: PlanArchiveStore) -> None:
        plan = _make_plan(goal="Test formatting", completed=3, num_steps=3)
        await store.archive_plan(plan)

        import sqlite3

        conn = sqlite3.connect(str(store._db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT plan_id FROM plan_archive").fetchall()
        conn.close()
        plan_ids = [row["plan_id"] for row in rows]

        recaller = PlanRecaller(store)
        result = await recaller._fetch_and_format(plan_ids)
        assert "Reference Plans" in result
        assert "Goal: Test formatting" in result


class TestConstants:
    def test_min_success_rate(self) -> None:
        assert MIN_SUCCESS_RATE == 0.8

    def test_similarity_threshold(self) -> None:
        assert SIMILARITY_THRESHOLD == 0.75

    def test_dedup_threshold(self) -> None:
        assert DEDUP_THRESHOLD == 0.95

    def test_vector_collection(self) -> None:
        assert VECTOR_COLLECTION == "plan_archive"
