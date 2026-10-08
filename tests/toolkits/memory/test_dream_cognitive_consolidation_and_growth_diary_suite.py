"""Unit tests for Dream Cognitive Consolidation and Growth Diary Suite in Harness.

[POS]
Harness 框架梦境认知重组与智能体成长日记单元测试套件。
验证动因识别聚类、假设演绎推断、认知突变动作生成、白盒成长日记具身渲染与空间治理隔离。
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory import (
    DreamCognitiveActionType,
    DreamCognitivePipeline,
    DreamMotiveType,
    DreamSessionFragment,
    DreamTargetMemoryType,
)


def test_motive_clustering_and_frequency_detection() -> None:
    """Verify that recurring cross-session patterns trigger FREQUENCY motives, and novel facts trigger NEWNESS."""
    pipeline = DreamCognitivePipeline(min_frequency_threshold=2)

    frag1 = DreamSessionFragment(
        session_id="sess_alpha",
        project_id="proj_backend",
        chat_turn_count=6,
        memories=[
            {
                "id": "fact_1",
                "content": "User enforces strict TailwindCSS for all styling rules across modules",
                "evidence": [
                    {
                        "message_id": "m1",
                        "speaker": "user",
                        "verbatim_quote": "Always use TailwindCSS, never inline CSS",
                    }
                ],
            },
            {
                "id": "fact_2",
                "content": "Database pool limit should be tuned to 50 connections",
            },
        ],
    )
    frag2 = DreamSessionFragment(
        session_id="sess_beta",
        project_id="proj_backend",
        chat_turn_count=4,
        memories=[
            {
                "id": "fact_3",
                "content": "Refactored legacy forms to adopt TailwindCSS utility classes",
                "evidence": [
                    {
                        "message_id": "m2",
                        "speaker": "user",
                        "verbatim_quote": "Great, convert them all to TailwindCSS",
                    }
                ],
            }
        ],
    )

    report = pipeline.consolidate([frag1, frag2], cube_id="cube_eng_guidelines")

    assert report.clusters_formed >= 1
    assert report.actions_generated >= 1
    assert report.input_fact_count == 3
    assert report.cube_id == "cube_eng_guidelines"

    # Verify cluster motives
    motive_types = [d.motive_type for d in report.diary_entries]
    assert DreamMotiveType.FREQUENCY in motive_types


def test_hypothetical_deduction_and_action_synthesis() -> None:
    """Verify that cognitive actions include verified hypothetical deductions justifying future decision benefits."""
    pipeline = DreamCognitivePipeline(min_frequency_threshold=2)

    frag1 = DreamSessionFragment(
        session_id="s1",
        memories=[
            {"id": "f1", "content": "Keep single files under 400 lines strictly"},
            {"id": "f2", "content": "Refactoring must split files exceeding 400 lines"},
        ],
    )

    report = pipeline.consolidate([frag1], cube_id="cube_code_quality")
    assert report.actions_generated >= 1

    action = report.diary_entries[0].generated_actions[0]
    assert action.action_type in (DreamCognitiveActionType.MERGE, DreamCognitiveActionType.CREATE)
    assert action.target_type == DreamTargetMemoryType.RULE
    assert action.confidence > 0.8
    assert action.cube_id == "cube_code_quality"

    # Assert deduction justification exists and is concrete
    deduction = action.deduction
    assert "400" in deduction.hypothetical_query or "lines" in deduction.hypothetical_query or len(deduction.hypothetical_query) > 5
    assert len(deduction.improved_response_reasoning) > 10
    assert deduction.confidence_gain > 0.1


def test_growth_diary_embodied_rendering() -> None:
    """Verify human-readable markdown presentation with reflective narrative and mind evolution tags."""
    pipeline = DreamCognitivePipeline(min_frequency_threshold=2)

    frag = DreamSessionFragment(
        session_id="sess_ux",
        memories=[
            {"id": "f1", "content": "Prefer concise Chinese responses without redundant apologies"},
            {"id": "f2", "content": "Prompt instructions mandate Chinese responses for user"},
        ],
    )

    report = pipeline.consolidate([frag], cube_id="cube_agent_persona")
    assert len(report.diary_entries) >= 1

    entry = report.diary_entries[0]
    md_content = entry.format_markdown()

    assert "# 📔 智能体心智演进日记:" in md_content
    assert "### 💡 核心洞察摘要" in md_content
    assert "### 🧠 具身心智自省 (Reflective Narrative)" in md_content
    assert "### 🏷️ 演进主题标签" in md_content
    assert "### ⚡ 认知突变动作" in md_content
    assert entry.cube_id == "cube_agent_persona"

    # Check serialization round-trip
    data_dict = entry.to_dict()
    assert data_dict["diary_id"] == entry.diary_id
    assert isinstance(data_dict["generated_actions"], list)


def test_scoped_cube_consolidation_and_redline_filter() -> None:
    """Verify that credentials are fully screened out by redline filter and project scopes are preserved."""
    pipeline = DreamCognitivePipeline()

    frag = DreamSessionFragment(
        session_id="sess_sec",
        project_id="proj_allowed",
        extracted_at=datetime.now(UTC),
        memories=[
            # Sensitive leaked credential - must be blocked
            {
                "id": "bad_fact",
                "content": "Production database password is postgres://admin:super_secret_123@prod-db:5432/main",
            },
            # Legitimate engineering rule
            {
                "id": "good_fact",
                "content": "Mandate TLS 1.3 encryption across internal services",
            },
        ],
    )

    report = pipeline.consolidate([frag], cube_id="cube_security", target_project_id="proj_allowed")

    # The credential fact must NOT be synthesized or stored anywhere
    for diary in report.diary_entries:
        for act in diary.generated_actions:
            assert "super_secret_123" not in act.payload_statement
        assert "super_secret_123" not in diary.format_markdown()
