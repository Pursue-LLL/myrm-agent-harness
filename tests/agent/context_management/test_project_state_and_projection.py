# [POS] tests/test_project_state_and_projection.py
# [INPUT] ProjectStateLivingFactLedger, FourTierContextProjectionEngine, ValidationGatedPromotionGate, LivingFact, ProjectFactType, FactPromotionStage, ProjectionQuery, ValidationAuditInput
# [OUTPUT] pytest test suite for project state ledger and context projection

"""面向长期项目的动态事实状态账本与四层级联上下文投影套件单元测试。"""


from myrm_agent_harness.agent.context_management.project_state import (
    FactPromotionStage,
    FourTierContextProjectionEngine,
    ProjectFactType,
    ProjectionQuery,
    ProjectStateLivingFactLedger,
    ValidationAuditInput,
    ValidationGatedPromotionGate,
)


def test_living_fact_ledger_crud_and_lookup() -> None:
    """测试账本的基本登记、多条件检索与删除。"""
    ledger = ProjectStateLivingFactLedger()
    project_id = "proj-alpha"

    fact = ledger.create_fact(
        project_id=project_id,
        fact_id="fact-1",
        fact_type=ProjectFactType.CONSTRAINT,
        title="单文件行数限制",
        content="单个文件原则上不能超过400行",
        target_components=["core", "agent"],
        reason_or_constraint="保持极高可维护性与单一职责",
    )
    assert fact.fact_id == "fact-1"
    assert fact.validation_count == 0

    retrieved = ledger.get_fact(project_id, "fact-1")
    assert retrieved is not None
    assert retrieved.title == "单文件行数限制"

    # 按组件检索
    matched = ledger.find_by_components(project_id, ["agent"])
    assert len(matched) == 1
    assert matched[0].fact_id == "fact-1"

    # 按不存在的组件检索
    matched_empty = ledger.find_by_components(project_id, ["nonexistent"])
    assert len(matched_empty) == 0

    # 删除
    assert ledger.remove_fact(project_id, "fact-1") is True
    assert ledger.get_fact(project_id, "fact-1") is None


def test_validation_gate_promotion_and_regression() -> None:
    """测试验证审计网关的经验晋升阶梯与回归降级逻辑。"""
    ledger = ProjectStateLivingFactLedger()
    gate = ValidationGatedPromotionGate(ledger)
    project_id = "proj-beta"

    # 1. 登记一条临时观察
    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-obs",
        fact_type=ProjectFactType.DECISION,
        title="使用 SQLite WAL 模式",
        content="开启 WAL 模式提升并发读写吞吐",
        stage=FactPromotionStage.OBSERVATION,
    )

    # 第一次验证通过 -> 晋升为 CONFIRMED_FACT
    res1 = gate.audit_validation(
        ValidationAuditInput(
            project_id=project_id,
            fact_id="fact-obs",
            passed=True,
            test_summary="SQLite WAL 并发测试 100% 通过",
        )
    )
    assert res1.is_promoted is True
    assert res1.new_stage == FactPromotionStage.CONFIRMED_FACT
    assert res1.validation_count == 1

    # 第二次验证通过 -> 晋升为 KNOWLEDGE (验证次数 >= 2 且零回归)
    res2 = gate.audit_validation(
        ValidationAuditInput(
            project_id=project_id,
            fact_id="fact-obs",
            passed=True,
            test_summary="压测 500 轮无锁冲突",
        )
    )
    assert res2.is_promoted is True
    assert res2.new_stage == FactPromotionStage.KNOWLEDGE
    assert res2.validation_count == 2

    # 发生回归测试失败 -> 降级回 CONFIRMED_FACT 且 regression_count 递增
    res_fail = gate.audit_validation(
        ValidationAuditInput(
            project_id=project_id,
            fact_id="fact-obs",
            passed=False,
            test_summary="极端掉电测试发现 WAL 文件未完全同步",
        )
    )
    assert res_fail.is_promoted is False
    assert res_fail.new_stage == FactPromotionStage.CONFIRMED_FACT
    assert res_fail.regression_count == 1


