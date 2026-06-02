from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.execution.evaluator import BatchEvaluator
from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
    SkillCaptureResult,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
    VariantGenerator,
)

# --- Mock Data ---
MOCK_SKILL = SkillRecord(
    skill_id="mock-1",
    name="mock-skill",
    description="A mock skill",
    content="## Instructions\n1. Do something.",
    path="/fake/path",
    lineage=None,
    evolution_locked=False,
)


# --- 1. Test Evaluator (Sandbox Dry-Run) ---
@pytest.mark.asyncio
async def test_evaluator_dry_run_validation():
    # Setup mock LLM that always passes the initial score
    mock_llm = MagicMock()

    # Mock return values for ainvoke (it should return an object with .content string)
    from myrm_agent_harness.agent.skills.evolution.execution.evaluator import (
        SkillEvaluationRubric,
    )

    mock_rubric = SkillEvaluationRubric(
        accuracy_score=1.0,
        anti_fragmentation_score=1.0,
        redundancy_score=1.0,
        is_general=True,
        reasoning="Looks good",
    )

    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=mock_rubric)
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    evaluator = BatchEvaluator(mock_llm)

    # Variant 1: Good Python code
    good_variant = "```python\nprint('Hello')\nx = 1\n```"
    # Variant 2: Bad Python code (SyntaxError)
    bad_variant = "```python\nprint('Hello'\nx = 1\n```"  # Missing parenthesis

    variants = [good_variant, bad_variant]

    best, score, _reason, is_general = await evaluator.evaluate_variants(
        MOCK_SKILL, variants, "feedback", "trace"
    )

    # Evaluator should pick the good variant, because the bad one gets 0 score due to AST failure
    assert best == good_variant
    assert score == 1.0
    assert is_general is True


# --- 2. Test VariantGenerator (Constraint Injection) ---
@pytest.mark.asyncio
async def test_variant_generator_constraint_injection():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        side_effect=[
            MagicMock(content="Variant 1"),
            MagicMock(content="Variant 2"),
            MagicMock(content="Variant 3"),
        ]
    )
    generator = VariantGenerator(mock_llm)

    constraints = "- Do not use requests\n- Do not use bs4"
    variants = await generator.generate_variants(
        MOCK_SKILL, "feedback", "trace", num_variants=3, constraints=constraints
    )

    assert len(variants) == 3
    # Check if constraints were in the prompt
    call_args = mock_llm.ainvoke.call_args[0][0]
    prompt_text = call_args[0].content
    assert "Historical Constraints" in prompt_text
    assert "- Do not use requests" in prompt_text


# --- 3. Test Engine (Orchestration & CAPTURED type) ---
@pytest.mark.asyncio
async def test_engine_capture_skill_from_trajectory():
    # Mock store
    mock_store = MagicMock(spec=SkillStore)
    mock_store.get_active_skills.return_value = []  # No duplicates

    # Mock LLM
    mock_llm = MagicMock()

    engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)

    mock_result = SkillCaptureResult(
        is_general=True,
        confidence=0.9,
        safety_analysis="Safe",
        name="test-skill",
        content="## Instructions\n1. Do something.",
    )

    # Mock StructuredExtractor and SandboxValidator
    with (
        patch(
            "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
        ) as MockExtractor,
        patch(
            "myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.SandboxValidator"
        ) as MockSandbox,
    ):
        instance = MockExtractor.return_value
        instance.extract_from_trajectory = AsyncMock(return_value=mock_result)

        sandbox_instance = MockSandbox.return_value
        sandbox_instance.dry_run_skill = AsyncMock(return_value=(True, "Passed"))

        proposal = await engine.capture_skill_from_trajectory(
            "some trajectory", "session-123"
        )

    assert proposal is not None
    assert proposal.evolution_type == EvolutionType.CAPTURED
    assert proposal.proposed_content == "## Instructions\n1. Do something."
    assert proposal.score == 0.9
    assert proposal.is_general is True

