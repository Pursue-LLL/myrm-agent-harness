"""[POS]: tests/unit/toolkits/memory/test_tombstone_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for antithetical contradiction detection, tombstone masking, and eviction.
"""

from pathlib import Path

from myrm_agent_harness.toolkits.memory.tombstone import (
    MemoryTombstoneCurationService,
    MemoryTombstoneMetaTools,
    PreferenceContradictionDetector,
    TombstoneCandidateItem,
    TombstoneState,
)


def test_contradiction_detector_antithetical_domains() -> None:
    """Verify detector identifies domain-level antithetical preferences with temporal precedence."""
    detector = PreferenceContradictionDetector()

    memories = [
        TombstoneCandidateItem(
            memory_id="mem_comment_old",
            content="极简代码风格，不要写任何注释",
            created_at=100.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_comment_new",
            content="为所有核心函数添加详尽注释与docstring",
            created_at=200.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_lang_old",
            content="用户偏好使用unittest测试框架",
            created_at=150.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_lang_new",
            content="全仓一律使用pytest编写异步测试用例",
            created_at=250.0,
        ),
    ]

    contradictions = detector.detect_contradictions(memories)
    assert len(contradictions) == 2

    c_comment = next(c for c in contradictions if c.topic_keyword == "code_comments")
    assert c_comment.new_memory_id == "mem_comment_new"
    assert c_comment.outdated_memory_id == "mem_comment_old"
    assert c_comment.confidence_score >= 0.9

    c_test = next(c for c in contradictions if c.topic_keyword == "test_framework")
    assert c_test.new_memory_id == "mem_lang_new"
    assert c_test.outdated_memory_id == "mem_lang_old"


def test_contradiction_detector_polarity_inversion() -> None:
    """Verify detector catches explicit prefer vs prohibit polarity reversals."""
    detector = PreferenceContradictionDetector()

    memories = [
        TombstoneCandidateItem(
            memory_id="mem_redis_old",
            content="严禁使用 Redis 缓存，所有状态入 Postgres",
            created_at=500.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_redis_new",
            content="必须使用 Redis 作为高速会话存储",
            created_at=600.0,
        ),
    ]

    contradictions = detector.detect_contradictions(memories)
    assert len(contradictions) == 1
    assert contradictions[0].new_memory_id == "mem_redis_new"
    assert contradictions[0].outdated_memory_id == "mem_redis_old"
    assert contradictions[0].topic_keyword == "redis"


def test_tombstone_curation_masking_and_revival(tmp_path: Path) -> None:
    """Verify automated tombstone isolation blocks recall and user revival restores access."""
    db_file = tmp_path / "test_tombstone.db"
    service = MemoryTombstoneCurationService(db_path=db_file)

    items = [
        TombstoneCandidateItem(
            memory_id="mem_zh",
            content="所有任务回复使用中文",
            created_at=1000.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_en",
            content="This project requires reply in English only",
            created_at=2000.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_unrelated",
            content="Keep git commits clean and modular",
            created_at=1500.0,
        ),
    ]

    # Run curation
    report = service.curate_and_tombstone(items, auto_tombstone=True)
    assert report.total_scanned == 3
    assert report.total_contradictions_found == 1
    assert report.total_tombstoned == 1

    # Check record: older item (mem_zh) should be TOMBSTONED
    rec_zh = service.get_tombstone_record("mem_zh")
    assert rec_zh is not None
    assert rec_zh.state == TombstoneState.TOMBSTONED
    assert rec_zh.superseded_by_id == "mem_en"

    # Test Recall Barrier: tombstoned item must be excluded from active recall
    active = service.filter_active_memories(items)
    active_ids = {m.memory_id for m in active}
    assert "mem_zh" not in active_ids
    assert "mem_en" in active_ids
    assert "mem_unrelated" in active_ids

    # User revives the tombstoned memory
    revive_ok = service.revive_tombstone("mem_zh")
    assert revive_ok is True
    rec_zh_after = service.get_tombstone_record("mem_zh")
    assert rec_zh_after is not None
    assert rec_zh_after.state == TombstoneState.REVIVED

    # Verify memory is now active again
    active_again = service.filter_active_memories(items)
    active_again_ids = {m.memory_id for m in active_again}
    assert "mem_zh" in active_again_ids

    service.close()


def test_tombstone_eviction_lifecycle(tmp_path: Path) -> None:
    """Verify tombstoned memories can be physically evicted after retention."""
    db_file = tmp_path / "test_evict.db"
    service = MemoryTombstoneCurationService(db_path=db_file)

    items = [
        TombstoneCandidateItem(
            memory_id="mem_old_vue",
            content="项目优先使用 vue 构建组件",
            created_at=10.0,
        ),
        TombstoneCandidateItem(
            memory_id="mem_new_react",
            content="全面重构，优先使用 react 现代生态",
            created_at=20.0,
        ),
    ]

    service.curate_and_tombstone(items, auto_tombstone=True)
    rec = service.get_tombstone_record("mem_old_vue")
    assert rec is not None
    assert rec.state == TombstoneState.TOMBSTONED

    # Evict
    evicted_count = service.evict_tombstones(["mem_old_vue"])
    assert evicted_count == 1
    rec_evicted = service.get_tombstone_record("mem_old_vue")
    assert rec_evicted is not None
    assert rec_evicted.state == TombstoneState.EVICTED
    assert rec_evicted.evicted_at is not None

    service.close()


def test_meta_tools_integration(tmp_path: Path) -> None:
    """Verify Agent meta-tools expose curation, filtering, revival, and eviction."""
    db_file = tmp_path / "test_meta.db"
    service = MemoryTombstoneCurationService(db_path=db_file)
    tools = MemoryTombstoneMetaTools(service=service)

    raw_memories = [
        {"memory_id": "m1", "content": "暗色主题优先", "created_at": 100.0},
        {"memory_id": "m2", "content": "切换为浅色模式以防反光", "created_at": 200.0},
    ]

    curate_res = tools.scan_contradictions_and_curate(raw_memories, auto_tombstone=True)
    assert curate_res["total_contradictions_found"] == 1
    assert curate_res["total_tombstoned"] == 1

    # Filter active
    filtered = tools.filter_active_memories(raw_memories)
    assert len(filtered) == 1
    assert filtered[0]["memory_id"] == "m2"

    # Revive m1
    revive_res = tools.revive_tombstone_memory("m1")
    assert revive_res["success"] is True

    # List records
    records = tools.list_tombstone_records()
    assert len(records) >= 1
    rec_m1 = next(r for r in records if r["memory_id"] == "m1")
    assert rec_m1["state"] == "revived"

    service.close()