def test_validation_gate_skill_extraction_recommendation() -> None:
    """测试经过持续多次稳定复验后推荐下沉为 Skill。"""
    ledger = ProjectStateLivingFactLedger()
    gate = ValidationGatedPromotionGate(ledger)
    project_id = "proj-gamma"

    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-repeat",
        fact_type=ProjectFactType.DECISION,
        title="四层投影路由算法",
        content="基于规则、拓扑与语义分级截断",
        stage=FactPromotionStage.KNOWLEDGE,
    )

    # 模拟多次验证通过
    for _ in range(4):
        gate.audit_validation(
            ValidationAuditInput(
                project_id=project_id,
                fact_id="fact-repeat",
                passed=True,
                test_summary="多轮单测稳定通过",
            )
        )

    updated = ledger.get_fact(project_id, "fact-repeat")
    assert updated is not None
    assert updated.validation_count == 4
    assert updated.promotion_stage == FactPromotionStage.SKILL


def test_four_tier_context_projection_pipeline() -> None:
    """测试四层级联投影流水线：规则匹配、反模式展开、语义匹配与路由截断。"""
    ledger = ProjectStateLivingFactLedger()
    engine = FourTierContextProjectionEngine(ledger)
    project_id = "proj-delta"

    # 1. 约束 (Tier 1 目标组件直接约束)
    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-c1",
        fact_type=ProjectFactType.CONSTRAINT,
        title="严禁使用 Any 类型",
        content="所有模块必须具有具体的显式 Type Hints",
        target_components=["EnergyChart"],
        reason_or_constraint="消除动态类型隐患",
    )

    # 2. 正式接口 (Tier 1 直接契约)
    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-i1",
        fact_type=ProjectFactType.INTERFACE_CONTRACT,
        title="EnergyTrend API V2",
        content="GET /api/v2/energy/trend 返回标准 TimeSeries 数据点",
        target_components=["EnergyChart"],
    )

    # 3. 被否决方案 (Tier 2 必须展开的反模式)
    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-r1",
        fact_type=ProjectFactType.REJECTED_ALTERNATIVE,
        title="客户端暴力轮询方案",
        content="前端每秒调用接口刷新图表",
        target_components=["EnergyChart"],
        reason_or_constraint="导致服务端过载且耗尽电池，已否决，改为 SSE 推送",
    )

    # 4. 语义相关事实 (Tier 3 语义匹配)
    ledger.create_fact(
        project_id=project_id,
        fact_id="fact-s1",
        fact_type=ProjectFactType.VALIDATION_RESULT,
        title="图表重绘性能基准",
        content="使用虚拟滚动优化大数据量渲染吞吐",
        target_components=["GeneralUI"],
        reason_or_constraint="渲染超过 10000 点时保持 60fps",
    )

    # 执行投影
    query = ProjectionQuery(
        project_id=project_id,
        target_task="重构 EnergyChart 图表渲染性能与数据源对接",
        target_components=["EnergyChart"],
        token_budget=1500,
    )
    result = engine.project_context(query)

    assert result.project_id == project_id
    assert len(result.facts) >= 3
    # 验证反模式已被准确投影入块
    assert "REJECTED ALTERNATIVES - DO NOT RETRY" in result.formatted_prompt_block
    assert "客户端暴力轮询方案" in result.formatted_prompt_block
    assert "严禁使用 Any 类型" in result.formatted_prompt_block
    assert "EnergyTrend API V2" in result.formatted_prompt_block
    assert result.projected_by_tier["rule_projection"] >= 2
    assert result.projected_by_tier["dependency_expansion"] >= 1


def test_projection_empty_and_budget_truncation() -> None:
    """测试空事实集投影与严格预算截断。"""
    ledger = ProjectStateLivingFactLedger()
    engine = FourTierContextProjectionEngine(ledger)

    # 空项目投影
    empty_res = engine.project_context(
        ProjectionQuery(project_id="proj-empty", target_task="test")
    )
    assert empty_res.facts == []
    assert empty_res.formatted_prompt_block == ""
    assert empty_res.total_tokens_estimated == 0

    # 极低 token 预算测试
    ledger.create_fact(
        project_id="proj-small",
        fact_id="f1",
        fact_type=ProjectFactType.CONSTRAINT,
        title="约束 A" * 10,
        content="内容 A" * 20,
    )
    ledger.create_fact(
        project_id="proj-small",
        fact_id="f2",
        fact_type=ProjectFactType.DECISION,
        title="决策 B" * 10,
        content="内容 B" * 20,
    )

    small_res = engine.project_context(
        ProjectionQuery(
            project_id="proj-small",
            target_task="任务",
            token_budget=30,  # 极低预算
        )
    )
    # 应截断仅保留优先级最高的一项
    assert len(small_res.facts) == 1
    assert small_res.facts[0].fact_type == ProjectFactType.CONSTRAINT
