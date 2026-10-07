"""[POS]: tests/unit/toolkits/memory/test_cognitive_box_suite.py
[INPUT]: Cognitive box domain models, filters, storage, and service.
[OUTPUT]: Comprehensive unit tests validating strict intake filtering, four-layer isolation, and prompt generation.
"""

from myrm_agent_harness.toolkits.memory.cognitive_box import (
    CognitiveBoxMetaTools,
    CognitiveLayerKind,
    CognitiveMemoryBoxService,
    CognitiveMemoryEntry,
    FourLayerCognitiveMemoryBox,
    IntakeDecisionKind,
    StrictMemoryIntakeFilter,
)


def test_strict_intake_filter_noise_and_transient() -> None:
    # 1. Chit-chat and salutations
    rep1 = StrictMemoryIntakeFilter.evaluate("hello!")
    assert rep1.decision == IntakeDecisionKind.DROP_NOISE

    rep2 = StrictMemoryIntakeFilter.evaluate("好的，收到")
    assert rep2.decision == IntakeDecisionKind.DROP_NOISE

    # 2. Transient procedural query
    rep3 = StrictMemoryIntakeFilter.evaluate("为什么报错了?")
    assert rep3.decision == IntakeDecisionKind.DROP_TRANSIENT

    rep4 = StrictMemoryIntakeFilter.evaluate("can you check this file?")
    assert rep4.decision == IntakeDecisionKind.DROP_TRANSIENT


def test_strict_intake_filter_layer_classification() -> None:
    # User Profile
    rep_pref = StrictMemoryIntakeFilter.evaluate("我习惯使用 TypeScript 并且偏好函数式编程风格")
    assert rep_pref.decision == IntakeDecisionKind.ADMIT
    assert rep_pref.layer == CognitiveLayerKind.USER_PROFILE

    # Lessons & Rules
    rep_rule = StrictMemoryIntakeFilter.evaluate("架构规则：SQLite 内存库必须在实例中持久保持连接引用，严禁每次重连")
    assert rep_rule.decision == IntakeDecisionKind.ADMIT
    assert rep_rule.layer == CognitiveLayerKind.LESSONS_RULES


def test_cognitive_memory_box_storage_and_partitioning() -> None:
    box = FourLayerCognitiveMemoryBox(db_path=":memory:")
    try:
        e1 = CognitiveMemoryEntry(
            id="e1",
            layer=CognitiveLayerKind.USER_PROFILE,
            content="Prefer 2 spaces indentation",
            confidence=0.9,
            tags=["formatting"],
        )
        e2 = CognitiveMemoryEntry(
            id="e2",
            layer=CognitiveLayerKind.LESSONS_RULES,
            content="Always verify Ruff zero errors before committing",
            confidence=0.95,
            tags=["lint", "safety"],
        )
        box.write_entry(e1)
        box.write_entry(e2)

        # List all
        all_entries = box.list_entries()
        assert len(all_entries) == 2

        # List by layer
        profile_entries = box.list_entries(layer=CognitiveLayerKind.USER_PROFILE)
        assert len(profile_entries) == 1
        assert profile_entries[0].id == "e1"

        # Snapshot check
        snap = box.get_snapshot()
        assert snap.total_count == 2
        assert snap.counts_by_layer[CognitiveLayerKind.USER_PROFILE.value] == 1
        assert snap.counts_by_layer[CognitiveLayerKind.LESSONS_RULES.value] == 1

        # Clear layer
        cleared = box.clear_layer(CognitiveLayerKind.USER_PROFILE)
        assert cleared == 1
        assert len(box.list_entries(layer=CognitiveLayerKind.USER_PROFILE)) == 0
        assert len(box.list_entries(layer=CognitiveLayerKind.LESSONS_RULES)) == 1
    finally:
        box.close()


def test_service_evaluate_and_update_existing() -> None:
    service = CognitiveMemoryBoxService(db_path=":memory:")
    try:
        # First admission
        report1, entry1 = service.evaluate_and_ingest(
            raw_content="踩坑教训：严禁使用 Any 类型，必须使用具体 Type Hints",
            source_session="sess_001",
            tags=["typing"],
        )
        assert report1.decision == IntakeDecisionKind.ADMIT
        assert entry1 is not None
        assert entry1.layer == CognitiveLayerKind.LESSONS_RULES

        # Duplicate admission should trigger UPDATE_EXISTING
        report2, entry2 = service.evaluate_and_ingest(
            raw_content="踩坑教训：严禁使用 Any 类型，必须使用具体 Type Hints",
            source_session="sess_002",
            tags=["pep8"],
        )
        assert report2.decision == IntakeDecisionKind.UPDATE_EXISTING
        assert entry2 is not None
        assert entry2.id == entry1.id
        assert "pep8" in entry2.tags
        assert "typing" in entry2.tags

        # Noise rejected
        report3, entry3 = service.evaluate_and_ingest("哈哈")
        assert report3.decision == IntakeDecisionKind.DROP_NOISE
        assert entry3 is None
    finally:
        service.close()


def test_prompt_context_rendering_and_meta_tools() -> None:
    service = CognitiveMemoryBoxService(db_path=":memory:")
    try:
        service.evaluate_and_ingest("偏好配置：代码编辑器主题偏好深色模式，字体使用 Fira Code")
        service.evaluate_and_ingest("架构铁律：单文件代码行数严格控制在 400 行以内")

        rendered = service.render_prompt_context()
        assert "Cognitive Layer 2: User Profile & Preferences" in rendered
        assert "Cognitive Layer 4: Distilled Lessons & Rules" in rendered
        assert "Fira Code" in rendered
        assert "400 行" in rendered

        tools = CognitiveBoxMetaTools(service=service)
        queried = tools.query_cognitive_box(layer="lessons_rules")
        assert len(queried) == 1
        assert "400 行" in str(queried[0]["content"])

        res = tools.crystallize_lesson(lesson="测试规则：单元测试必须 100% 通过方可合并")
        assert res["admitted"] is True
        assert res["decision"] == "admit"
    finally:
        service.close()