@pytest.mark.asyncio
async def test_engine_extract_skill_from_slice():
    mock_store = MagicMock(spec=SkillStore)
    mock_store.get_active_skills.return_value = []
    mock_llm = MagicMock()

    mock_slice_result = MagicMock()
    mock_slice_result.is_coherent = True
    mock_slice_result.formatted_trace = "some trace"

    mock_result = SkillCaptureResult(
        is_general=True,
        confidence=0.9,
        safety_analysis="Safe",
        name="test-skill",
        content="## Instructions\n1. Do something.",
    )

    with (
        patch("myrm_agent_harness.agent.skills.evolution.core.engine.TraceAnalyzer") as MockTraceAnalyzer,
        patch("myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor") as MockExtractor,
        patch("myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.SandboxValidator") as MockSandbox,
    ):
        engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm, event_log_backend=MagicMock())
        trace_instance = MockTraceAnalyzer.return_value
        trace_instance.analyze_slice = AsyncMock(return_value=mock_slice_result)

        extractor_instance = MockExtractor.return_value
        extractor_instance.extract_from_trajectory = AsyncMock(return_value=mock_result)

        sandbox_instance = MockSandbox.return_value
        sandbox_instance.dry_run_skill = AsyncMock(return_value=(True, "Passed"))

        proposal = await engine.extract_skill_from_slice("session-123", ["call_1", "call_2"], "agent-1")

    assert proposal is not None
    assert proposal.evolution_type == EvolutionType.SLICE_EXTRACTION
    assert proposal.agent_id == "agent-1"


@pytest.mark.asyncio
async def test_engine_extract_skill_from_slice_incoherent():
    mock_store = MagicMock(spec=SkillStore)
    mock_llm = MagicMock()

    mock_slice_result = MagicMock()
    mock_slice_result.is_coherent = False

    with patch("myrm_agent_harness.agent.skills.evolution.core.engine.TraceAnalyzer") as MockTraceAnalyzer:
        engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm, event_log_backend=MagicMock())
        trace_instance = MockTraceAnalyzer.return_value
        trace_instance.analyze_slice = AsyncMock(return_value=mock_slice_result)

        proposal = await engine.extract_skill_from_slice("session-123", ["call_1"], "agent-1")

    assert proposal is None

    @pytest.mark.asyncio
    async def test_engine_fix_skill_with_constraints():
        # Mock store
        mock_store = MagicMock(spec=SkillStore)
        mock_store.get_skill.return_value = MOCK_SKILL
        mock_store.get_evolution_constraints.return_value = ["Must be fast"]

        from myrm_agent_harness.agent.skills.evolution.execution.evaluator import (
            SkillEvaluationRubric,
        )

        async def fake_ainvoke(messages, **kwargs):
            content = messages[0].content
            if "expert AI agent skill optimizer" in content:
                return MagicMock(content="Fixed Variant")
            else:
                return SkillEvaluationRubric(
                    accuracy_score=0.85,
                    anti_fragmentation_score=1.0,
                    redundancy_score=1.0,
                    is_general=True,
                    reasoning="fixed",
                )

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

        engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)

        proposal = await engine.fix_skill("mock-1", "error")

        assert proposal is not None
        assert proposal.evolution_type == EvolutionType.FIX
        assert proposal.proposed_content == "Fixed Variant"
        assert proposal.score >= 0.85

    @pytest.mark.asyncio
    async def test_engine_derive_skill_simple():
        mock_store = MagicMock(spec=SkillStore)
        mock_store.get_skill.return_value = MOCK_SKILL
        mock_store.get_evolution_constraints.return_value = []

        from myrm_agent_harness.agent.skills.evolution.execution.evaluator import (
            SkillEvaluationRubric,
        )

        async def fake_ainvoke(messages, **kwargs):
            content = messages[0].content
            if "expert AI agent skill optimizer" in content:
                return MagicMock(content="Derived Variant")
            else:
                return SkillEvaluationRubric(
                    accuracy_score=0.90,
                    anti_fragmentation_score=1.0,
                    redundancy_score=1.0,
                    is_general=True,
                    reasoning="derived",
                )

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)

        mock_structured_llm = MagicMock()
        mock_structured_llm.ainvoke = AsyncMock(side_effect=fake_ainvoke)
        mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

        engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)

        proposal = await engine.derive_skill_simple("mock-1", "Make it better")

        assert proposal is not None
        assert proposal.evolution_type == EvolutionType.DERIVED
        assert proposal.proposed_content == "Derived Variant"
        assert proposal.score >= 0.90


