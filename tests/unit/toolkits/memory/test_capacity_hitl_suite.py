"""[POS]: tests/unit/toolkits/memory/test_capacity_hitl_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for near-capacity detection, read-only proposals, and HITL resolution.
"""

from pathlib import Path

from myrm_agent_harness.toolkits.memory.capacity_hitl import (
    CandidateActionKind,
    CapacityAlertKind,
    CapacityHitlMetaTools,
    CapacityHitlService,
    CapacityThresholdDetector,
    HitlCandidateStatus,
    MergeArchiveCandidateProposer,
)


def test_capacity_threshold_detector() -> None:
    """Verify capacity threshold detector triggers correct ladder alert tiers."""
    detector = CapacityThresholdDetector(
        default_max_entries=1000,
        near_capacity_ratio=0.80,
        critical_capacity_ratio=0.95,
    )

    # 1. Normal state (500 / 1000 = 50%)
    rep_norm = detector.evaluate(total_entries=500)
    assert rep_norm.alert_level == CapacityAlertKind.NORMAL
    assert rep_norm.capacity_ratio == 0.50

    # 2. Near capacity state (850 / 1000 = 85%)
    rep_near = detector.evaluate(total_entries=850)
    assert rep_near.alert_level == CapacityAlertKind.NEAR_CAPACITY
    assert rep_near.capacity_ratio == 0.85

    # 3. Critical full state (960 / 1000 = 96%)
    rep_crit = detector.evaluate(total_entries=960)
    assert rep_crit.alert_level == CapacityAlertKind.CRITICAL_FULL
    assert rep_crit.capacity_ratio == 0.96


def test_proposer_read_only_candidates() -> None:
    """Verify proposer identifies merge overlaps and archive candidates without modifying originals."""
    proposer = MergeArchiveCandidateProposer(similarity_threshold=0.40)

    entries = [
        {
            "id": "e1",
            "content": "用户喜欢喝美式黑咖啡，早晨必须来一杯唤醒精力",
            "tags": ["coffee", "habit"],
            "created_at": 1000.0,
            "access_count": 12,
        },
        {
            "id": "e2",
            "content": "用户早晨习惯喝美式黑咖啡，不加糖和奶，非常喜欢",
            "tags": ["beverage"],
            "created_at": 1005.0,
            "access_count": 8,
        },
        {
            "id": "e3",
            "content": "2024年临时记录的某次打印机IP地址 192.168.1.200",
            "tags": ["hardware", "temporary"],
            "created_at": 800.0,
            "access_count": 0,
        },
    ]

    proposals = proposer.propose_candidates(entries=entries, max_proposals=5)
    assert len(proposals) >= 2

    # Check merge proposal
    merge_props = [p for p in proposals if p.action_kind == CandidateActionKind.MERGE]
    assert len(merge_props) == 1
    merge_p = merge_props[0]
    assert len(merge_p.source_entries) == 2
    assert "美式黑咖啡" in merge_p.proposed_content
    assert merge_p.status == HitlCandidateStatus.PENDING
    assert merge_p.source_entries[0].content_hash != ""

    # Check archive proposal
    archive_props = [p for p in proposals if p.action_kind == CandidateActionKind.ARCHIVE]
    assert len(archive_props) == 1
    arch_p = archive_props[0]
    assert arch_p.source_entries[0].id == "e3"
    assert arch_p.status == HitlCandidateStatus.PENDING


def test_hitl_service_lifecycle_and_soft_archive(tmp_path: Path) -> None:
    """Verify HITL proposal resolution and cold storage preservation."""
    db_file = tmp_path / "hitl.db"
    service = CapacityHitlService(db_path=db_file)

    entries = [
        {
            "id": "item-arch-1",
            "content": "过期的旧项目临时环境密码密钥",
            "tags": ["secret"],
            "created_at": 500.0,
            "access_count": 0,
        }
    ]

    proposals = service.generate_and_store_proposals(entries=entries)
    assert len(proposals) == 1
    cand_id = proposals[0].candidate_id

    pending_list = service.list_proposals(status=HitlCandidateStatus.PENDING)
    assert len(pending_list) == 1
    assert pending_list[0].candidate_id == cand_id

    # Approve the archive proposal
    success, msg, resolved = service.resolve_candidate(
        candidate_id=cand_id,
        decision=HitlCandidateStatus.APPROVED,
        reviewer_note="确认归档冷存储",
    )
    assert success is True
    assert "成功应用" in msg
    assert resolved is not None
    assert resolved.status == HitlCandidateStatus.APPROVED

    # Verify soft archive preserved item
    archived = service.list_archived_entries()
    assert len(archived) == 1
    assert archived[0]["id"] == "item-arch-1"
    assert archived[0]["origin_candidate_id"] == cand_id

    service.close()


def test_cas_concurrency_violation_defense(tmp_path: Path) -> None:
    """Verify CAS protects against concurrent modification while proposals are in review."""
    db_file = tmp_path / "cas.db"
    service = CapacityHitlService(db_path=db_file)

    entries = [
        {
            "id": "doc-1",
            "content": "原版重要配置：port 8080",
            "tags": ["config"],
            "created_at": 100.0,
            "access_count": 0,
        }
    ]

    proposals = service.generate_and_store_proposals(entries=entries)
    cand_id = proposals[0].candidate_id

    # Simulate concurrent external update to doc-1: content modified, hash mismatch
    current_hashes = {"doc-1": "tampered_hash_9999"}

    success, msg, _ = service.resolve_candidate(
        candidate_id=cand_id,
        decision=HitlCandidateStatus.APPROVED,
        reviewer_note="尝试确认",
        current_entry_hashes=current_hashes,
    )
    assert success is False
    assert "EXPIRED" in msg

    # Proposal state in DB must now be EXPIRED
    proposals_after = service.list_proposals()
    target = next(p for p in proposals_after if p.candidate_id == cand_id)
    assert target.status == HitlCandidateStatus.EXPIRED

    service.close()


def test_meta_tools_integration() -> None:
    """Verify Agent CapacityHitlMetaTools operation."""
    service = CapacityHitlService(db_path=":memory:")
    tools = CapacityHitlMetaTools(service=service)

    # 1. Check capacity
    rep = tools.check_memory_capacity(total_entries=820, max_entries=1000)
    assert rep.alert_level == CapacityAlertKind.NEAR_CAPACITY

    # 2. Propose candidates
    props = tools.propose_capacity_candidates(
        entries=[
            {
                "id": "t1",
                "content": "测试知识点条目 A",
                "tags": ["test"],
                "created_at": 100.0,
                "access_count": 0,
            }
        ]
    )
    assert len(props) == 1

    # 3. List pending
    pending = tools.list_pending_capacity_candidates()
    assert len(pending) == 1
    assert pending[0].candidate_id == props[0].candidate_id

    service.close()
