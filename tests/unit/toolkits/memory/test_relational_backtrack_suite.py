# [POS]: tests/unit/toolkits/memory/test_relational_backtrack_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.relational_backtrack
# [OUTPUT]: Unit test suite for TemporalRelationalAnchorAndCrossSessionEntityBacktrackingSuite (Item 100)

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.relational_backtrack import (
    ActionSynonymNormalizer,
    CrossSessionBacktrackEngine,
    EntityTypeKind,
    RelationalBacktrackQuery,
    TemporalRelationTriplet,
    TemporalTripletStore,
)


def test_action_synonym_normalization_and_expansion() -> None:
    """Validate action synonym canonicalization, dialect expansion, and similarity scoring."""
    norm = ActionSynonymNormalizer()

    # 1. Canonicalize dialect cue
    assert norm.canonicalize_action("打边炉") == "eat_hotpot"
    assert norm.canonicalize_action("吃火锅") == "eat_hotpot"
    assert norm.canonicalize_action("去吃火锅啦") == "eat_hotpot"
    assert norm.canonicalize_action("签约") == "sign_contract"

    # 2. Expand synonyms
    expanded = norm.expand_synonyms("打边炉")
    assert "吃火锅" in expanded
    assert "打边炉" in expanded
    assert "hotpot" in expanded

    # 3. Action similarity
    score_identical = norm.compute_action_similarity("吃火锅", "吃火锅")
    assert score_identical == 1.0

    score_syn = norm.compute_action_similarity("打边炉", "吃火锅")
    assert score_syn >= 0.9

    score_unrelated = norm.compute_action_similarity("打边炉", "代码审查")
    assert score_unrelated == 0.0

    # 4. Dynamic synonym registration
    norm.register_synonyms("play_badminton", ["打羽毛球", "打球", "badminton"])
    assert norm.canonicalize_action("打羽毛球") == "play_badminton"
    assert "打球" in norm.expand_synonyms("play_badminton")


def test_temporal_triplet_store_indexing_and_lookup() -> None:
    """Validate in-memory inverted indexing and multi-criteria lookup."""
    store = TemporalTripletStore()

    t1 = TemporalRelationTriplet(
        triplet_id="trip-1",
        subject="user",
        predicate_action="deploy_service",
        action_synonyms=["发布", "上线", "部署"],
        target_entity="AuthGateway",
        target_entity_type=EntityTypeKind.PROJECT,
        temporal_anchor="2026-10-01",
        session_id="sess-01",
        message_id="msg-101",
        verbatim_quote="昨晚部署了 AuthGateway 生产环境。",
    )

    t2 = TemporalRelationTriplet(
        triplet_id="trip-2",
        subject="user",
        predicate_action="sign_contract",
        action_synonyms=["签约", "签合同"],
        target_entity="AcmeCorp",
        target_entity_type=EntityTypeKind.CLIENT,
        temporal_anchor="2026-10-05",
        session_id="sess-02",
        message_id="msg-202",
        verbatim_quote="周五和 AcmeCorp 签署了框架协议。",
    )

    store.record_triplet(t1)
    store.record_triplet(t2)

    # Search by action cue "上线"
    candidates_deploy = store.find_candidates(
        candidate_actions=["上线", "发布", "deploy_service"]
    )
    assert len(candidates_deploy) == 1
    assert candidates_deploy[0].target_entity == "AuthGateway"

    # Search by action cue "签约" with entity_type constraint
    candidates_sign = store.find_candidates(
        candidate_actions=["签约"], entity_type=EntityTypeKind.CLIENT
    )
    assert len(candidates_sign) == 1
    assert candidates_sign[0].target_entity == "AcmeCorp"

    # Search with mismatching entity_type
    candidates_mismatch = store.find_candidates(
        candidate_actions=["签约"], entity_type=EntityTypeKind.PROJECT
    )
    assert len(candidates_mismatch) == 0


def test_cross_session_backtrack_engine_hotpot_client_query() -> None:
    """Solve the classic benchmark case: 'eat hotpot' vs 'da-bin-lo' client resolution."""
    engine = CrossSessionBacktrackEngine()

    # Session 1 (past session): user discusses eating hotpot with Client Li
    triplet_hotpot = TemporalRelationTriplet(
        triplet_id="trip-hotpot-01",
        subject="user",
        predicate_action="eat_hotpot",
        action_synonyms=["吃火锅", "打边炉", "涮火锅"],
        target_entity="李总",
        target_entity_type=EntityTypeKind.CLIENT,
        temporal_anchor="2026-10-02",
        session_id="sess-past-001",
        message_id="msg-past-101",
        verbatim_quote="下周四带客户李总去吃火锅，预订了川味观。",
        confidence=1.0,
    )

    # Session 2 (past session): user syncs with technical consultant Wang
    triplet_meeting = TemporalRelationTriplet(
        triplet_id="trip-meet-02",
        subject="user",
        predicate_action="online_meeting",
        action_synonyms=["开会", "语音沟通"],
        target_entity="王工",
        target_entity_type=EntityTypeKind.PERSON,
        temporal_anchor="2026-10-05",
        session_id="sess-past-002",
        message_id="msg-past-202",
        verbatim_quote="下午和技术顾问王工开了线上技术评审会。",
        confidence=1.0,
    )

    engine.store.record_triplet(triplet_hotpot)
    engine.store.record_triplet(triplet_meeting)

    # Current query: "上次说去打边炉，是和哪个客户来着？"
    query = RelationalBacktrackQuery(
        action_cue="打边炉",
        target_entity_type=EntityTypeKind.CLIENT,
        min_confidence=0.5,
    )

    result = engine.backtrack(query)

    assert result.total_found == 1
    assert len(result.hits) == 1

    top_hit = result.hits[0]
    assert top_hit.triplet.target_entity == "李总"
    assert top_hit.triplet.target_entity_type == EntityTypeKind.CLIENT
    assert top_hit.triplet.temporal_anchor == "2026-10-02"
    assert "川味观" in top_hit.triplet.verbatim_quote
    assert top_hit.match_score >= 0.9

    # Verify synthesized answer incorporates entity and verbatim evidence
    assert result.inferred_answer is not None
    assert "李总" in result.inferred_answer
    assert "2026-10-02" in result.inferred_answer
    assert "下周四带客户李总去吃火锅" in result.inferred_answer