@pytest.mark.asyncio
async def test_evaluator_syntax_error_validation():
    mock_llm = MagicMock()
    evaluator = BatchEvaluator(mock_llm)

    # Missing parenthesis
    is_valid, reason = evaluator._dry_run_validation("```python\nprint('Hello'\n```")
    assert is_valid is False
    assert "SyntaxError" in reason

    # Hallucinated import (now caught by advanced import check)
    is_valid, reason = evaluator._dry_run_validation(
        "```python\nimport this_does_not_exist\n```"
    )
    assert is_valid is False
    assert "ModuleNotFoundError" in reason


@pytest.mark.asyncio
async def test_variant_generator_error_handling():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))
    generator = VariantGenerator(mock_llm)

    variants = await generator.generate_variants(
        MOCK_SKILL, "feedback", "trace", num_variants=1
    )

    # Should fallback to original skill
    assert len(variants) == 1
    assert variants[0] == MOCK_SKILL.content


@pytest.mark.asyncio
async def test_engine_evolve_multiple_concurrent():
    from myrm_agent_harness.agent.skills.evolution.core.types import (
        EvolutionRequest,
        EvolutionType,
    )

    mock_store = MagicMock(spec=SkillStore)
    mock_store.get_skill.return_value = MOCK_SKILL
    mock_store.get_evolution_constraints.return_value = []

    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(
        return_value=MagicMock(content="SCORE: 0.95\nREASON: Looks good\nGENERAL: True")
    )

    engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)

    req1 = EvolutionRequest(
        skill_id="mock-1",
        evolution_type=EvolutionType.FIX,
        reason="error",
        repeated_commands=[],
    )
    req2 = EvolutionRequest(
        skill_id="mock-1",
        evolution_type=EvolutionType.DERIVED,
        user_feedback="optimize",
        repeated_commands=[],
    )

    results = await engine.evolve_multiple_concurrent([req1, req2])

    assert len(results) == 2
    # Just asserting it processes them, individual details tested above
    assert results[0].evolution_type == EvolutionType.FIX
    assert results[1].evolution_type == EvolutionType.DERIVED

    # test empty
    empty_res = await engine.evolve_multiple_concurrent([])
    assert empty_res == []


@pytest.mark.asyncio
async def test_engine_capture_skill_edge_cases():
    mock_store = MagicMock(spec=SkillStore)
    mock_store.get_active_skills.return_value = []

    # 1. No LLM
    engine_no_llm = SkillEvolutionEngine(store=mock_store, llm=None)
    assert await engine_no_llm.capture_skill_from_trajectory("t", "1") is None

    # 2. No valid extraction
    mock_llm = MagicMock()
    engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)
    with patch(
        "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
    ) as MockExtractor:
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(
            return_value=None
        )
        assert await engine.capture_skill_from_trajectory("t", "2") is None

    # 3. Not general
    with patch(
        "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
    ) as MockExtractor:
        res = SkillCaptureResult(
            is_general=False, confidence=1.0, safety_analysis="", name="x", content="x"
        )
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(return_value=res)
        assert await engine.capture_skill_from_trajectory("t", "3") is None

    # 4. Low confidence
    with patch(
        "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
    ) as MockExtractor:
        res = SkillCaptureResult(
            is_general=True, confidence=0.5, safety_analysis="", name="x", content="x"
        )
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(return_value=res)
        assert await engine.capture_skill_from_trajectory("t", "4") is None

    # 5. Validation failure
    with (
        patch(
            "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
        ) as MockExtractor,
        patch(
            "myrm_agent_harness.agent.skills.evolution.safety.validator.SkillValidator"
        ) as MockValidator,
    ):
        res = SkillCaptureResult(
            is_general=True, confidence=0.9, safety_analysis="", name="x", content="x"
        )
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(return_value=res)
        MockValidator.return_value.validate.return_value = MagicMock(
            valid=False, errors=["err"]
        )
        assert await engine.capture_skill_from_trajectory("t", "5") is None

    # 6. Sandbox dry-run failure
    with (
        patch(
            "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
        ) as MockExtractor,
        patch(
            "myrm_agent_harness.agent.skills.evolution.safety.validator.SkillValidator"
        ) as MockValidator,
        patch(
            "myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.SandboxValidator"
        ) as MockSandbox,
    ):
        res = SkillCaptureResult(
            is_general=True, confidence=0.9, safety_analysis="", name="x", content="x"
        )
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(return_value=res)
        MockValidator.return_value.validate.return_value = MagicMock(valid=True)
        MockSandbox.return_value.dry_run_skill = AsyncMock(
            return_value=(False, "Failed")
        )
        assert await engine.capture_skill_from_trajectory("t", "6") is None


