"""Unit tests for Long-Horizon Project Milestone Checkpoint and Resumption Engine.

Verifies project milestone lifecycle transitions, immutable decision tracking,
dependent TODO topology calculations, incremental material delta extraction,
and zero-drift resumption prompt synthesis.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.incremental_material_hydration_engine import (
    IncrementalMaterialHydrationEngine,
)
from myrm_agent_harness.runtime.context.project_milestone_tracker import (
    ProjectMilestoneTracker,
)
from myrm_agent_harness.runtime.context.project_milestone_types import (
    MilestonePhaseKind,
)


def test_milestone_lifecycle_and_decision_tracking() -> None:
    """Verifies sequential phase progression and preservation of committed decisions."""
    tracker = ProjectMilestoneTracker()
    project_id = "proj_ecommerce_refactor"

    # 1. Initialize project
    init_cp = tracker.init_project(
        project_id,
        initial_phase=MilestonePhaseKind.REQUIREMENTS_ANALYSIS,
    )
    assert init_cp.phase == MilestonePhaseKind.REQUIREMENTS_ANALYSIS
    assert len(init_cp.completed_milestones) == 0

    # 2. Commit two foundational decisions
    dec1 = tracker.record_decision(
        project_id=project_id,
        title="技术选型：使用 SQLite + WAL 模式单机存储",
        rationale="单机极致性能与零外部网络运维开销。",
    )
    dec2 = tracker.record_decision(
        project_id=project_id,
        title="架构分层：Harness 与 Server 严格解耦",
        rationale="保证框架纯净开源且业务可定制。",
    )
    assert dec1.status == "active"
    assert dec2.status == "active"

    # 3. Advance to Architecture Design
    cp_arch = tracker.advance_phase(
        project_id=project_id,
        new_phase=MilestonePhaseKind.ARCHITECTURE_DESIGN,
        milestone_title="完成需求梳理与核心约束确认",
    )
    assert cp_arch.phase == MilestonePhaseKind.ARCHITECTURE_DESIGN
    assert len(cp_arch.completed_milestones) == 1
    assert "需求梳理" in cp_arch.completed_milestones[0]
    assert len(cp_arch.active_decisions) == 2

    # 4. Advance to Core Implementation
    cp_impl = tracker.advance_phase(
        project_id=project_id,
        new_phase=MilestonePhaseKind.CORE_IMPLEMENTATION,
        milestone_title="完成架构设计文档与分层接口契约",
    )
    assert cp_impl.phase == MilestonePhaseKind.CORE_IMPLEMENTATION
    assert len(cp_impl.completed_milestones) == 2


def test_dependent_todo_topology_calculation() -> None:
    """Verifies that only dependency-satisfied TODO items are surfaced as ready."""
    tracker = ProjectMilestoneTracker()
    project_id = "proj_topology_eval"
    tracker.init_project(project_id)

    # Chain: task_db -> task_api -> task_ui
    tracker.add_todo(
        project_id=project_id,
        todo_id="task_db",
        title="构建底层数据库 Schema 与迁移脚本",
        depends_on=(),
        priority="high",
    )
    tracker.add_todo(
        project_id=project_id,
        todo_id="task_api",
        title="开发 REST 与 WebSocket 接口网关",
        depends_on=("task_db",),
        priority="high",
    )
    tracker.add_todo(
        project_id=project_id,
        todo_id="task_ui",
        title="实现前端可视化控制面板",
        depends_on=("task_api",),
        priority="normal",
    )

    # 1. Initially, only task_db is ready
    ready_initial = tracker.compute_ready_todos(project_id)
    assert ready_initial == ("task_db",)

    # 2. Resolving task_db unblocks task_api
    tracker.resolve_todo(project_id, "task_db")
    ready_after_db = tracker.compute_ready_todos(project_id)
    assert ready_after_db == ("task_api",)

    # 3. Resolving task_api unblocks task_ui
    tracker.resolve_todo(project_id, "task_api")
    ready_after_api = tracker.compute_ready_todos(project_id)
    assert ready_after_api == ("task_ui",)


def test_incremental_material_diff_extraction() -> None:
    """Verifies semantic isolation of new requirements, modified constraints, and deprecations."""
    engine = IncrementalMaterialHydrationEngine()
    raw_material = """
    # 2026 业务重构补充技术规范
    - 新增特性：新增支持 OAuth2 PKCE 授权码模式认证流
    - 约束更新：将数据库连接池超时限制为 15s
    - 废弃声明：废弃旧版基于 Cookie 的明文 Session 校验
    - 其他普通背景说明描述行
    """

    diff = engine.extract_incremental_diff(
        raw_text=raw_material,
        source_name="PRD_v2_addendum.md",
    )

    assert diff.source_name == "PRD_v2_addendum.md"
    assert len(diff.new_requirements) == 1
    assert "OAuth2 PKCE" in diff.new_requirements[0]

    assert len(diff.modified_constraints) == 1
    assert "15s" in diff.modified_constraints[0]

    assert len(diff.deprecated_items) == 1
    assert "废弃旧版" in diff.deprecated_items[0]


def test_resumption_package_synthesis_zero_drift() -> None:
    """Verifies that the resumption package carries both historical decisions and new deltas."""
    tracker = ProjectMilestoneTracker()
    engine = IncrementalMaterialHydrationEngine()
    project_id = "proj_astra_weekly_resumption"

    # Setup project with history
    tracker.init_project(project_id, initial_phase=MilestonePhaseKind.CORE_IMPLEMENTATION)
    tracker.record_decision(
        project_id=project_id,
        title="严格 0 Any 编码规范",
        rationale="确保代码可维护性与类型安全。",
    )
    tracker.add_todo(
        project_id=project_id,
        todo_id="todo_101",
        title="编写单元测试覆盖",
        depends_on=(),
        priority="high",
    )
    tracker.register_deliverables(project_id, ["src/core/engine.py"])

    # User returns next week and injects new spec
    new_spec = "- 新增特性：支持 Prometheus 性能度量导出"
    engine.hydrate_material(
        project_id=project_id,
        raw_material=new_spec,
        source_name="monitoring_spec.md",
        tracker=tracker,
    )

    # Synthesize resumption package
    pkg = engine.synthesize_resumption_package(
        project_id=project_id,
        tracker=tracker,
        custom_guidance="请优先推进 Prometheus 监控模块的单测编写。",
    )

    assert pkg.project_id == project_id
    assert pkg.current_phase == MilestonePhaseKind.CORE_IMPLEMENTATION
    assert pkg.pending_todo_count == 1
    assert pkg.ready_todo_ids == ("todo_101",)

    # Verify panorama
    assert "CORE_IMPLEMENTATION" in pkg.panorama_summary
    assert "src/core/engine.py" not in pkg.panorama_summary  # file count is listed
    assert "交付物产出文件: 1 个" in pkg.panorama_summary

    # Verify resumption prompt zero-drift guarantees
    assert "严格 0 Any 编码规范" in pkg.resumption_prompt
    assert "Prometheus 性能度量" in pkg.resumption_prompt
    assert "todo_101" in pkg.resumption_prompt
    assert "请优先推进 Prometheus 监控模块" in pkg.resumption_prompt
