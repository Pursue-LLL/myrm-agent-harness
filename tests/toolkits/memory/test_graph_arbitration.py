from __future__ import annotations

from myrm_agent_harness.toolkits.memory.graph_arbitration.arbitrator import (
    FactConflictArbitrator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.decay import (
    TemporalEdgeDecayCalculator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.disambiguation import (
    EntityDisambiguator,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.engine import (
    HierarchicalEntityGraphEngine,
)
from myrm_agent_harness.toolkits.memory.graph_arbitration.models import (
    ConflictResolutionAction,
    EntityNode,
    EntityRelationEdge,
    FactStatus,
)


def test_entity_disambiguation_normalization_and_merge() -> None:
    # 1. 规范化指纹测试
    assert EntityDisambiguator.normalize_name("Claude Code") == "claude_code"
    assert EntityDisambiguator.normalize_name("claude-code") == "claude_code"
    assert EntityDisambiguator.normalize_name("  Claude_Code! ") == "claude_code"

    # 2. 匹配已有别名
    node1 = EntityNode(
        node_id="n1",
        canonical_name="PostgreSQL",
        aliases=["postgres", "pgsql"],
        entity_type="database",
        description="RDBMS",
        created_at_epoch_s=1000.0,
        last_accessed_epoch_s=1000.0,
    )
    assert EntityDisambiguator.find_canonical_match("pgsql", [node1]) == node1
    assert EntityDisambiguator.find_canonical_match("postgre-sql", [node1]) == node1
    assert EntityDisambiguator.find_canonical_match("mysql", [node1]) is None

    # 3. 实体合并
    node2 = EntityNode(
        node_id="n2",
        canonical_name="postgres_db",
        aliases=["pg"],
        entity_type="database",
        description="",
        created_at_epoch_s=1500.0,
        last_accessed_epoch_s=2000.0,
    )
    edge1 = EntityRelationEdge(
        edge_id="e1",
        source_node_id="n2",  # 指向 node2
        target_node_id="target_db",
        predicate="instance_of",
        fact_value="sql_database",
        base_weight=1.0,
        dynamic_weight=1.0,
        status=FactStatus.ACTIVE,
        created_at_epoch_s=1500.0,
        last_verified_epoch_s=1500.0,
        access_count=1,
    )

    merged_node, retargeted_edges = EntityDisambiguator.merge_entities(
        node1, node2, [edge1]
    )
    assert "postgres_db" in merged_node.aliases
    assert "pg" in merged_node.aliases
    assert retargeted_edges[0].source_node_id == "n1"  # 边成功重定向至主实体


def test_temporal_edge_decay_calculator() -> None:
    t0 = 100000.0
    half_life_days = 14.0
    day_s = 86400.0

    # 1. 刚创建时无时间衰减
    decay_0 = TemporalEdgeDecayCalculator.calculate_temporal_decay(
        t0, t0, half_life_days
    )
    assert decay_0 == 1.0

    # 2. 经过 1 个半衰期（14 天），时间衰减因子约为 0.5
    decay_14d = TemporalEdgeDecayCalculator.calculate_temporal_decay(
        t0, t0 + 14.0 * day_s, half_life_days
    )
    assert abs(decay_14d - 0.5) < 0.01

    # 3. 频次增强测试
    boost_1 = TemporalEdgeDecayCalculator.calculate_frequency_boost(1)
    boost_10 = TemporalEdgeDecayCalculator.calculate_frequency_boost(10)
    assert boost_10 > boost_1

    # 4. 经过 100 天未验证，触发状态自动归档 ARCHIVED
    edge = EntityRelationEdge(
        edge_id="e_old",
        source_node_id="s1",
        target_node_id="t1",
        predicate="theme",
        fact_value="light",
        base_weight=0.5,
        dynamic_weight=0.5,
        status=FactStatus.ACTIVE,
        created_at_epoch_s=t0,
        last_verified_epoch_s=t0,
        access_count=1,
    )
    decayed_edge = TemporalEdgeDecayCalculator.apply_decay_to_edge(
        edge, t0 + 100.0 * day_s, half_life_days
    )
    assert decayed_edge.dynamic_weight < 0.10
    assert decayed_edge.status == FactStatus.ARCHIVED


def test_fact_conflict_arbitrator_reinforce_and_supersede() -> None:
    t0 = 1000.0
    edge_py = EntityRelationEdge(
        edge_id="e_py",
        source_node_id="user_1",
        target_node_id="tech_py",
        predicate="primary_stack",
        fact_value="Python",
        base_weight=0.8,
        dynamic_weight=0.8,
        status=FactStatus.ACTIVE,
        created_at_epoch_s=t0,
        last_verified_epoch_s=t0,
        access_count=1,
    )

    # 1. 重复确认相同事实 -> 强化
    edge_py_repeat = EntityRelationEdge(
        edge_id="e_py_2",
        source_node_id="user_1",
        target_node_id="tech_py",
        predicate="primary_stack",
        fact_value="python",  # 大小写不敏感等价
        base_weight=0.8,
        dynamic_weight=0.8,
        status=FactStatus.ACTIVE,
        created_at_epoch_s=t0 + 100.0,
        last_verified_epoch_s=t0 + 100.0,
        access_count=1,
    )
    result_reinforce, updated_edges = FactConflictArbitrator.arbitrate(
        edge_py_repeat, [edge_py]
    )
    assert result_reinforce.action == ConflictResolutionAction.REINFORCE_EXISTING
    assert len(updated_edges) == 1
    assert updated_edges[0].access_count == 2
    assert updated_edges[0].base_weight > 0.8

    # 2. 互斥的新事实（时间更新）-> 覆写旧事实
    edge_rust = EntityRelationEdge(
        edge_id="e_rust",
        source_node_id="user_1",
        target_node_id="tech_rust",
        predicate="primary_stack",
        fact_value="Rust",
        base_weight=1.0,
        dynamic_weight=1.0,
        status=FactStatus.ACTIVE,
        created_at_epoch_s=t0 + 500.0,
        last_verified_epoch_s=t0 + 500.0,
        access_count=1,
    )
    result_supersede, edges_after_rust = FactConflictArbitrator.arbitrate(
        edge_rust, updated_edges
    )
    assert result_supersede.action == ConflictResolutionAction.SUPERSEDE_OLD
    assert "e_py" in result_supersede.superseded_edge_ids
    assert len(edges_after_rust) == 2

    old_py_edge = next(e for e in edges_after_rust if e.edge_id == "e_py")
    assert old_py_edge.status == FactStatus.SUPERSEDED
    assert old_py_edge.causal_superseded_by == "e_rust"

    active_rust_edge = next(e for e in edges_after_rust if e.edge_id == "e_rust")
    assert active_rust_edge.status == FactStatus.ACTIVE


def test_hierarchical_entity_graph_engine_end_to_end() -> None:
    engine = HierarchicalEntityGraphEngine()
    t_start = 10000.0

    # 1. 插入实体与初始事实
    res1 = engine.add_fact(
        source_name="Alice",
        predicate="favorite_framework",
        fact_value="FastAPI",
        current_epoch_s=t_start,
    )
    assert res1.action == ConflictResolutionAction.COEXIST
    assert engine.nodes_count == 2  # Alice and global
    assert engine.edges_count == 1

    # 2. 强化既有事实
    res2 = engine.add_fact(
        source_name="Alice",
        predicate="favorite_framework",
        fact_value="fastapi",  # 等价强化
        current_epoch_s=t_start + 1000.0,
    )
    assert res2.action == ConflictResolutionAction.REINFORCE_EXISTING
    assert engine.edges_count == 1

    # 3. 7 天后全面切换为 Axum
    t_later = t_start + 7.0 * 86400.0
    res3 = engine.add_fact(
        source_name="alice",  # 别名/小写自动消歧对齐
        predicate="favorite_framework",
        fact_value="Axum",
        current_epoch_s=t_later,
    )
    assert res3.action == ConflictResolutionAction.SUPERSEDE_OLD
    assert engine.edges_count == 2

    # 4. 查询当前活跃事实，验证仅返回最新的 Axum
    active_facts = engine.query_active_facts("Alice")
    assert len(active_facts) == 1
    assert active_facts[0].fact_value == "Axum"
    assert active_facts[0].status == FactStatus.ACTIVE

    # 5. 查询因果演进谱系，验证保留了从 FastAPI 到 Axum 的完整覆写痕迹
    lineage = engine.get_fact_lineage("Alice", "favorite_framework")
    assert len(lineage) == 2
    assert lineage[0].fact_value == "FastAPI"
    assert lineage[0].status == FactStatus.SUPERSEDED
    assert lineage[0].causal_superseded_by == lineage[1].edge_id
    assert lineage[1].fact_value == "Axum"
    assert lineage[1].status == FactStatus.ACTIVE

    # 6. 运行时间衰减
    t_future = t_later + 30.0 * 86400.0
    engine.decay_graph(current_epoch_s=t_future)
    updated_active = engine.query_active_facts("Alice", min_weight=0.01)
    assert len(updated_active) == 1
    assert updated_active[0].dynamic_weight < 1.0
