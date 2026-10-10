"""Unit tests for Cross-Source Context Fabric and Project Entity Linker suite (Item 153).

[INPUT]
- Mock work events, project registries, candidate insights, temporary workspace directories.

[OUTPUT]
- Asserts on entity extraction, project matching, insight sinking, and provenance tracking.

[POS]
- Harness test suite for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory.context_fabric import (
    ContextFabricExtractor,
    InsightCandidate,
    InsightSinkEngine,
    ProjectEntityLinker,
    ProjectRegistryEntry,
    SourceKind,
    WorkEvent,
)
from myrm_agent_harness.toolkits.memory.project_dongle import (
    DongleBlockType,
    ProjectContextDongleManager,
)


def test_extract_unstructured_entities_and_commitments() -> None:
    extractor = ContextFabricExtractor()
    raw_text = """
    项目: 北京站
    由@张三 负责票务闸机改造，承诺在 2026-10-25 完成联调。
    阻塞原因: 硬件供应商尚未提供最新驱动。
    """
    event = WorkEvent(
        event_id="ev_001",
        source_kind=SourceKind.FEISHU,
        source_id="msg_9988",
        title="北京站闸机改造例会",
        raw_content=raw_text,
    )

    entities = extractor.extract_from_event(event)
    entity_types = {e.entity_type for e in entities}

    assert "module" in entity_types or "person" in entity_types
    assert "person" in entity_types
    assert "commitment" in entity_types
    assert "blocker" in entity_types

    # Validate specific fields
    person = next(e for e in entities if e.entity_type == "person")
    assert "张三" in person.name

    commitment = next(e for e in entities if e.entity_type == "commitment")
    assert commitment.temporal_anchor == "2026-10-25"

    blocker = next(e for e in entities if e.entity_type == "blocker")
    assert "硬件供应商" in blocker.name


def test_project_entity_linker_matching() -> None:
    linker = ProjectEntityLinker()
    linker.register_project(
        ProjectRegistryEntry(
            project_id="proj_bj",
            name="北京站",
            aliases=("北京项目", "BJ-Station"),
            keywords=("闸机", "票务", "安检"),
            description="北京站智慧客流与通行治理",
        )
    )
    linker.register_project(
        ProjectRegistryEntry(
            project_id="proj_sh",
            name="上海虹桥",
            aliases=("虹桥枢纽",),
            keywords=("行李寄存", "VIP休息室"),
            description="上海虹桥智慧枢纽",
        )
    )

    # 1. Exact name + keyword match
    matches = linker.link_text("本次访谈主要复盘北京站闸机扫码异常问题")
    assert len(matches) >= 1
    assert matches[0].project_id == "proj_bj"
    assert matches[0].is_definitive is True
    assert matches[0].confidence_score >= 0.7

    # 2. Alias match
    alias_matches = linker.link_text("关于 BJ-Station 的需求变更单")
    assert len(alias_matches) >= 1
    assert alias_matches[0].project_id == "proj_bj"

    # 3. Unrelated text
    unrelated_matches = linker.link_text("今天天气不错，下午一起去喝咖啡吧")
    assert len(unrelated_matches) == 0


def test_insight_sink_with_dongle_persistence() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace_path = Path(tmp_dir)

        linker = ProjectEntityLinker(
            initial_projects=[
                ProjectRegistryEntry(
                    project_id="proj_bj",
                    name="北京站",
                    aliases=("BJ-Station",),
                    keywords=("闸机", "检票"),
                )
            ]
        )
        dongle_mgr = ProjectContextDongleManager()
        sink_engine = InsightSinkEngine(linker=linker, dongle_manager=dongle_mgr)

        candidate = InsightCandidate(
            insight_id="ins_001",
            title="北京站闸机网络重试超时需从 3s 调整为 800ms",
            content="用户在弱网环境下极易触发闸机红灯卡阻，建议引入本地离线凭证缓存",
            source_event_ids=("feishu_msg_101", "interview_audio_md"),
            target_project_id=None,  # Intentionally unset, tests auto-linking
            impact_level="high",
        )

        record = sink_engine.sink_insight(
            candidate,
            workspace_dir=workspace_path,
            target_file_type=DongleBlockType.PROJECT_STATE,
        )

        assert record is not None
        assert record.project_id == "proj_bj"
        assert record.provenance_tag == "prov:feishu_msg_101,interview_audio_md"

        # Check dongle state reflects the sunken insight
        state = dongle_mgr.load_state(workspace_path)
        assert len(state.project_state_blocks) == 1
        sunken_block = state.project_state_blocks[0]
        assert "北京站" in sunken_block.content
        assert "闸机网络重试超时" in sunken_block.content
        assert "insight" in sunken_block.tags


def test_insight_sink_idempotency() -> None:
    linker = ProjectEntityLinker(
        initial_projects=[
            ProjectRegistryEntry(
                project_id="proj_bj",
                name="北京站",
            )
        ]
    )
    sink_engine = InsightSinkEngine(linker=linker)

    candidate = InsightCandidate(
        insight_id="ins_idemp",
        title="北京站架构定案",
        content="采用轻量边缘节点同步策略",
        source_event_ids=("linear_issue_42",),
        target_project_id="proj_bj",
    )

    first_record = sink_engine.sink_insight(candidate)
    assert first_record is not None

    second_record = sink_engine.sink_insight(candidate)
    assert second_record is not None
    assert first_record.record_id == second_record.record_id
    assert len(sink_engine.list_sink_records()) == 1
