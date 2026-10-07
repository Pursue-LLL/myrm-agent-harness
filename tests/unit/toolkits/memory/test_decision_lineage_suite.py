"""[POS]: tests/unit/toolkits/memory/test_decision_lineage_suite.py
[INPUT]: EngineeringDecisionStore, DecisionLineageEngine, IngestionNoiseFilter, and toolkits.
[OUTPUT]: Pytest unit test coverage verifying lineage state transitions, cycle prevention, MMR, and HITL gate.
"""

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.decisions import (
    CandidateStatus,
    DecisionLineageEngine,
    DecisionRecord,
    DecisionStatus,
    EngineeringDecisionStore,
    IngestionNoiseFilter,
    LineageCycleError,
    PendingDecisionCandidate,
    RecordArchitectureDecisionTool,
    StructuredPriorityReranker,
)


def test_noise_filter_system_prompts() -> None:
    """Verify IngestionNoiseFilter properly rejects system prompts and short fragments."""
    assert IngestionNoiseFilter.is_noise("<system-reminder> Update your files") is True
    assert IngestionNoiseFilter.is_noise("<context-boundary> Previous session ended") is True
    assert IngestionNoiseFilter.is_noise("Updated instructions from AGENTS.md") is True
    assert IngestionNoiseFilter.is_noise("ok") is True

    valid_text = "选用 Session 认证架构，废弃 JWT 无状态方案"
    assert IngestionNoiseFilter.is_noise(valid_text) is False
    assert IngestionNoiseFilter.contains_decision_cue(valid_text) is True


def test_lineage_cycle_detection() -> None:
    """Verify cycle detection prevents cyclic dependency loops in lineage DAG."""
    # A supersedes B, B supersedes C -> valid
    db_mock: dict[str, DecisionRecord] = {
        "dec_c": DecisionRecord(
            id="dec_c",
            title="Init DB",
            text="Use SQLite",
            status=DecisionStatus.SUPERSEDED,
            created_at="2026-09-01T00:00:00Z",
            updated_at="2026-09-01T00:00:00Z",
        ),
        "dec_b": DecisionRecord(
            id="dec_b",
            title="Upgrade DB",
            text="Use Postgres",
            status=DecisionStatus.SUPERSEDED,
            supersedes_id="dec_c",
            created_at="2026-09-02T00:00:00Z",
            updated_at="2026-09-02T00:00:00Z",
        ),
    }

    # New dec_a supersedes dec_b -> valid
    DecisionLineageEngine.validate_transition(
        "dec_a", "dec_b", lambda rid: db_mock.get(rid)
    )

    # Self-supersession -> raises LineageCycleError
    with pytest.raises(LineageCycleError):
        DecisionLineageEngine.validate_transition(
            "dec_b", "dec_b", lambda rid: db_mock.get(rid)
        )

    # Cyclic loop: dec_c trying to supersede dec_b -> raises LineageCycleError
    with pytest.raises(LineageCycleError):
        DecisionLineageEngine.validate_transition(
            "dec_c", "dec_b", lambda rid: db_mock.get(rid)
        )


