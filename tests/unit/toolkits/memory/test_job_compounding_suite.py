"""[POS]: tests/unit/toolkits/memory/test_job_compounding_suite.py
[INPUT]: Temporary agent memory directory, 4-pillar job specs, feedback rules, and actions.
[OUTPUT]: Comprehensive test assertions verifying job builder, compounding engine, and maturity tracker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory import (
    CompoundingMaturityTracker,
    JobDescriptionBuilder,
    MaturityTier,
    PreferenceCompoundingEngine,
    RuleType,
)


@pytest.fixture
def temp_memory_dir(tmp_path: Path) -> Path:
    """Fixture providing isolated temporary directory for agent domain memory storage."""
    return tmp_path / "agent_memory_store"


def test_job_description_builder_and_boundary_evaluation() -> None:
    """Verify 4-pillar job description spec building, boundary evaluation, and contract rendering."""
    spec = JobDescriptionBuilder.build_spec(
        agent_id="agent_talent_scout_01",
        job_title="Talent Scout",
        target_scope="Monitor candidate platforms and identify senior distributed systems architects.",
        tools_and_sources=["github_crawler", "linkedin_scraper", "resume_parser"],
        work_style="concise, evidence-driven, high-bar",
        autonomous_actions=["search_candidates", "parse_resume", "generate_brief", "tag_profile"],
        requires_approval_actions=["send_interview_invite", "reject_executive_candidate", "export_pii_docket"],
    )

    assert spec.agent_id == "agent_talent_scout_01"
    assert spec.job_title == "Talent Scout"
    assert len(spec.tools_and_sources) == 3

    # 1. Test action boundary - explicit autonomous action
    needs_appr, reason = JobDescriptionBuilder.evaluate_action_boundary(spec, "search_candidates")
    assert needs_appr is False
    assert "autonomous_actions" in reason

    # 2. Test action boundary - explicit requires approval action
    needs_appr_high, reason_high = JobDescriptionBuilder.evaluate_action_boundary(
        spec, "send_interview_invite"
    )
    assert needs_appr_high is True
    assert "requires_approval_actions" in reason_high

    # 3. Test action boundary - implicit mutation cue without explicit grant
    needs_appr_mut, reason_mut = JobDescriptionBuilder.evaluate_action_boundary(
        spec, "delete_candidate_record"
    )
    assert needs_appr_mut is True
    assert "mutation detected" in reason_mut

    # 4. Test action boundary - safe read-only inspection
    needs_appr_read, _reason_read = JobDescriptionBuilder.evaluate_action_boundary(
        spec, "read_candidate_profile"
    )
    assert needs_appr_read is False

    # 5. Test prompt contract rendering
    contract = JobDescriptionBuilder.render_system_contract(spec)
    assert "## Role Job Description: Talent Scout" in contract
    assert "Pillar 1" in contract or "Target Scope" in contract
    assert "search_candidates" in contract
    assert "send_interview_invite" in contract


def test_preference_compounding_engine_and_memory_file_sync(temp_memory_dir: Path) -> None:
    """Verify rule extraction, deduplication, physical MEMORY.md sync, and prompt rendering."""
    engine = PreferenceCompoundingEngine(base_storage_dir=temp_memory_dir)
    agent_id = "agent_expense_mgr_02"

    # 1. Record positive preference
    rule1 = engine.record_rule(
        agent_id=agent_id,
        rule_type=RuleType.POSITIVE_PREFERENCE,
        statement="Prioritize electronic tax receipts with valid QR verification codes.",
        trigger_condition="Invoice verification during reimbursement review",
        evidence_source="Review session #1024 audit log",
    )
    assert rule1.rule_type == RuleType.POSITIVE_PREFERENCE
    assert rule1.hit_count == 1

    # Check physical MEMORY.md creation
    expected_file = temp_memory_dir / agent_id / "MEMORY.md"
    assert expected_file.is_file()
    content = expected_file.read_text(encoding="utf-8")
    assert "Positive Preferences" in content
    assert "electronic tax receipts" in content

    # 2. Record negative constraint
    rule2 = engine.record_rule(
        agent_id=agent_id,
        rule_type=RuleType.NEGATIVE_CONSTRAINT,
        statement="Never approve travel claims exceeding $500 per day without pre-flight travel order.",
        trigger_condition="Business trip per-diem processing",
        evidence_source="CFO finance policy amendment 2026",
    )
    assert rule2.rule_type == RuleType.NEGATIVE_CONSTRAINT

    # 3. Record inspection lesson
    rule3 = engine.record_rule(
        agent_id=agent_id,
        rule_type=RuleType.INSPECTION_LESSON,
        statement="If exchange rate is missing, fallback to PBOC central parity rate on transaction date.",
        trigger_condition="Multi-currency invoice conversion",
        evidence_source="Expense audit case #88",
    )
    assert rule3.rule_type == RuleType.INSPECTION_LESSON

    # 4. Deduplication: recording identical statement increases hit count
    rule1_dup = engine.record_rule(
        agent_id=agent_id,
        rule_type=RuleType.POSITIVE_PREFERENCE,
        statement="Prioritize electronic tax receipts with valid QR verification codes.",
        trigger_condition="Different turn observation",
        evidence_source="Follow-up audit",
    )
    assert rule1_dup.rule_id == rule1.rule_id
    assert rule1_dup.hit_count == 2

    # 5. List rules
    all_rules = engine.list_rules(agent_id)
    assert len(all_rules) == 3

    constraints = engine.list_rules(agent_id, rule_type=RuleType.NEGATIVE_CONSTRAINT)
    assert len(constraints) == 1
    assert constraints[0].rule_id == rule2.rule_id

    # 6. Render domain memory prompt
    prompt = engine.render_domain_memory_prompt(agent_id)
    assert "Accumulated Domain Lessons" in prompt
    assert "[PREFERENCE]" in prompt
    assert "[CONSTRAINT]" in prompt
    assert "[LESSON]" in prompt


def test_compounding_maturity_tracker() -> None:
    """Verify progressive maturity score calculation, tier promotion, and report generation."""
    spec = JobDescriptionBuilder.build_spec(
        agent_id="agent_bug_repro_03",
        job_title="Bug Reproduction Specialist",
        target_scope="Reproduce concurrency defects, isolate race conditions, and minimize test repros.",
        tools_and_sources=["docker_sandbox", "pytest_runner", "strace_profiler"],
        work_style="methodical, deterministic, minimal",
    )

    engine = PreferenceCompoundingEngine()

    # 1. No rules -> Rookie
    empty_rules = engine.list_rules(spec.agent_id)
    report_empty = CompoundingMaturityTracker.evaluate_maturity(spec, empty_rules)
    assert report_empty.maturity_score == 0.0
    assert report_empty.tier == MaturityTier.ROOKIE
    assert "Rookie" in report_empty.summary

    # 2. Add multiple diverse rules to promote to Practitioner and Specialist
    for i in range(5):
        engine.record_rule(
            agent_id=spec.agent_id,
            rule_type=RuleType.POSITIVE_PREFERENCE,
            statement=f"Always run tests with -s --timeout=10 flag for reproduction pattern {i}.",
            trigger_condition="Pytest invocation",
            evidence_source=f"Case {i}",
        )
    for i in range(3):
        engine.record_rule(
            agent_id=spec.agent_id,
            rule_type=RuleType.NEGATIVE_CONSTRAINT,
            statement=f"Do not share global sqlite connection across threads in pattern {i}.",
            trigger_condition="Database race testing",
            evidence_source=f"Bug issue #{i}",
        )
    for i in range(3):
        engine.record_rule(
            agent_id=spec.agent_id,
            rule_type=RuleType.INSPECTION_LESSON,
            statement=f"Use strace -e trace=network to spot dropped SYN packets in pattern {i}.",
            trigger_condition="Network stall debugging",
            evidence_source=f"Incident report #{i}",
        )

    active_rules = engine.list_rules(spec.agent_id)
    assert len(active_rules) == 11

    report_promoted = CompoundingMaturityTracker.evaluate_maturity(spec, active_rules)
    assert report_promoted.total_rules_count == 11
    assert report_promoted.positive_preferences_count == 5
    assert report_promoted.negative_constraints_count == 3
    assert report_promoted.inspection_lessons_count == 3
    # Volume: 11 * 2 = 22; Diversity: 3 * 10 = 30; Usage: 11 * 1.5 = 16.5 -> total ~ 68.5
    assert report_promoted.maturity_score >= 50.0
    assert report_promoted.tier in (MaturityTier.SPECIALIST, MaturityTier.PARTNER)
    assert "Specialist" in report_promoted.summary or "Partner" in report_promoted.summary
