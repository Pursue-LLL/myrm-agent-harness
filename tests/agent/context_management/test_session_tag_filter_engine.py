# ============================================================================
# Unit Tests for SessionTagFilterEngine (Item 156)
# Verifies tag catalog registration, session tag associations, multi-dimensional
# metadata filtering (ANY/ALL/EXACT), semantic auto-tagging, and analytics.
# ============================================================================

from __future__ import annotations

import time

from myrm_agent_harness.agent.context_management.tagging import (
    SessionFilterQuery,
    SessionTag,
    SessionTagFilterEngine,
    TagCategory,
    TagColor,
    TaggedSessionItem,
    TagMatchMode,
)


def test_tag_registration_and_catalog() -> None:
    """Verifies tag registration, normalization, and catalog lookups."""
    engine = SessionTagFilterEngine()

    tag_fix = engine.register_tag(
        name="BugFix",
        color=TagColor.RED,
        category=TagCategory.TASK_TYPE,
        description="Bug fix resolution",
    )

    assert tag_fix.name == "BugFix"
    assert tag_fix.color == TagColor.RED
    assert tag_fix.category == TagCategory.TASK_TYPE

    # Case-insensitive and prefix-insensitive retrieval
    assert engine.get_tag("bugfix") == tag_fix
    assert engine.get_tag("#BugFix") == tag_fix
    assert engine.get_tag(tag_fix.tag_id) == tag_fix
    assert engine.get_tag("non-existent") is None

    # List catalog
    catalog = engine.list_registered_tags()
    assert len(catalog) == 1
    assert catalog[0] == tag_fix


def test_session_tagging_and_untagging() -> None:
    """Verifies attaching tags to a session, dynamic registration, and removal."""
    engine = SessionTagFilterEngine()

    tags = engine.tag_session(
        session_id="sess-001",
        tag_names=["#Frontend", "React", "BugFix"],
    )

    assert len(tags) == 3
    attached = engine.get_session_tags("sess-001")
    assert len(attached) == 3
    attached_names = {t.name for t in attached}
    assert attached_names == {"Frontend", "React", "BugFix"}

    # Untag single tag
    removed = engine.untag_session("sess-001", "React")
    assert removed
    assert len(engine.get_session_tags("sess-001")) == 2
    assert "React" not in {t.name for t in engine.get_session_tags("sess-001")}

    # Untag non-existent
    assert not engine.untag_session("sess-001", "Unknown")


def test_multi_dimensional_filtering_tags() -> None:
    """Verifies ANY, ALL, and EXACT tag boolean query filtering."""
    engine = SessionTagFilterEngine()
    tag_py = SessionTag(tag_id="t-1", name="Python", color=TagColor.BLUE)
    tag_db = SessionTag(tag_id="t-2", name="Database", color=TagColor.GREEN)
    tag_sec = SessionTag(tag_id="t-3", name="Security", color=TagColor.RED)

    # Session 1: [Python, Database]
    # Session 2: [Python]
    # Session 3: [Python, Database, Security]
    s1 = TaggedSessionItem(session_id="s-1", title="ORM setup", tags=(tag_py, tag_db))
    s2 = TaggedSessionItem(session_id="s-2", title="Python script", tags=(tag_py,))
    s3 = TaggedSessionItem(session_id="s-3", title="Auth database", tags=(tag_py, tag_db, tag_sec))
    sessions = [s1, s2, s3]

    # 1. ANY (Union): tags=["Database", "Security"] -> matches s1, s3
    q_any = SessionFilterQuery(tags=("Database", "Security"), match_mode=TagMatchMode.ANY)
    res_any = engine.filter_sessions(sessions, q_any)
    assert {s.session_id for s in res_any} == {"s-1", "s-3"}

    # 2. ALL (Intersection): tags=["Python", "Database"] -> matches s1, s3
    q_all = SessionFilterQuery(tags=("Python", "Database"), match_mode=TagMatchMode.ALL)
    res_all = engine.filter_sessions(sessions, q_all)
    assert {s.session_id for s in res_all} == {"s-1", "s-3"}

    # 3. EXACT (Set equality): tags=["Python", "Database"] -> matches ONLY s1
    q_exact = SessionFilterQuery(tags=("Python", "Database"), match_mode=TagMatchMode.EXACT)
    res_exact = engine.filter_sessions(sessions, q_exact)
    assert {s.session_id for s in res_exact} == {"s-1"}