def test_ancestry_tracing_and_active_successor() -> None:
    """Verify trace_ancestry returns chronological history and successor finding."""
    r1 = DecisionRecord(
        id="d1",
        title="V1",
        text="Auth V1",
        status=DecisionStatus.SUPERSEDED,
        superseded_by="d2",
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    r2 = DecisionRecord(
        id="d2",
        title="V2",
        text="Auth V2",
        status=DecisionStatus.SUPERSEDED,
        supersedes_id="d1",
        superseded_by="d3",
        created_at="2026-09-02T00:00:00Z",
        updated_at="2026-09-02T00:00:00Z",
    )
    r3 = DecisionRecord(
        id="d3",
        title="V3",
        text="Auth V3",
        status=DecisionStatus.ACTIVE,
        supersedes_id="d2",
        created_at="2026-09-03T00:00:00Z",
        updated_at="2026-09-03T00:00:00Z",
    )
    store_map = {"d1": r1, "d2": r2, "d3": r3}

    chain = DecisionLineageEngine.trace_ancestry("d3", lambda rid: store_map.get(rid))
    assert [c.id for c in chain] == ["d1", "d2", "d3"]

    succ = DecisionLineageEngine.find_active_successor(
        "d1", lambda rid: store_map.get(rid)
    )
    assert succ is not None
    assert succ.id == "d3"


def test_structured_priority_reranker() -> None:
    """Verify Jaccard dedup, MMR diversity, and structured priority prompt generation."""
    r_auth = DecisionRecord(
        id="d_auth",
        title="认证架构选型",
        text="采用 Session 认证方案，不使用 JWT",
        rationale="单机沙箱无需无状态 Token",
        status=DecisionStatus.ACTIVE,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    r_dup = DecisionRecord(
        id="d_auth_dup",
        title="认证架构选型",
        text="采用 Session 认证方案，不使用 JWT",
        rationale="冗余副本",
        status=DecisionStatus.ACTIVE,
        created_at="2026-09-04T01:00:00Z",
        updated_at="2026-09-04T01:00:00Z",
    )
    r_db = DecisionRecord(
        id="d_db",
        title="持久化存储",
        text="采用嵌入式 SQLite WAL，不使用外部 Docker 数据库",
        status=DecisionStatus.ACTIVE,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )

    hits = StructuredPriorityReranker.score_and_rank(
        query="请问我们系统的认证架构选型是什么？",
        records=[r_auth, r_dup, r_db],
        limit=5,
    )

    assert len(hits) == 1
    assert hits[0].decision_id in ("d_auth", "d_auth_dup")
    assert hits[0].is_priority is True

    prompt_block = StructuredPriorityReranker.format_prompt_block(hits)
    assert "生效架构决策与代际链" in prompt_block
    assert "元认知边界声明" in prompt_block
    assert "采用 Session 认证方案" in prompt_block


@pytest.mark.asyncio
async def test_engineering_decision_store_lifecycle(tmp_path: Path) -> None:
    """Verify decision staging, human confirmation gate approval, and persistence."""
    db_file = tmp_path / "decisions_test.db"
    store = EngineeringDecisionStore(db_path=db_file, auto_approve=False)

    # 1. Stage candidate awaiting confirmation
    staged = await store.stage_candidate(
        session_id="sess_101",
        title="认证方案",
        text="选定 Session 认证替代 JWT",
        rationale="本地沙箱内聚安全",
    )
    assert isinstance(staged, PendingDecisionCandidate)
    assert staged.status == CandidateStatus.PENDING

    # 2. Approve candidate
    decision = await store.approve_candidate(staged.id)
    assert isinstance(decision, DecisionRecord)
    assert decision.status == DecisionStatus.ACTIVE
    assert decision.title == "认证方案"

    # Verify candidate marked APPROVED in db
    cand_in_db = await store.db.get_candidate(staged.id)
    assert cand_in_db is not None
    assert cand_in_db.status == CandidateStatus.APPROVED

    # 3. New decision superseding prior decision
    staged2 = await store.stage_candidate(
        session_id="sess_102",
        title="认证方案更新",
        text="全面升级为 mTLS 混合 Session",
        rationale="支持多设备互联",
        supersedes_id=decision.id,
    )
    assert isinstance(staged2, PendingDecisionCandidate)
    decision2 = await store.approve_candidate(staged2.id)

    # Verify old decision updated to SUPERSEDED
    old_in_db = await store.db.get_decision(decision.id)
    assert old_in_db is not None
    assert old_in_db.status == DecisionStatus.SUPERSEDED
    assert old_in_db.superseded_by == decision2.id

    # Verify lineage ancestry
    chain = await store.get_lineage(decision2.id)
    assert len(chain) == 2
    assert chain[0].id == decision.id
    assert chain[1].id == decision2.id

    # 4. Search priority recall
    hits = await store.search_priority(query="认证方案更新 mTLS", limit=5)
    assert len(hits) >= 1
    assert hits[0].decision_id == decision2.id


@pytest.mark.asyncio
async def test_record_architecture_decision_tool(tmp_path: Path) -> None:
    """Verify tool executes and respects confirmation gate."""
    db_file = tmp_path / "tool_test.db"
    store = EngineeringDecisionStore(db_path=db_file, auto_approve=False)
    tool = RecordArchitectureDecisionTool(store=store)

    res = await tool.execute(
        title="微服务 vs 单体",
        text="坚持模块化单体架构，坚决不拆分微服务",
        rationale="降低运维复杂度与网络开销",
        session_id="session_tool_test",
    )
    assert res["status"] == "pending_confirmation"
    assert "candidate_id" in res

    # Switch store to auto-approve
    store.auto_approve = True
    res_auto = await tool.execute(
        title="轻量嵌入向量库",
        text="选型 sqlite-vec 作为默认向量引擎",
        rationale="零守护进程与本地优先",
        session_id="session_tool_test",
    )
    assert res_auto["status"] == "active"
    assert "decision_id" in res_auto
