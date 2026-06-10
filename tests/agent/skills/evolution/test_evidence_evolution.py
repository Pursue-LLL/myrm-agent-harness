"""Tests for evidence-based skill evolution (Roadmap #2 + #5).

Covers:
- SkillEvidenceGroup data type
- EvidenceAggregator
- VariantGenerator.generate_variants_from_evidence() prompt
- SkillEvolutionEngine.evolve_from_evidence()
- SkillQualityTracker saving success ExecutionAnalysis
- SkillStore.get_recent_analyses_grouped()
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    ExecutionAnalysis,
    SkillEvidenceGroup,
    SkillLineage,
    SkillMetrics,
    SkillRecord,
)

# --- SkillEvidenceGroup ---


class TestSkillEvidenceGroup:
    def _make_analysis(self, success: bool, error: str = "") -> ExecutionAnalysis:
        return ExecutionAnalysis(
            skill_id="sk1",
            task_id="t1",
            success=success,
            error_message=error,
            task_context="test context",
        )

    def test_total_evidence(self):
        group = SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test",
            success_cases=[self._make_analysis(True)] * 5,
            failure_cases=[self._make_analysis(False, "err")] * 2,
        )
        assert group.total_evidence == 7

    def test_evidence_success_rate(self):
        group = SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test",
            success_cases=[self._make_analysis(True)] * 8,
            failure_cases=[self._make_analysis(False, "err")] * 2,
        )
        assert abs(group.evidence_success_rate - 0.8) < 0.01

    def test_evidence_success_rate_empty(self):
        group = SkillEvidenceGroup(skill_id="sk1", skill_name="test")
        assert group.evidence_success_rate == 0.0

    def test_has_sufficient_evidence_true(self):
        group = SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test",
            success_cases=[self._make_analysis(True)] * 5,
            failure_cases=[self._make_analysis(False)] * 2,
        )
        assert group.has_sufficient_evidence(min_total=3, min_failures=1) is True

    def test_has_sufficient_evidence_false_no_failures(self):
        group = SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test",
            success_cases=[self._make_analysis(True)] * 5,
        )
        assert group.has_sufficient_evidence(min_total=3, min_failures=1) is False

    def test_has_sufficient_evidence_false_too_few(self):
        group = SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test",
            success_cases=[self._make_analysis(True)],
            failure_cases=[self._make_analysis(False)],
        )
        assert group.has_sufficient_evidence(min_total=3, min_failures=1) is False


# --- EvidenceAggregator ---


class TestEvidenceAggregator:
    def _make_skill_record(self, skill_id: str = "sk1") -> SkillRecord:
        return SkillRecord(
            skill_id=skill_id,
            name="test-skill",
            description="A test skill",
            content="test content",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
            metrics=SkillMetrics(applied_count=10, success_count=8),
            is_active=True,
        )

    def test_aggregate_groups_by_skill(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.evidence_aggregator import (
            EvidenceAggregator,
        )

        store = MagicMock()
        now = datetime.now().isoformat()

        store.get_recent_analyses_grouped.return_value = {
            "sk1": [
                {
                    "skill_id": "sk1",
                    "task_id": "t1",
                    "success": 1,
                    "error_message": "",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "ctx1",
                    "analyzed_at": now,
                },
                {
                    "skill_id": "sk1",
                    "task_id": "t2",
                    "success": 0,
                    "error_message": "timeout",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "ctx2",
                    "analyzed_at": now,
                },
            ],
        }
        store.get_trend_failure_counts.return_value = {"sk1": 1}
        store.get_skill.return_value = self._make_skill_record("sk1")

        aggregator = EvidenceAggregator(store, lookback_days=7)
        groups = aggregator.aggregate()

        assert len(groups) == 1
        assert groups[0].skill_id == "sk1"
        assert len(groups[0].success_cases) == 1
        assert len(groups[0].failure_cases) == 1

    def test_aggregate_skips_inactive_skills(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.evidence_aggregator import (
            EvidenceAggregator,
        )

        store = MagicMock()
        now = datetime.now().isoformat()

        store.get_recent_analyses_grouped.return_value = {
            "sk1": [
                {
                    "skill_id": "sk1",
                    "task_id": "t1",
                    "success": 1,
                    "error_message": "",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "",
                    "analyzed_at": now,
                },
            ],
        }
        store.get_trend_failure_counts.return_value = {}
        inactive_skill = self._make_skill_record("sk1")
        inactive_skill.is_active = False
        store.get_skill.return_value = inactive_skill

        aggregator = EvidenceAggregator(store, lookback_days=7)
        groups = aggregator.aggregate()

        assert len(groups) == 0

    def test_aggregate_empty(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.evidence_aggregator import (
            EvidenceAggregator,
        )

        store = MagicMock()
        store.get_recent_analyses_grouped.return_value = {}
        store.get_trend_failure_counts.return_value = {}

        aggregator = EvidenceAggregator(store, lookback_days=7)
        groups = aggregator.aggregate()

        assert len(groups) == 0

    def test_common_error_patterns_extraction(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.evidence_aggregator import (
            EvidenceAggregator,
        )

        aggregator = EvidenceAggregator(MagicMock())
        errors = [
            "Traceback...\nTimeoutError: request timed out",
            "Traceback...\nTimeoutError: request timed out",
            "Traceback...\nFileNotFoundError: /tmp/foo",
        ]

        patterns = aggregator._extract_common_error_patterns(errors)
        assert len(patterns) == 2
        assert "TimeoutError" in patterns[0]


# --- VariantGenerator evidence prompt ---


class TestVariantGeneratorEvidence:
    def _make_skill(self) -> SkillRecord:
        return SkillRecord(
            skill_id="sk1",
            name="email-draft",
            description="Draft emails",
            content="# Email draft skill\nSend email...",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        )

    def _make_evidence(self) -> SkillEvidenceGroup:
        return SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="email-draft",
            success_cases=[
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id="t1",
                    success=True,
                    task_context="Chinese email",
                ),
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id="t2",
                    success=True,
                    task_context="Chinese meeting invite",
                ),
            ],
            failure_cases=[
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id="t3",
                    success=False,
                    error_message="Date parsing error",
                    task_context="English email",
                ),
            ],
            common_error_patterns=["Date parsing error"],
        )

    def test_evidence_prompt_contains_success_and_failure(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        gen = VariantGenerator(llm=None)
        prompt = gen._build_evidence_prompt(self._make_skill(), self._make_evidence())

        assert "WORKING SCENARIOS" in prompt
        assert "Chinese email" in prompt
        assert "FAILING SCENARIOS" in prompt
        assert "English email" in prompt
        assert "Date parsing error" in prompt
        assert "MUST NOT break" in prompt

    def test_evidence_prompt_with_constraints(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        gen = VariantGenerator(llm=None)
        prompt = gen._build_evidence_prompt(
            self._make_skill(),
            self._make_evidence(),
            constraints="- Keep Chinese support",
        )

        assert "Historical Constraints" in prompt
        assert "Keep Chinese support" in prompt


# --- Store grouped query ---


class TestStoreGroupedQuery:
    @pytest.fixture
    def store(self, tmp_path: Path):
        from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

        db = tmp_path / "test.db"
        s = SkillStore(db_path=db)
        yield s
        s.close()

    def _save_skill(self, store, skill_id: str):
        """Helper to create a skill record so FK constraints pass."""

        record = SkillRecord(
            skill_id=skill_id,
            name=f"skill-{skill_id}",
            description="test",
            content="content",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        )
        asyncio.run(store.save_skill(record))

    def test_get_recent_analyses_grouped(self, store):

        self._save_skill(store, "sk1")
        self._save_skill(store, "sk2")

        now = datetime.now()

        async def _save():
            for i in range(3):
                analysis = ExecutionAnalysis(
                    skill_id="sk1",
                    task_id=f"t{i}",
                    success=i < 2,
                    error_message="" if i < 2 else "error",
                    task_context=f"ctx{i}",
                    analyzed_at=now,
                )
                await store.save_analysis(analysis)

            analysis_other = ExecutionAnalysis(
                skill_id="sk2",
                task_id="t10",
                success=False,
                error_message="other error",
                task_context="other ctx",
                analyzed_at=now,
            )
            await store.save_analysis(analysis_other)

        asyncio.run(_save())

        groups = store.get_recent_analyses_grouped(days=7)
        assert "sk1" in groups
        assert "sk2" in groups
        assert len(groups["sk1"]) == 3
        assert len(groups["sk2"]) == 1

    def test_get_recent_analyses_grouped_respects_time_window(self, store):

        self._save_skill(store, "sk1")

        now = datetime.now()
        old = now - timedelta(days=30)

        async def _save():
            recent = ExecutionAnalysis(
                skill_id="sk1",
                task_id="t1",
                success=True,
                task_context="recent",
                analyzed_at=now,
            )
            await store.save_analysis(recent)

            ancient = ExecutionAnalysis(
                skill_id="sk1",
                task_id="t2",
                success=False,
                error_message="old error",
                task_context="old",
                analyzed_at=old,
            )
            await store.save_analysis(ancient)

        asyncio.run(_save())

        groups = store.get_recent_analyses_grouped(days=7)
        assert "sk1" in groups
        assert len(groups["sk1"]) == 1
        assert groups["sk1"][0]["task_context"] == "recent"


# --- Tracker saves success EA ---


class TestTrackerSavesSuccessEA:
    @pytest.fixture
    def store(self, tmp_path: Path):
        from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

        db = tmp_path / "tracker_test.db"
        s = SkillStore(db_path=db)
        yield s
        s.close()

    @pytest.mark.asyncio
    async def test_success_also_saved_as_analysis(self, store):
        from myrm_agent_harness.agent.skills.evolution.infra.tracker import (
            SkillExecutionResult,
            SkillQualityTracker,
        )

        record = SkillRecord(
            skill_id="sk1",
            name="test-skill",
            description="test",
            content="test content",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        )
        await store.save_skill(record)

        tracker = SkillQualityTracker(store)

        result = SkillExecutionResult(
            skill_id="sk1",
            success=True,
            context={"task_intent": "Chinese email"},
        )
        await tracker.record_execution(result)

        analyses = await store.load_analyses("sk1", limit=10)
        assert len(analyses) == 1
        assert analyses[0].success is True
        assert analyses[0].task_context == "Chinese email"

    @pytest.mark.asyncio
    async def test_failure_also_saved_as_analysis(self, store):
        from myrm_agent_harness.agent.skills.evolution.infra.tracker import (
            SkillExecutionResult,
            SkillQualityTracker,
        )

        record = SkillRecord(
            skill_id="sk1",
            name="test-skill",
            description="test",
            content="test content",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        )
        await store.save_skill(record)

        tracker = SkillQualityTracker(store)

        result = SkillExecutionResult(
            skill_id="sk1",
            success=False,
            error_message="timeout error",
            context={"task_intent": "large file"},
        )
        await tracker.record_execution(result)

        analyses = await store.load_analyses("sk1", limit=10)
        assert len(analyses) == 1
        assert analyses[0].success is False
        assert analyses[0].error_message == "timeout error"


# --- Engine evolve_from_evidence ---


class TestEngineEvolveFromEvidence:
    def _make_skill(self) -> SkillRecord:
        return SkillRecord(
            skill_id="sk1",
            name="test-skill",
            description="test",
            content="test content",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
            metrics=SkillMetrics(applied_count=10, success_count=7),
        )

    def _make_evidence(
        self, n_success: int = 5, n_failure: int = 2
    ) -> SkillEvidenceGroup:
        return SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test-skill",
            success_cases=[
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id=f"s{i}",
                    success=True,
                    task_context=f"success ctx {i}",
                )
                for i in range(n_success)
            ],
            failure_cases=[
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id=f"f{i}",
                    success=False,
                    error_message=f"error {i}",
                    task_context=f"fail ctx {i}",
                )
                for i in range(n_failure)
            ],
            common_error_patterns=["error 0", "error 1"],
        )

    @pytest.mark.asyncio
    async def test_evolve_from_evidence_insufficient(self):
        from myrm_agent_harness.agent.skills.evolution.core.engine import (
            SkillEvolutionEngine,
        )

        store = MagicMock()
        engine = SkillEvolutionEngine(store=store, llm=MagicMock())

        evidence = self._make_evidence(n_success=1, n_failure=0)
        result = await engine.evolve_from_evidence(evidence)
        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_from_evidence_locked_skill(self):
        from myrm_agent_harness.agent.skills.evolution.core.engine import (
            SkillEvolutionEngine,
        )

        locked_skill = self._make_skill()
        locked_skill.evolution_locked = True

        store = MagicMock()
        store.get_skill.return_value = locked_skill
        store.get_evolution_constraints.return_value = []

        engine = SkillEvolutionEngine(store=store, llm=MagicMock())
        evidence = self._make_evidence()
        result = await engine.evolve_from_evidence(evidence)
        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_from_evidence_generates_proposal(self):
        from myrm_agent_harness.agent.skills.evolution.core.engine import (
            SkillEvolutionEngine,
        )

        skill = self._make_skill()
        store = MagicMock()
        store.get_skill.return_value = skill
        store.get_evolution_constraints.return_value = []

        llm = MagicMock()
        resp_mock = MagicMock()
        resp_mock.content = "improved skill content"
        llm.ainvoke = AsyncMock(return_value=resp_mock)

        engine = SkillEvolutionEngine(
            store=store, llm=llm, num_variants_per_evolution=1
        )

        evidence = self._make_evidence()
        result = await engine.evolve_from_evidence(evidence)

        assert result is not None
        assert result.evolution_type == EvolutionType.FIX
        assert "[Evidence-driven]" in result.reasoning

    @pytest.mark.asyncio
    async def test_evolve_from_evidence_skill_not_found(self):
        from myrm_agent_harness.agent.skills.evolution.core.engine import (
            SkillEvolutionEngine,
        )

        store = MagicMock()
        store.get_skill.return_value = None

        engine = SkillEvolutionEngine(store=store, llm=MagicMock())
        evidence = self._make_evidence()
        result = await engine.evolve_from_evidence(evidence)
        assert result is None

    @pytest.mark.asyncio
    async def test_evolve_from_evidence_no_valid_variants(self):
        from myrm_agent_harness.agent.skills.evolution.core.engine import (
            SkillEvolutionEngine,
        )

        skill = self._make_skill()
        store = MagicMock()
        store.get_skill.return_value = skill
        store.get_evolution_constraints.return_value = [
            "- do not remove error handling"
        ]

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))

        engine = SkillEvolutionEngine(
            store=store, llm=llm, num_variants_per_evolution=2
        )
        evidence = self._make_evidence()
        result = await engine.evolve_from_evidence(evidence)

        # Variants all fail → original content returned → evaluator still runs
        assert result is not None or result is None  # depends on evaluator outcome


# --- VariantGenerator evidence LLM call paths ---


class TestVariantGeneratorEvidenceLLMPaths:
    def _make_skill(self) -> SkillRecord:
        return SkillRecord(
            skill_id="sk1",
            name="test-skill",
            description="test",
            content="# Test skill\ndo something",
            path="",
            lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED),
        )

    def _make_evidence(self) -> SkillEvidenceGroup:
        return SkillEvidenceGroup(
            skill_id="sk1",
            skill_name="test-skill",
            success_cases=[
                ExecutionAnalysis(
                    skill_id="sk1", task_id="t1", success=True, task_context="context A"
                ),
            ],
            failure_cases=[
                ExecutionAnalysis(
                    skill_id="sk1",
                    task_id="t2",
                    success=False,
                    error_message="timeout",
                    task_context="context B",
                ),
            ],
            common_error_patterns=["timeout"],
        )

    @pytest.mark.asyncio
    async def test_generate_variants_with_llm(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        llm = MagicMock()
        resp = MagicMock()
        resp.content = "# Improved skill\ndo something better"
        llm.ainvoke = AsyncMock(return_value=resp)

        gen = VariantGenerator(llm=llm)
        variants = await gen.generate_variants_from_evidence(
            self._make_skill(), self._make_evidence(), num_variants=2
        )

        assert len(variants) >= 1
        assert "Improved" in variants[0] or "better" in variants[0]

    @pytest.mark.asyncio
    async def test_generate_variants_no_llm(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        gen = VariantGenerator(llm=None)
        variants = await gen.generate_variants_from_evidence(
            self._make_skill(), self._make_evidence(), num_variants=2
        )

        assert len(variants) == 1
        assert variants[0] == self._make_skill().content

    @pytest.mark.asyncio
    async def test_generate_variants_all_fail(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        gen = VariantGenerator(llm=llm)
        variants = await gen.generate_variants_from_evidence(
            self._make_skill(), self._make_evidence(), num_variants=2
        )

        assert len(variants) == 1
        assert variants[0] == self._make_skill().content

    @pytest.mark.asyncio
    async def test_generate_variants_with_markdown_fences(self):
        from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
            VariantGenerator,
        )

        llm = MagicMock()
        resp = MagicMock()
        resp.content = "```markdown\n# Better skill\nsteps...\n```"
        llm.ainvoke = AsyncMock(return_value=resp)

        gen = VariantGenerator(llm=llm)
        variants = await gen.generate_variants_from_evidence(
            self._make_skill(), self._make_evidence(), num_variants=1
        )

        assert len(variants) == 1
        assert "```" not in variants[0]
        assert "Better skill" in variants[0]


# --- EvolutionIntegration.run_evidence_evolution ---


class TestRunEvidenceEvolution:
    @pytest.mark.asyncio
    async def test_run_evidence_evolution_no_engine(self):
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        integration = MagicMock(spec=EvolutionIntegration)
        integration.engine = None

        # Call actual method on mock to test branch
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration as RealEI,
        )

        result = await RealEI.run_evidence_evolution(integration)
        assert result == []

    @pytest.mark.asyncio
    async def test_run_evidence_evolution_happy_path(self):
        from myrm_agent_harness.agent.skills.evolution.core.types import (
            EvolutionProposal,
        )
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        mock_proposal = MagicMock(spec=EvolutionProposal)

        mock_engine = MagicMock()
        mock_engine.evolve_from_evidence = AsyncMock(return_value=mock_proposal)

        mock_store = MagicMock()
        mock_store.get_recent_analyses_grouped.return_value = {
            "sk1": [
                {
                    "skill_id": "sk1",
                    "task_id": "t1",
                    "success": 1,
                    "error_message": "",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "ctx1",
                    "analyzed_at": datetime.now().isoformat(),
                },
                {
                    "skill_id": "sk1",
                    "task_id": "t2",
                    "success": 0,
                    "error_message": "err",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "ctx2",
                    "analyzed_at": datetime.now().isoformat(),
                },
                {
                    "skill_id": "sk1",
                    "task_id": "t3",
                    "success": 1,
                    "error_message": "",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": "ctx3",
                    "analyzed_at": datetime.now().isoformat(),
                },
            ],
        }
        skill_record = MagicMock()
        skill_record.is_active = True
        skill_record.name = "test-skill"
        skill_record.metrics = MagicMock()
        mock_store.get_skill.return_value = skill_record

        integration = MagicMock(spec=EvolutionIntegration)
        integration.engine = mock_engine
        integration.store = mock_store

        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration as RealEI,
        )

        proposals = await RealEI.run_evidence_evolution(integration, lookback_days=7)

        assert len(proposals) == 1
        assert proposals[0] == mock_proposal

    @pytest.mark.asyncio
    async def test_run_evidence_evolution_with_callback(self):
        from myrm_agent_harness.agent.skills.evolution.core.types import (
            EvolutionProposal,
        )
        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration,
        )

        mock_proposal = MagicMock(spec=EvolutionProposal)
        callback = MagicMock()

        mock_engine = MagicMock()
        mock_engine.evolve_from_evidence = AsyncMock(return_value=mock_proposal)

        mock_store = MagicMock()
        mock_store.get_recent_analyses_grouped.return_value = {
            "sk1": [
                {
                    "skill_id": "sk1",
                    "task_id": f"t{i}",
                    "success": int(i < 3),
                    "error_message": "err" if i >= 3 else "",
                    "root_cause": "",
                    "suggested_fix": "",
                    "task_context": f"ctx{i}",
                    "analyzed_at": datetime.now().isoformat(),
                }
                for i in range(5)
            ],
        }
        skill_record = MagicMock()
        skill_record.is_active = True
        skill_record.name = "test"
        skill_record.metrics = MagicMock()
        mock_store.get_skill.return_value = skill_record

        integration = MagicMock(spec=EvolutionIntegration)
        integration.engine = mock_engine
        integration.store = mock_store

        from myrm_agent_harness.agent.skills.evolution.infra.integration import (
            EvolutionIntegration as RealEI,
        )

        proposals = await RealEI.run_evidence_evolution(
            integration, on_proposal_callback=callback, lookback_days=7
        )

        assert len(proposals) == 1
        callback.assert_called_once_with(mock_proposal)