@pytest.mark.asyncio
async def test_engine_capture_skill_deduplication():
    mock_store = MagicMock(spec=SkillStore)

    # Create an active skill that is highly similar
    active_skill = SkillRecord(
        skill_id="mock",
        name="mock-skill",
        description="mock",
        content="## Instructions\n1. Exactly the same thing.",
        path="",
        lineage=None,
        evolution_locked=False,  # type: ignore
    )
    mock_store.get_active_skills.return_value = [active_skill]

    engine = SkillEvolutionEngine(store=mock_store, llm=MagicMock())

    with patch(
        "myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor.StructuredExtractor"
    ) as MockExtractor:
        # Same content should trigger dedup
        res = SkillCaptureResult(
            is_general=True,
            confidence=0.9,
            safety_analysis="",
            name="test-skill",
            content="## Instructions\n1. Exactly the same thing.",
        )
        MockExtractor.return_value.extract_from_trajectory = AsyncMock(return_value=res)

        proposal = await engine.capture_skill_from_trajectory("t", "1")
        assert proposal is None  # Rejected due to deduplication


@pytest.mark.asyncio
async def test_engine_fix_derive_not_found_or_locked():
    mock_store = MagicMock(spec=SkillStore)
    mock_store.get_skill.return_value = None

    engine = SkillEvolutionEngine(store=mock_store, llm=MagicMock())

    assert await engine.fix_skill("not-exist", "err") is None
    assert await engine.derive_skill_simple("not-exist", "fb") is None

    locked_skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="mock",
        path="",
        lineage=None,
        evolution_locked=True,  # type: ignore
    )
    mock_store.get_skill.return_value = locked_skill
    assert await engine.fix_skill("mock", "err") is None
    assert await engine.derive_skill_simple("mock", "fb") is None


# --- Tests for OPTIMIZE_DESCRIPTION pipeline ---


@pytest.mark.asyncio
async def test_proposal_builder_optimize_description_semantics():
    """ProposalBuilder uses skill.description (not content) for OPTIMIZE_DESCRIPTION."""
    from myrm_agent_harness.agent.skills.evolution.core.proposal_builder import (
        ProposalBuilder,
    )

    builder = ProposalBuilder()
    skill = SkillRecord(
        skill_id="s1",
        name="test-skill",
        description="Old description for matching",
        content="## Full Skill Body\n1. Step one\n2. Step two",
        path="/fake",
        lineage=None,
    )
    proposal = builder.build_proposal(
        skill=skill,
        evolution_type=EvolutionType.OPTIMIZE_DESCRIPTION,
        best_variant="Use when: coding tasks. NOT for: writing tasks.",
        score=0.85,
        reasoning="Better triggers",
        is_general=True,
    )
    assert proposal.original_content == "Old description for matching"
    assert proposal.proposed_content == "Use when: coding tasks. NOT for: writing tasks."
    assert "Old description" in proposal.diff
    assert "Use when:" in proposal.diff
    assert "## Full Skill Body" not in proposal.original_content


@pytest.mark.asyncio
async def test_proposal_builder_split_edit_summary():
    """ProposalBuilder correctly extracts edit_summary from variant content."""
    from myrm_agent_harness.agent.skills.evolution.core.proposal_builder import (
        ProposalBuilder,
    )

    builder = ProposalBuilder()
    skill = SkillRecord(
        skill_id="s1",
        name="test-skill",
        description="desc",
        content="original content",
        path="/fake",
        lineage=None,
    )
    variant_with_summary = (
        'Updated skill content here\n---EDIT_SUMMARY---\n'
        '{"preserved_sections": ["setup"], "changed_sections": ["validation"], "notes": "fixed"}'
    )
    proposal = builder.build_proposal(
        skill=skill,
        evolution_type=EvolutionType.FIX,
        best_variant=variant_with_summary,
        score=0.9,
        reasoning="Good fix",
    )
    assert proposal.proposed_content == "Updated skill content here"
    assert proposal.edit_summary is not None
    assert proposal.edit_summary["changed_sections"] == ["validation"]


