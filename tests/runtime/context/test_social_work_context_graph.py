"""Tests for Social Collaboration Graph and Cross-Application Work Context Engine."""

from myrm_agent_harness.runtime.context.social_work_context_graph import (
    CrossAppChronologicalResolver,
    CrossAppWorkAsset,
    FuzzyQueryIntent,
    PersonEntity,
    PersonRoleKind,
    PrivacyAuditSentinel,
    SocialCollaborationGraph,
    WorkAssetKind,
)


def test_social_collaboration_graph_mention_resolution():
    graph = SocialCollaborationGraph()

    p_wang = PersonEntity(
        person_id="p-wang",
        name="王伟",
        aliases=("王总", "David Wang"),
        title="Engineering VP",
        role_kind=PersonRoleKind.LEADER,
        department="Platform Engineering",
    )
    p_zhang = PersonEntity(
        person_id="p-zhang",
        name="张建国",
        aliases=("老张", "张工"),
        title="Staff Architect",
        role_kind=PersonRoleKind.DECISION_MAKER,
        department="Kernel Team",
    )
    p_li = PersonEntity(
        person_id="p-li",
        name="李小明",
        aliases=("小李",),
        title="Software Engineer",
        role_kind=PersonRoleKind.CONTRIBUTOR,
        department="Kernel Team",
    )

    graph.register_person(p_wang)
    graph.register_person(p_zhang)
    graph.register_person(p_li)

    # 1. Resolve exact name
    assert graph.resolve_person_mention("王伟") == p_wang

    # 2. Resolve colloquial aliases
    assert graph.resolve_person_mention("王总") == p_wang
    assert graph.resolve_person_mention("老张") == p_zhang
    assert graph.resolve_person_mention("张工") == p_zhang
    assert graph.resolve_person_mention("未知用户") is None

    # 3. Decision maker checks
    assert graph.is_decision_maker("p-wang")
    assert graph.is_decision_maker("p-zhang")
    assert not graph.is_decision_maker("p-li")


def test_cross_app_chronological_fuzzy_resolution():
    graph = SocialCollaborationGraph()
    p_zhang = PersonEntity(
        person_id="p-zhang",
        name="张建国",
        aliases=("老张",),
        title="Staff Architect",
        role_kind=PersonRoleKind.DECISION_MAKER,
        department="Architecture",
    )
    p_other = PersonEntity(
        person_id="p-other",
        name="其他员工",
        aliases=(),
        title="Dev",
        role_kind=PersonRoleKind.CONTRIBUTOR,
        department="Marketing",
    )
    graph.register_person(p_zhang)
    graph.register_person(p_other)

    now = 1_700_000_000.0
    resolver = CrossAppChronologicalResolver()

    # Asset 1: Created by Zhang 2 days ago (Target)
    resolver.register_asset(
        CrossAppWorkAsset(
            asset_id="asset-budget-2026",
            title="Q3 研发预算明细表.xlsx",
            path_or_uri="/shared/docs/Q3_Budget.xlsx",
            kind=WorkAssetKind.DOCUMENT,
            created_by_person_id="p-zhang",
            timestamp_epoch_s=now - (2 * 86400.0),
            semantic_summary="Kernel team headcount, cloud compute, and hardware budget",
        )
    )

    # Asset 2: Created by other person (Different author)
    resolver.register_asset(
        CrossAppWorkAsset(
            asset_id="asset-mkt-budget",
            title="市场投放预算表.xlsx",
            path_or_uri="/shared/docs/Marketing_Budget.xlsx",
            kind=WorkAssetKind.DOCUMENT,
            created_by_person_id="p-other",
            timestamp_epoch_s=now - (1 * 86400.0),
            semantic_summary="Marketing campaigns and ad spend",
        )
    )

    # Asset 3: Created by Zhang 60 days ago (Stale)
    resolver.register_asset(
        CrossAppWorkAsset(
            asset_id="asset-old-spec",
            title="架构重构技术预算.docx",
            path_or_uri="/shared/docs/old_spec.docx",
            kind=WorkAssetKind.DOCUMENT,
            created_by_person_id="p-zhang",
            timestamp_epoch_s=now - (60 * 86400.0),
            semantic_summary="Old migration budget spec",
        )
    )

    # Query: "老张上周发我的预算表"
    intent = FuzzyQueryIntent(
        mention_person="老张",
        time_hint="recent",
        keyword_hints=("预算", "表"),
    )

    result = resolver.resolve_fuzzy_query(intent, graph, current_time_epoch_s=now)

    assert result.matched_person == p_zhang
    assert len(result.matched_assets) == 1
    assert result.matched_assets[0].asset_id == "asset-budget-2026"
    assert result.confidence_score > 0.5
    assert "张建国" in result.explanation


def test_privacy_audit_sentinel():
    sentinel = PrivacyAuditSentinel(allowed_prefixes=("/workspace/safe/", "/projects/active/"))

    # Authorized query
    r1 = sentinel.check_and_audit(
        action="read_file",
        target_path="/workspace/safe/config.json",
        timestamp_utc="2026-10-06T12:00:00Z",
    )
    assert r1.is_authorized
    assert r1.access_id == "audit_1"

    # Unauthorized access outside boundary
    r2 = sentinel.check_and_audit(
        action="read_file",
        target_path="/etc/passwd",
        timestamp_utc="2026-10-06T12:01:00Z",
    )
    assert not r2.is_authorized
    assert r2.access_id == "audit_2"

    records = sentinel.get_audit_records()
    assert len(records) == 2
