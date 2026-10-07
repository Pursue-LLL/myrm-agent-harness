# [POS] tests/test_dependency_expansion_and_dual_track.py
# [INPUT] ArchitecturalDependencyGraphExpander, AdaptiveComplexityGovernor, ArchitectureNode, ArchitectureNodeType, DependencyEdge, DependencyEdgeType, TaskComplexityTrack
# [OUTPUT] pytest test suite for architectural dependency expansion and dual-track scheduler

"""全链路跨栈架构依赖展开图谱与任务复杂度自适应双轨调度单测。"""

from myrm_agent_harness.agent.context_management.dependency_expansion import (
    AdaptiveComplexityGovernor,
    ArchitecturalDependencyGraphExpander,
    ArchitectureNode,
    ArchitectureNodeType,
    DependencyEdge,
    DependencyEdgeType,
    TaskComplexityTrack,
)


def test_dependency_graph_cascade_expansion_and_blast_radius() -> None:
    """验证从前端 UI 组件出发级联展开 API、数据模型与架构决议的全链路拓扑。"""
    expander = ArchitecturalDependencyGraphExpander()

    # 1. 注册跨栈节点
    ui_node = ArchitectureNode(
        node_id="ui-energy-chart",
        node_type=ArchitectureNodeType.COMPONENT,
        name="EnergyTrendChart",
        file_path="src/components/EnergyTrendChart.tsx",
        description="能源消耗与碳排放趋势折线图",
    )
    lib_node = ArchitectureNode(
        node_id="lib-echarts",
        node_type=ArchitectureNodeType.DEPENDENCY,
        name="ECharts-Core",
        description="百度 ECharts 渲染引擎 V5",
    )
    api_node = ArchitectureNode(
        node_id="api-energy-trend",
        node_type=ArchitectureNodeType.API,
        name="GET /api/v2/energy/trend",
        file_path="app/api/energy/trend.py",
        description="能源时序指标聚合接口",
    )
    model_node = ArchitectureNode(
        node_id="model-energy-point",
        node_type=ArchitectureNodeType.DATA_MODEL,
        name="EnergyMetricTimeSeriesRecord",
        file_path="app/database/models/energy.py",
        description="按分钟归档的原始能源上报时序表",
    )
    decision_node = ArchitectureNode(
        node_id="dec-sse-push",
        node_type=ArchitectureNodeType.ARCHITECTURAL_DECISION,
        name="采纳 SSE 增量推流模式",
        description="大屏高频刷新统一走 SSE，杜绝前端短轮询打崩网关",
    )
    rejected_node = ArchitectureNode(
        node_id="rej-client-poll",
        node_type=ArchitectureNodeType.ARCHITECTURAL_DECISION,
        name="否决前端客户端 1s 轮询方案",
        description="高频轮询导致服务端连接打满与移动端电池骤降",
    )

    for n in (ui_node, lib_node, api_node, model_node, decision_node, rejected_node):
        expander.add_node(n)

    # 2. 构建级联边
    expander.add_edge(DependencyEdge("ui-energy-chart", "lib-echarts", DependencyEdgeType.DEPENDS_ON))
    expander.add_edge(DependencyEdge("ui-energy-chart", "api-energy-trend", DependencyEdgeType.CALLS))
    expander.add_edge(DependencyEdge("api-energy-trend", "model-energy-point", DependencyEdgeType.BINDS_MODEL))
    expander.add_edge(DependencyEdge("api-energy-trend", "dec-sse-push", DependencyEdgeType.CONSTRAINED_BY))
    expander.add_edge(DependencyEdge("ui-energy-chart", "rej-client-poll", DependencyEdgeType.REJECTED_ALTERNATIVE))

    # 3. 执行级联展开 (从 UI 组件出发)
    result = expander.expand_dependencies("ui-energy-chart", max_depth=3)

    assert result.target_node_id == "ui-energy-chart"
    assert len(result.visited_nodes) == 6
    assert result.blast_radius_score > 20.0  # 涉及 API 与数据模型，影响面显著
    assert len(result.critical_constraints) >= 1
    assert "采纳 SSE 增量推流模式" in result.critical_constraints[0]
    assert len(result.rejected_alternatives) >= 1
    assert "否决前端客户端 1s 轮询方案" in result.rejected_alternatives[0]

    # 4. 验证渲染提示词块包含关键要素
    block = result.formatted_expansion_block
    assert "<architectural_dependency_graph>" in block
    assert "EnergyTrendChart" in block
    assert "GET /api/v2/energy/trend" in block
    assert "EnergyMetricTimeSeriesRecord" in block
    assert "REJECTED ALTERNATIVES - DO NOT RETRY" in block


def test_dependency_graph_empty_and_isolated_node() -> None:
    """测试不存在节点与孤立节点的图谱展开兜底行为。"""
    expander = ArchitecturalDependencyGraphExpander()

    # 孤立节点
    iso = ArchitectureNode(
        node_id="iso-1",
        node_type=ArchitectureNodeType.COMPONENT,
        name="SingleHelper",
    )
    expander.add_node(iso)

    res = expander.expand_dependencies("iso-1")
    assert res.target_node_id == "iso-1"
    assert len(res.visited_nodes) == 1
    assert res.blast_radius_score == 0.0
    assert res.critical_constraints == []
    assert res.rejected_alternatives == []

    # 不存在的节点
    nonexistent = expander.expand_dependencies("nonexistent-id")
    assert nonexistent.visited_nodes == []
    assert nonexistent.blast_radius_score == 0.0
    assert nonexistent.formatted_expansion_block == ""


def test_adaptive_complexity_governor_routing() -> None:
    """测试任务复杂度动态感知双轨调度器的分流规则。"""
    governor = AdaptiveComplexityGovernor(multi_component_threshold=2)

    # 1. 轻量任务 -> FAST_LEAN (零开销，跳过状态写盘)
    c1 = governor.classify_task_complexity("fix typo in login button", ["LoginButton.tsx"])
    assert c1.track == TaskComplexityTrack.FAST_LEAN
    assert c1.bypass_state_sync is True
    assert c1.estimated_token_overhead == 0

    c2 = governor.classify_task_complexity("单文件脚本临时测试", [])
    assert c2.track == TaskComplexityTrack.FAST_LEAN
    assert c2.bypass_state_sync is True

    # 2. 多组件任务 (>=2) -> FULL_WORKBENCH
    c3 = governor.classify_task_complexity(
        "update styles", ["Header.tsx", "Footer.tsx", "Sidebar.tsx"]
    )
    assert c3.track == TaskComplexityTrack.FULL_WORKBENCH
    assert c3.bypass_state_sync is False
    assert c3.estimated_token_overhead > 0

    # 3. 复杂重构关键词特征 -> FULL_WORKBENCH
    c4 = governor.classify_task_complexity("全链路重构用户认证与会话管理", ["auth.py"])
    assert c4.track == TaskComplexityTrack.FULL_WORKBENCH
    assert c4.bypass_state_sync is False
    assert "refactor" in c4.reason.lower() or "重构" in c4.reason

    # 4. 多回合长周期项目显式标记 -> FULL_WORKBENCH
    c5 = governor.classify_task_complexity(
        "简单改动", ["test.py"], is_multi_turn_project_session=True
    )
    assert c5.track == TaskComplexityTrack.FULL_WORKBENCH
    assert c5.bypass_state_sync is False