@pytest.mark.asyncio
async def test_evaluator_strip_edit_summary():
    """BatchEvaluator._strip_edit_summary removes the metadata block."""
    evaluator = BatchEvaluator(llm=None)
    content_with_summary = (
        "Skill content body\n---EDIT_SUMMARY---\n"
        '{"preserved_sections": ["all"]}'
    )
    stripped = evaluator._strip_edit_summary(content_with_summary)
    assert stripped == "Skill content body"
    assert "EDIT_SUMMARY" not in stripped

    content_without = "Clean skill content"
    assert evaluator._strip_edit_summary(content_without) == "Clean skill content"


@pytest.mark.asyncio
async def test_evaluate_description_variants():
    """evaluate_description_variants scores description variants."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = '{"score": 0.9, "reasoning": "Good triggers"}'
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

    evaluator = BatchEvaluator(llm=mock_llm)
    skill = SkillRecord(
        skill_id="s1",
        name="test-skill",
        description="Old desc",
        content="body",
        path="/fake",
        lineage=None,
    )
    variants = [
        "Use when: X tasks. NOT for: Y tasks.",
        "Use when: A tasks. NOT for: B tasks.",
    ]
    best_desc, score, _reason, is_general = await evaluator.evaluate_description_variants(
        original_skill=skill, variants=variants
    )
    assert best_desc in variants
    assert score == 0.9
    assert is_general is True


@pytest.mark.asyncio
async def test_generate_description_variants():
    """VariantGenerator.generate_description_variants generates desc variants."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = "Use when: coding. NOT for: math."
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

    gen = VariantGenerator(llm=mock_llm)
    skill = SkillRecord(
        skill_id="s1",
        name="code-helper",
        description="Helps with code",
        content="## Body",
        path="/fake",
        lineage=None,
    )
    variants = await gen.generate_description_variants(skill=skill, num_variants=2)
    assert len(variants) == 2
    assert all("Use when:" in v for v in variants)


@pytest.mark.asyncio
async def test_engine_optimize_description():
    """SkillEvolutionEngine.optimize_description produces correct proposal."""
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = "Use when: deployment. NOT for: testing."
    mock_llm.ainvoke = AsyncMock(return_value=mock_resp)

    desc_eval_resp = MagicMock()
    desc_eval_resp.content = '{"score": 0.88, "reasoning": "Precise triggers"}'
    mock_llm.ainvoke = AsyncMock(return_value=desc_eval_resp)

    mock_store = MagicMock(spec=SkillStore)
    skill = SkillRecord(
        skill_id="s1",
        name="deploy-skill",
        description="Deploys stuff",
        content="## Deploy Guide\n1. Run deploy",
        path="/fake",
        lineage=None,
        evolution_locked=False,
    )
    mock_store.get_skill.return_value = skill

    engine = SkillEvolutionEngine(store=mock_store, llm=mock_llm)
    proposal = await engine.optimize_description(skill_id="s1")

    assert proposal is not None
    assert proposal.evolution_type == EvolutionType.OPTIMIZE_DESCRIPTION
    assert proposal.original_content == "Deploys stuff"
    assert proposal.proposed_content != ""
    assert proposal.is_general is True


@pytest.mark.asyncio
async def test_engine_select_evolution_action():
    """_select_evolution_action routes to OPTIMIZE_DESCRIPTION on high fallback + high effective."""
    from myrm_agent_harness.agent.skills.evolution.core.types import (
        SkillEvidenceGroup,
        SkillMetrics,
    )

    skill = SkillRecord(
        skill_id="s1",
        name="test",
        description="desc",
        content="body",
        path="",
        lineage=None,
    )
    skill.metrics = SkillMetrics(
        total_selections=10,
        applied_count=6,
        completed_count=6,
        success_count=5,
    )

    evidence = SkillEvidenceGroup(
        skill_id="s1",
        skill_name="test",
        metrics_snapshot=SkillMetrics(
            total_selections=10,
            applied_count=6,
            completed_count=6,
            success_count=5,
        ),
    )

    action = SkillEvolutionEngine._select_evolution_action(skill, evidence)
    assert action == EvolutionType.OPTIMIZE_DESCRIPTION

    evidence_low_fallback = SkillEvidenceGroup(
        skill_id="s1",
        skill_name="test",
        metrics_snapshot=SkillMetrics(
            total_selections=10,
            applied_count=10,
            completed_count=10,
            success_count=3,
        ),
    )
    action2 = SkillEvolutionEngine._select_evolution_action(skill, evidence_low_fallback)
    assert action2 == EvolutionType.FIX
