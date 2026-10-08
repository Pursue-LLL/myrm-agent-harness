"""Pre-seeded industrial business experience templates.

Provides standard cold-start templates for Business Analysis Review procedures
and Retail Exchange workflows with human escalation gates.
Aligned with OpenViking evaluation findings (PPT review & tau2 retail bench).

[INPUT]
- toolkits.memory.business_templates.models::BusinessExperienceTemplate, ChecklistStep, TemplateCategory (POS:
  Domain models for business experience templates and escalation checklists.)

[OUTPUT]
- None (no public symbols)

[POS]
Pre-seeded industrial business experience templates.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.business_templates.models import (
    BusinessExperienceTemplate,
    ChecklistStep,
    TemplateCategory,
)

SEED_BUSINESS_ANALYSIS_TEMPLATE = BusinessExperienceTemplate(
    template_id="BA-REV-01",
    name="经营分析与PPT复盘三方法经验模板",
    category=TemplateCategory.BUSINESS_ANALYSIS,
    summary="对标企业经营分析与PPT复盘场景的三类可复用方法：公式值回查、多源口径核对与交付前模板验收，复用检查方法而非历史旧数据。",
    checklist_steps=[
        ChecklistStep(
            step_index=1,
            name="复杂表格公式计算值回查",
            description="解析包含毛利率、环比增长等计算指标的复杂电子表格时，读取公式计算结果与缓存值，绝不可将原始公式字符串直接作为统计指标输出。",
            mandatory=True,
            validation_rule="cell_value != formula_raw_string and is_numeric(cell_value)",
        ),
        ChecklistStep(
            step_index=2,
            name="多源冲突数据口径显式核对",
            description="当销售台账、财务系统与一线客户反馈之间存在统计口径偏差时，在结论中明确注明各源口径及对齐依据，禁止单方面静默覆盖任一权威数据源。",
            mandatory=True,
            validation_rule="source_attribution_declared and conflict_resolution_noted",
        ),
        ChecklistStep(
            step_index=3,
            name="交付前规范模板验收检查",
            description="生成汇报图表与大纲前，核对数字可信度、结论逻辑链支撑以及格式规范，确保结论具备直接业务证据支持。",
            mandatory=True,
            validation_rule="verify_evidence_links and verify_chart_kpi_alignment",
        ),
    ],
    boundary_conditions=[
        "复用排障检查方法，严格禁止复用上一周期的业务数字",
        "涉及跨表引用时必须进行完整性校验",
    ],
    sample_trajectory_ref="traj_ppt_review_margin_analysis",
    version="1.1.0",
    tags=["business_analysis", "excel_formula", "ppt_review", "kpi_audit"],
    metadata={
        "domain": "management_reporting",
        "source": "OpenViking_experience_benchmark",
        "benchmark_provenance": "tau2_business_review",
    },
    validated_count=12,
    rejected_count=0,
)

SEED_RETAIL_EXCHANGE_TEMPLATE = BusinessExperienceTemplate(
    template_id="RET-EXC-01",
    name="消费者售后换货全链路先问必查标准规程",
    category=TemplateCategory.RETAIL_EXCHANGE,
    summary="零售与电商客服售后换货标准化流程：强制执行'先问身份意图、必查状态政策库存、确认后办理、告知后续'闭环，杜绝顺序颠倒导致违反政策。",
    checklist_steps=[
        ChecklistStep(
            step_index=1,
            name="先问: 身份、订单号与换货诉求",
            description="接入售后对话第一轮，必须先行核验用户身份凭证、关联有效订单号，并明确顾客的具体换货诉求（如尺码不合、质量问题或误购）。",
            mandatory=True,
            validation_rule="identity_verified and order_id_present and intent_classified",
        ),
        ChecklistStep(
            step_index=2,
            name="必查: 物流履约状态、售后政策与目标库存",
            description="在提出换货方案前，强制调用工具校验原订单物流签收状态、7天无理由退换货保质期，以及目标更换SKU的当前实时库存可用量。",
            mandatory=True,
            validation_rule="shipment_delivered and warranty_window_valid and target_sku_in_stock",
        ),
        ChecklistStep(
            step_index=3,
            name="显式确认: 换货明细与寄回协议",
            description="向用户出示更换的目标商品规格与寄回要求，必须等待用户显式确认同意后，方可调用后台换货单创建工具，严禁自主盲目提交。",
            mandatory=True,
            validation_rule="user_explicitly_confirmed_exchange_spec",
        ),
        ChecklistStep(
            step_index=4,
            name="办理: 原子创建换货单与物流标签",
            description="调用系统换货办理工具，原子生成换货服务单号与逆向物流寄件预约定单。",
            mandatory=True,
            validation_rule="exchange_order_created and rma_label_generated",
        ),
        ChecklistStep(
            step_index=5,
            name="告知后续: 退货指引与新包裹时效",
            description="向用户明确传达退货包裹寄回指引、质检时效以及换新包裹的预计发出与到达时间。",
            mandatory=True,
            validation_rule="return_instructions_dispatched and eta_timeline_communicated",
        ),
    ],
    boundary_conditions=[
        "严禁在未校验库存情况下承诺换新",
        "严禁在用户未确认前调用 commit_exchange 工具",
    ],
    sample_trajectory_ref="traj_tau2_retail_exchange_clean",
    version="1.2.0",
    tags=["retail", "customer_service", "exchange", "tau2_benchmark"],
    metadata={
        "domain": "e_commerce_service",
        "source": "tau2_retail_exchange_matrix",
    },
    validated_count=28,
    rejected_count=1,
)

SEED_ESCALATION_GATE_TEMPLATE = BusinessExperienceTemplate(
    template_id="ESC-GATE-01",
    name="售后与异常处置例外转人工决策门禁",
    category=TemplateCategory.ESCALATION_GATE,
    summary="智能客服与自主代理的安全护栏：针对政策模糊、目标商品断码缺货、用户争议纠正失败或情绪升级场景，实施确定性转人工拦截并生成交接单。",
    checklist_steps=[
        ChecklistStep(
            step_index=1,
            name="政策模糊与定制例外扫描",
            description="若涉及定制商品、内衣生鲜等特殊品类，或政策条款存在冲突解释时，立即挂起自主流程，触发例外转人工。",
            mandatory=True,
            validation_rule="policy_ambiguity_flag == True or is_custom_order == True",
        ),
        ChecklistStep(
            step_index=2,
            name="目标更换SKU缺货断码检查",
            description="若用户诉求更换的款式完全缺货且短期无法补货，禁止编造虚假承诺，直接引导转人工客服协商替代补偿方案。",
            mandatory=True,
            validation_rule="sku_inventory <= 0",
        ),
        ChecklistStep(
            step_index=3,
            name="用户纠错争议与情绪升级熔断",
            description="若用户连续两次纠正 Agent 结论，或检测到顾客强烈不满意情绪，立即熔断自动化处理，避免陷入循环争辩。",
            mandatory=True,
            validation_rule="user_dispute_count >= 2 or sentiment_escalated == True",
        ),
        ChecklistStep(
            step_index=4,
            name="结构化人工交接包组装",
            description="转人工时必须将已核验的身份、订单明细、用户诉求、缺货事实与已排查日志格式化打包，附送至人工客服界面。",
            mandatory=True,
            validation_rule="generate_human_handover_package",
        ),
    ],
    boundary_conditions=[
        "转人工后 Agent 自动切为只读辅助模式",
        "必须完整保留上下文证据链",
    ],
    sample_trajectory_ref="traj_escalation_out_of_stock_dispute",
    version="1.0.0",
    tags=["escalation", "safety_gate", "human_in_the_loop", "sentiment_guard"],
    metadata={
        "domain": "governance_and_safety",
        "source": "OpenViking_escalation_protocol",
    },
    validated_count=19,
    rejected_count=0,
)

SEED_TEMPLATES: list[BusinessExperienceTemplate] = [
    SEED_BUSINESS_ANALYSIS_TEMPLATE,
    SEED_RETAIL_EXCHANGE_TEMPLATE,
    SEED_ESCALATION_GATE_TEMPLATE,
]