def test_multi_dimensional_filtering_project_pin_keyword_dates() -> None:
    """Verifies combined project, pin status, title keyword, and timestamp bounds filtering."""
    engine = SessionTagFilterEngine()
    now = time.time()

    s1 = TaggedSessionItem(
        session_id="s-1",
        title="Payment stripe integration",
        project_id="proj-finance",
        is_pinned=True,
        created_at=now - 1000,
    )
    s2 = TaggedSessionItem(
        session_id="s-2",
        title="Payment paypal webhook",
        project_id="proj-finance",
        is_pinned=False,
        created_at=now - 500,
    )
    s3 = TaggedSessionItem(
        session_id="s-3",
        title="User profile settings",
        project_id="proj-user",
        is_pinned=True,
        created_at=now - 200,
    )
    sessions = [s1, s2, s3]

    # Filter by project_id and pinned
    q1 = SessionFilterQuery(project_id="proj-finance", is_pinned=True)
    res1 = engine.filter_sessions(sessions, q1)
    assert [s.session_id for s in res1] == ["s-1"]

    # Filter by keyword
    q2 = SessionFilterQuery(keyword="paypal")
    res2 = engine.filter_sessions(sessions, q2)
    assert [s.session_id for s in res2] == ["s-2"]

    # Filter by date range
    q3 = SessionFilterQuery(created_after=now - 600, created_before=now - 100)
    res3 = engine.filter_sessions(sessions, q3)
    assert {s.session_id for s in res3} == {"s-2", "s-3"}


def test_autonomous_semantic_tag_classifier() -> None:
    """Verifies rule-based semantic auto-tag recommendation on transcript summaries."""
    engine = SessionTagFilterEngine()

    transcript_bug_fix = (
        "User reported traceback exception: division by zero crash. "
        "We identified the panic bug in calculate_ratio and wrote a fix."
    )
    suggestions_bug = engine.auto_suggest_tags_from_text("sess-test-bug", transcript_bug_fix)
    tag_names_bug = [s.tag_name for s in suggestions_bug]
    assert "BugFix" in tag_names_bug
    assert suggestions_bug[0].confidence > 0.7

    transcript_refactor_test = (
        "Refactor giant handler to modular controllers, decouple dependencies, "
        "and run pytest suite with full coverage assertion."
    )
    suggestions_ref = engine.auto_suggest_tags_from_text("sess-test-ref", transcript_refactor_test)
    tag_names_ref = [s.tag_name for s in suggestions_ref]
    assert "Refactor" in tag_names_ref
    assert "Testing" in tag_names_ref
    assert len(suggestions_ref) <= 3


def test_tag_distribution_analytics() -> None:
    """Verifies computation of tag usage frequency and population metrics."""
    engine = SessionTagFilterEngine()
    t1 = SessionTag(tag_id="t-1", name="React")
    t2 = SessionTag(tag_id="t-2", name="API")

    s1 = TaggedSessionItem(session_id="s-1", title="UI", tags=(t1, t2))
    s2 = TaggedSessionItem(session_id="s-2", title="Client", tags=(t1,))
    s3 = TaggedSessionItem(session_id="s-3", title="No tags", tags=())

    dist = engine.get_tag_distribution([s1, s2, s3])
    assert dist.total_tagged_sessions == 2
    assert dist.tag_counts["react"] == 2
    assert dist.tag_counts["api"] == 1


def test_tag_dataclass_serialization() -> None:
    """Verifies that all tagging dataclasses serialize cleanly to dictionaries."""
    tag = SessionTag(tag_id="t-x", name="GraphQL", color=TagColor.PURPLE)
    t_dict = tag.to_dict()
    assert t_dict["name"] == "GraphQL"
    assert t_dict["color"] == "purple"

    item = TaggedSessionItem(session_id="s-x", title="Title", tags=(tag,))
    i_dict = item.to_dict()
    assert i_dict["session_id"] == "s-x"
    assert len(i_dict["tags"]) == 1
