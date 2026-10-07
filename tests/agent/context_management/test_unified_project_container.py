"""单元测试：统一项目全生命周期资产容器、会话物理拖拽归档与零噪音静默收纳套件 (Item 190)。

覆盖测试点：
1. 项目真实工作区容器注册与初始全要素大盘聚合
2. 侧边栏 HTML5 物理拖拽会话原子收纳与跨项目迁移
3. 挂载多类别资产 (工件/里程碑/看板任务/工作卷) 与聚合统计
4. 非活跃会话单键静默归档隐藏与一键抽屉唤醒恢复
5. 错误边界处理与会话项目反向索引查询
"""

from myrm_agent_harness.agent.context_management.project_container import (
    DragDropIngestionEvent,
    ProjectAssetItem,
    ProjectAssetKind,
    ProjectContainerWorkspace,
    SessionVisibilityStatus,
    SilentArchivingResult,
    UnifiedProjectContainerEngine,
)


def test_project_container_registration_and_consolidation() -> None:
    """测试项目真实容器注册与初始大盘全景聚合。"""
    engine = UnifiedProjectContainerEngine()
    workspace = engine.register_or_update_project(
        project_id="proj_refactor_2026",
        name="2026 架构纯净重构项目",
        description="系统核心架构演进与全量解耦",
    )

    assert workspace.project_id == "proj_refactor_2026"
    assert workspace.project_name == "2026 架构纯净重构项目"
    assert workspace.description == "系统核心架构演进与全量解耦"
    assert len(workspace.assets) == 0
    assert len(workspace.active_session_ids) == 0
    assert len(workspace.archived_session_ids) == 0
    assert workspace.milestone_count == 0
    assert workspace.artifact_count == 0
    assert workspace.total_asset_count == 0


def test_drag_drop_session_ingestion_and_cross_project_transfer() -> None:
    """测试侧边栏 HTML5 拖拽收纳会话与跨项目原子迁移。"""
    engine = UnifiedProjectContainerEngine()
    engine.register_or_update_project("proj_alpha", "Alpha 调研项目")
    engine.register_or_update_project("proj_beta", "Beta 执行项目")

    # 1. 拖拽会话 session_101 归入 proj_alpha
    event1 = DragDropIngestionEvent(
        source_session_id="session_101",
        target_project_id="proj_alpha",
        session_title="技术选型探讨",
    )
    ws_alpha = engine.ingest_session_via_drag_drop(event1)

    assert "session_101" in ws_alpha.active_session_ids
    assert ws_alpha.total_asset_count == 1
    assert engine.get_project_for_session("session_101") == "proj_alpha"

    # 2. 跨项目拖拽：将 session_101 从 proj_alpha 迁移到 proj_beta
    event2 = DragDropIngestionEvent(
        source_session_id="session_101",
        target_project_id="proj_beta",
        session_title="技术选型探讨 (已确认)",
    )
    ws_beta = engine.ingest_session_via_drag_drop(event2)

    assert "session_101" in ws_beta.active_session_ids
    assert engine.get_project_for_session("session_101") == "proj_beta"

    # 验证旧项目 proj_alpha 中已被原子清除，防止多属混乱
    ws_alpha_updated = engine.consolidate_project_assets("proj_alpha")
    assert "session_101" not in ws_alpha_updated.active_session_ids
    assert ws_alpha_updated.total_asset_count == 0


def test_multi_kind_asset_attachment_and_consolidation() -> None:
    """测试统一容器挂载专业工件、阶段里程碑等并聚合统计。"""
    engine = UnifiedProjectContainerEngine()
    pid = "proj_office_suite"
    engine.register_or_update_project(pid, "智能办公套件")

    # 挂载 1 个会话、2 个工件、1 个交付里程碑
    session_asset = ProjectAssetItem(
        asset_id="sess_doc_gen",
        asset_kind=ProjectAssetKind.CONVERSATION_SESSION,
        title="Word 报告起草会话",
        resource_uri="session://sess_doc_gen",
    )
    artifact_1 = ProjectAssetItem(
        asset_id="art_docx_01",
        asset_kind=ProjectAssetKind.COMPILED_ARTIFACT,
        title="年终汇报草稿.docx",
        resource_uri="file:///workspace/output/report.docx",
    )
    artifact_2 = ProjectAssetItem(
        asset_id="art_pdf_02",
        asset_kind=ProjectAssetKind.COMPILED_ARTIFACT,
        title="架构全景设计图.pdf",
        resource_uri="file:///workspace/output/arch.pdf",
    )
    milestone_1 = ProjectAssetItem(
        asset_id="ms_phase1",
        asset_kind=ProjectAssetKind.DELIVERABLE_MILESTONE,
        title="M1 阶段交付验收",
        resource_uri="milestone://phase1",
    )

    engine.attach_asset(pid, session_asset)
    engine.attach_asset(pid, artifact_1)
    engine.attach_asset(pid, artifact_2)
    ws = engine.attach_asset(pid, milestone_1)

    assert ws.total_asset_count == 4
    assert ws.artifact_count == 2
    assert ws.milestone_count == 1
    assert "sess_doc_gen" in ws.active_session_ids


def test_toggle_session_silent_archiving_and_drawer_restore() -> None:
    """测试非活跃会话单键静默归档隐藏与一键抽屉唤醒恢复。"""
    engine = UnifiedProjectContainerEngine()
    pid = "proj_daily_ops"
    engine.register_or_update_project(pid, "日常运维大盘")

    # 摄入两个会话
    engine.ingest_session_via_drag_drop(
        DragDropIngestionEvent(source_session_id="s_active", target_project_id=pid)
    )
    engine.ingest_session_via_drag_drop(
        DragDropIngestionEvent(source_session_id="s_done", target_project_id=pid)
    )

    ws_init = engine.consolidate_project_assets(pid)
    assert len(ws_init.active_session_ids) == 2
    assert len(ws_init.archived_session_ids) == 0

    # 1. 静默隐藏 s_done
    res_hide = engine.toggle_session_silent_archiving("s_done", hide=True)
    assert res_hide.success is True
    assert res_hide.previous_status == SessionVisibilityStatus.ACTIVE_PRIMARY
    assert res_hide.current_status == SessionVisibilityStatus.SILENT_ARCHIVED

    ws_after_hide = engine.consolidate_project_assets(pid)
    assert "s_active" in ws_after_hide.active_session_ids
    assert "s_done" not in ws_after_hide.active_session_ids
    assert "s_done" in ws_after_hide.archived_session_ids

    # 2. 从归档抽屉一键唤醒恢复 s_done
    res_restore = engine.toggle_session_silent_archiving("s_done", hide=False)
    assert res_restore.success is True
    assert res_restore.current_status == SessionVisibilityStatus.ACTIVE_PRIMARY

    ws_after_restore = engine.consolidate_project_assets(pid)
    assert "s_done" in ws_after_restore.active_session_ids
    assert "s_done" not in ws_after_restore.archived_session_ids


def test_session_not_found_handling() -> None:
    """测试未注册会话操作的防御性容错。"""
    engine = UnifiedProjectContainerEngine()
    res = engine.toggle_session_silent_archiving("non_existent_session", hide=True)

    assert res.success is False
    assert "not found" in res.message
    assert engine.get_project_for_session("non_existent_session") is None
