"""多代理共享草稿白板、子代理瞬态上下文隔离与轻量事实广播套件单元测试。

[INPUT]
- MultiAgentSharedScratchpadEngine, FactCategory, SubagentLifecycleStatus, ScratchpadQueryFilter, SharedScratchpadFact

[OUTPUT]
- 自动化验证子代理隔离注册、共享白板写入与检索去重、踩坑记录广播防重复试错、完结时瞬态日志彻底销毁垃圾回收

[POS]
- 位于 tests/agent/context_management/test_subagent_scratchpad_engine.py
"""

import pytest

from myrm_agent_harness.agent.context_management.subagent_scratchpad import (
    EphemeralSubagentDossier,
    FactCategory,
    MultiAgentSharedScratchpadEngine,
    ScratchpadQueryFilter,
    SharedScratchpadFact,
    SubagentLifecycleStatus,
)


def test_subagent_registration_and_transient_logging() -> None:
    """测试子代理隔离注册与内部瞬态排错日志记录。"""
    engine = MultiAgentSharedScratchpadEngine()

    dossier: EphemeralSubagentDossier = engine.register_subagent(
        subagent_id="subagent_api_crawler",
        cluster_id="cluster_research_01",
        role_name="API Crawler",
    )

    assert dossier.subagent_id == "subagent_api_crawler"
    assert dossier.cluster_id == "cluster_research_01"
    assert dossier.status == SubagentLifecycleStatus.ACTIVE
    assert dossier.transient_logs_count == 0

    # 记录瞬态排错日志
    engine.record_transient_log("subagent_api_crawler", "HTTP GET /api/v1/auth 返回 401，尝试刷新 Token")
    engine.record_transient_log("subagent_api_crawler", "Token 刷新成功，正在解析响应 JSON Schema")

    updated_dossier = engine.get_subagent_dossier("subagent_api_crawler")
    assert updated_dossier is not None
    assert updated_dossier.transient_logs_count == 2
    assert len(engine.get_transient_logs("subagent_api_crawler")) == 2


def test_post_and_query_shared_facts_with_filtering() -> None:
    """测试共享白板事实广播与多条件精准检索（防重复劳动与避免重踩已知坑）。"""
    engine = MultiAgentSharedScratchpadEngine()
    cluster = "cluster_eng_99"

    engine.register_subagent("agent_a", cluster, "Doc Reader")
    engine.register_subagent("agent_b", cluster, "Dev Tester")

    # 1. Agent A 沉淀已查明的接口规格
    fact_api = engine.post_shared_fact(
        cluster_id=cluster,
        subagent_id="agent_a",
        category=FactCategory.API_SPEC,
        key="payment_api_v2",
        summary="支付网关 V2 必须携带 X-Signature 头",
        details="签名算法为 HMAC-SHA256(timestamp + payload)",
        confidence=0.95,
    )
    assert fact_api.fact_id.startswith("fact_")

    # 2. Agent B 沉淀踩坑记录（Anti-Pattern）
    engine.post_shared_fact(
        cluster_id=cluster,
        subagent_id="agent_b",
        category=FactCategory.ANTI_PATTERN_PITFALL,
        key="port_8080_conflict",
        summary="本地端口 8080 已被宿主监控进程占用，禁止绑定",
        details="请改用 8088 端口启动本地 Mock 服务",
        confidence=1.0,
    )

    # 3. 并发 Agent C 查询所有事实
    all_facts = engine.query_shared_facts(cluster)
    assert len(all_facts) == 2

    # 4. 按踩坑类别过滤
    pitfalls = engine.query_shared_facts(
        cluster,
        filter_spec=ScratchpadQueryFilter(category=FactCategory.ANTI_PATTERN_PITFALL),
    )
    assert len(pitfalls) == 1
    assert pitfalls[0].key == "port_8080_conflict"

    # 5. 关键词过滤
    results_kw = engine.query_shared_facts(
        cluster,
        filter_spec=ScratchpadQueryFilter(keyword="payment"),
    )
    assert len(results_kw) == 1
    assert results_kw[0].key == "payment_api_v2"


def test_garbage_collect_subagent_cleans_transient_logs() -> None:
    """测试子代理任务结束时触发垃圾回收：彻底销毁内部排错日志，保留已提升事实。"""
    engine = MultiAgentSharedScratchpadEngine()
    cluster = "cluster_ops_01"

    engine.register_subagent("worker_sub_01", cluster, "Log Parser")
    engine.record_transient_log("worker_sub_01", "正在读取 100MB 访问日志...")
    engine.record_transient_log("worker_sub_01", "堆栈异常堆积: Traceback ...")

    # 提升关键公共事实
    fact = engine.post_shared_fact(
        cluster_id=cluster,
        subagent_id="worker_sub_01",
        category=FactCategory.ENVIRONMENT_TRUTH,
        key="db_connection_pool_limit",
        summary="数据库连接池上限为 20，当前闲置 15",
    )

    dossier_before = engine.get_subagent_dossier("worker_sub_01")
    assert dossier_before is not None
    assert dossier_before.transient_logs_count == 2
    assert fact.fact_id in dossier_before.promoted_fact_ids

    # 执行垃圾回收
    collected: EphemeralSubagentDossier = engine.garbage_collect_subagent("worker_sub_01")
    assert collected.status == SubagentLifecycleStatus.GARBAGE_COLLECTED
    assert collected.transient_logs_count == 0
    assert collected.collected_at_iso is not None

    # 验证瞬态日志被物理清空
    assert len(engine.get_transient_logs("worker_sub_01")) == 0

    # 验证公共白板中的高价值事实依然保留
    facts = engine.query_shared_facts(cluster)
    assert len(facts) == 1
    assert facts[0].key == "db_connection_pool_limit"


def test_gc_nonexistent_subagent_raises_error() -> None:
    """测试对不存在的子代理执行垃圾回收抛出 KeyError。"""
    engine = MultiAgentSharedScratchpadEngine()
    with pytest.raises(KeyError, match="子代理 nonexistent_id 不存在"):
        engine.garbage_collect_subagent("nonexistent_id")
