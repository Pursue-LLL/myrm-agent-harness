"""PDF Template Registry implementation - Single Source of Truth.

[INPUT]
.manifest::PdfTemplateCategory, PdfTemplateManifest, PdfTemplateVariableSchema (POS: data contracts)
pathlib::Path (POS: filesystem template resolution)

[OUTPUT]
- PdfTemplateRegistry: Singleton / class-based registry managing all registered PDF templates
- get_pdf_template_registry(): Global singleton accessor for PdfTemplateRegistry

[POS]
Maintains the centralized registry for PDF templates in the framework.
Provides registration, lookup, categorization, validation against JSON schemas,
and built-in default templates (Invoices, Business Reports, Receipts, Audit Reports).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .manifest import (
    PdfTemplateCategory,
    PdfTemplateManifest,
    PdfTemplateRenderOptions,
    PdfTemplateVariableSchema,
)

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _build_builtin_manifests() -> list[PdfTemplateManifest]:
    """Construct the 10 industrial built-in template manifests (6 Finance + 4 Reports)."""
    return [
        # --- 1. Finance: Standard VAT Invoice ---
        PdfTemplateManifest(
            id="invoice_vat_standard",
            name="增值税标准发票 (Standard VAT Invoice)",
            category=PdfTemplateCategory.INVOICE,
            version="1.0.0",
            description="用于企业向客户开具的标准增值税发票与对账单，包含销售方/购买方纳税人信息、明细列表、税率小计及银行结算信息。",
            template_path=str(_TEMPLATES_DIR / "invoice_vat_standard.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "invoice", "billing", "tax", "vat"],
            variables=[
                PdfTemplateVariableSchema(
                    name="title",
                    type="string",
                    description="发票主标题",
                    example="增值税专用发票 / TAX INVOICE",
                ),
                PdfTemplateVariableSchema(
                    name="doc_no",
                    type="string",
                    description="发票/账单编号",
                    example="INV-20260820-001",
                ),
                PdfTemplateVariableSchema(
                    name="doc_date",
                    type="string",
                    description="开票日期 (YYYY-MM-DD)",
                    example="2026-08-20",
                ),
                PdfTemplateVariableSchema(
                    name="seller",
                    type="object",
                    description="销售方信息 (name, tax_id, address, bank_name, bank_account)",
                ),
                PdfTemplateVariableSchema(
                    name="buyer",
                    type="object",
                    description="购买方信息 (name, tax_id, contact, address, account)",
                ),
                PdfTemplateVariableSchema(
                    name="items",
                    type="array",
                    description="开票项目明细列表 (含 name, spec, quantity, unit_price, amount)",
                ),
                PdfTemplateVariableSchema(
                    name="subtotal",
                    type="string",
                    description="金额小计",
                    example="¥12,800.00",
                ),
                PdfTemplateVariableSchema(
                    name="tax_rate", type="string", description="适用税率", example="6%"
                ),
                PdfTemplateVariableSchema(
                    name="tax_amount",
                    type="string",
                    description="税额合计",
                    example="¥768.00",
                ),
                PdfTemplateVariableSchema(
                    name="total_amount",
                    type="string",
                    description="价税合计总金额",
                    example="¥13,568.00",
                ),
                PdfTemplateVariableSchema(
                    name="total_words",
                    type="string",
                    description="金额大写",
                    example="人民币 壹万叁仟伍佰陆拾捌元整",
                ),
                PdfTemplateVariableSchema(
                    name="watermark",
                    type="string",
                    description="水印文字",
                    required=False,
                    example="ORIGINAL",
                ),
            ],
        ),
        # --- 2. Finance: Commercial B2B Invoice ---
        PdfTemplateManifest(
            id="invoice_commercial_b2b",
            name="企业商业采购与服务发票 (Commercial B2B Invoice)",
            category=PdfTemplateCategory.INVOICE,
            version="1.0.0",
            description="面向企业级B2B大额采购与外包服务的高保真商业发票，支持双语标识与全功能模块组件。",
            template_path=str(_TEMPLATES_DIR / "invoice_commercial_b2b.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "invoice", "b2b", "commercial", "enterprise"],
            variables=[
                PdfTemplateVariableSchema(
                    name="title",
                    type="string",
                    description="单据主标题",
                    example="商业采购与服务结算发票 (COMMERCIAL INVOICE)",
                ),
                PdfTemplateVariableSchema(
                    name="doc_no",
                    type="string",
                    description="发票编号",
                    example="CIN-2026-9901",
                ),
                PdfTemplateVariableSchema(
                    name="doc_date",
                    type="string",
                    description="开票日期",
                    example="2026-08-20",
                ),
                PdfTemplateVariableSchema(
                    name="seller", type="object", description="供应商/销售方资料"
                ),
                PdfTemplateVariableSchema(
                    name="buyer", type="object", description="采购方资料"
                ),
                PdfTemplateVariableSchema(
                    name="items", type="array", description="采购明细清单"
                ),
                PdfTemplateVariableSchema(
                    name="total_amount",
                    type="string",
                    description="结算总额",
                    example="¥45,000.00",
                ),
                PdfTemplateVariableSchema(
                    name="total_words",
                    type="string",
                    description="大写金额",
                    example="肆万伍仟元整",
                ),
            ],
        ),
        # --- 3. Finance: SaaS Subscription Invoice ---
        PdfTemplateManifest(
            id="invoice_subscription_saas",
            name="SaaS云服务与周期性订阅对账发票 (SaaS Subscription Invoice)",
            category=PdfTemplateCategory.INVOICE,
            version="1.0.0",
            description="用于云平台、API 计费及 SaaS 产品月度/年度订阅发票与续费凭证，包含席位及算力消耗说明。",
            template_path=str(_TEMPLATES_DIR / "invoice_subscription_saas.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "invoice", "subscription", "saas", "billing", "cloud"],
            variables=[
                PdfTemplateVariableSchema(
                    name="title",
                    type="string",
                    description="订阅单据标题",
                    example="SaaS 平台年度订阅结算单 (SUBSCRIPTION INVOICE)",
                ),
                PdfTemplateVariableSchema(
                    name="doc_no",
                    type="string",
                    description="账单编号",
                    example="SUB-2026-1024",
                ),
                PdfTemplateVariableSchema(
                    name="doc_date",
                    type="string",
                    description="结算周期日期",
                    example="2026-08-20",
                ),
                PdfTemplateVariableSchema(
                    name="seller", type="object", description="SaaS 运营方资料"
                ),
                PdfTemplateVariableSchema(
                    name="buyer", type="object", description="订阅企业资料"
                ),
                PdfTemplateVariableSchema(
                    name="items", type="array", description="订阅服务及席位清单"
                ),
                PdfTemplateVariableSchema(
                    name="total_amount",
                    type="string",
                    description="应收总额",
                    example="¥19,900.00",
                ),
            ],
        ),
        # --- 4. Finance: Payment Receipt ---
        PdfTemplateManifest(
            id="receipt_payment_minimal",
            name="极简收款收据 (Payment Receipt Voucher)",
            category=PdfTemplateCategory.RECEIPT,
            version="1.0.0",
            description="用于向客户快速出具轻量级收款凭据与交费收据，包含交款人、事由、大写金额与印章说明。",
            template_path=str(_TEMPLATES_DIR / "receipt_payment_minimal.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A5",
                orientation="landscape",
                margin_top="12mm",
                margin_bottom="12mm",
                margin_left="12mm",
                margin_right="12mm",
            ),
            tags=["receipt", "payment", "voucher", "finance"],
            variables=[
                PdfTemplateVariableSchema(
                    name="receipt_no",
                    type="string",
                    description="收据单据编号",
                    example="REC-2026-0881",
                ),
                PdfTemplateVariableSchema(
                    name="receipt_date",
                    type="string",
                    description="收款日期",
                    example="2026-08-20",
                ),
                PdfTemplateVariableSchema(
                    name="company_name",
                    type="string",
                    description="收款单位名称",
                    example="MYRM AGENT LABS",
                ),
                PdfTemplateVariableSchema(
                    name="payer_name",
                    type="string",
                    description="交款单位/个人名称",
                    example="上海智能科技有限公司",
                ),
                PdfTemplateVariableSchema(
                    name="payment_reason",
                    type="string",
                    description="收款事由/项目",
                    example="定制智能体技术支持与云沙箱服务费",
                ),
                PdfTemplateVariableSchema(
                    name="payment_method",
                    type="string",
                    description="结算方式",
                    example="企业网银转账",
                ),
                PdfTemplateVariableSchema(
                    name="amount",
                    type="string",
                    description="实收金额 (数字)",
                    example="¥12,800.00",
                ),
                PdfTemplateVariableSchema(
                    name="amount_in_words",
                    type="string",
                    description="实收金额 (中文大写)",
                    example="壹万贰仟捌佰元整",
                ),
            ],
        ),
        # --- 5. Finance: Consulting Settlement ---
        PdfTemplateManifest(
            id="settlement_consulting_fee",
            name="专业咨询与技术服务结算单 (Consulting Fee Settlement)",
            category=PdfTemplateCategory.INVOICE,
            version="1.0.0",
            description="用于专家咨询、技术顾问工时与交付物验收结算，包含工时明细与专家签章。",
            template_path=str(_TEMPLATES_DIR / "settlement_consulting_fee.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "consulting", "settlement", "services", "timesheet"],
            variables=[
                PdfTemplateVariableSchema(
                    name="title",
                    type="string",
                    description="单据标题",
                    example="专业咨询与专家服务结算确认书",
                ),
                PdfTemplateVariableSchema(
                    name="doc_no",
                    type="string",
                    description="结算单号",
                    example="SET-2026-0520",
                ),
                PdfTemplateVariableSchema(
                    name="seller", type="object", description="咨询服务方"
                ),
                PdfTemplateVariableSchema(
                    name="buyer", type="object", description="委托客户方"
                ),
                PdfTemplateVariableSchema(
                    name="items", type="array", description="咨询工时与交付明细"
                ),
                PdfTemplateVariableSchema(
                    name="total_amount",
                    type="string",
                    description="结算总额",
                    example="¥36,000.00",
                ),
            ],
        ),
        # --- 6. Finance: Travel Expense Reimbursement ---
        PdfTemplateManifest(
            id="expense_travel_reimbursement",
            name="差旅与商务报销结算凭单 (Travel & Expense Reimbursement)",
            category=PdfTemplateCategory.RECEIPT,
            version="1.0.0",
            description="用于员工差旅出差、商务招待与日常办公费用的内部报销审批与结算凭单。",
            template_path=str(_TEMPLATES_DIR / "expense_travel_reimbursement.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "expense", "travel", "reimbursement", "internal"],
            variables=[
                PdfTemplateVariableSchema(
                    name="title",
                    type="string",
                    description="报销单标题",
                    example="员工差旅与商务报销审批结算单",
                ),
                PdfTemplateVariableSchema(
                    name="doc_no",
                    type="string",
                    description="报销单号",
                    example="EXP-2026-0819",
                ),
                PdfTemplateVariableSchema(
                    name="seller", type="object", description="申请人与归属部门"
                ),
                PdfTemplateVariableSchema(
                    name="buyer", type="object", description="报销核算公司主体"
                ),
                PdfTemplateVariableSchema(
                    name="items", type="array", description="费用票据与支出明细"
                ),
                PdfTemplateVariableSchema(
                    name="total_amount",
                    type="string",
                    description="报销总金额",
                    example="¥4,520.00",
                ),
            ],
        ),
        # --- 7. Report: Executive Summary ---
        PdfTemplateManifest(
            id="report_executive_summary",
            name="高管决策与商业分析全景报告 (Executive Summary Report)",
            category=PdfTemplateCategory.REPORT,
            version="1.0.0",
            description="用于输出高管汇报、商业智能洞察与战略分析，包含 SVG KPI 走势图、柱状图及结构化章节。",
            template_path=str(_TEMPLATES_DIR / "report_executive_summary.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["report", "business", "executive", "analytics", "charts"],
            variables=[
                PdfTemplateVariableSchema(
                    name="report_title",
                    type="string",
                    description="报告标题",
                    example="2026 年度企业数字化与 Agent 落地成效报告",
                ),
                PdfTemplateVariableSchema(
                    name="executive_summary",
                    type="string",
                    description="执行摘要正文",
                    example="本季度团队任务周转效率提升 320%...",
                ),
                PdfTemplateVariableSchema(
                    name="kpis",
                    type="array",
                    description="KPI 指标卡片列表 (含 label, value, change, is_positive, trend_data)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="bar_chart_items",
                    type="array",
                    description="柱状图数据项 (含 label, value)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="sections",
                    type="array",
                    description="报告主体章节列表 (含 title, content, table)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="conclusion",
                    type="string",
                    description="战略结论与建议",
                    required=False,
                ),
            ],
        ),
        # --- 8. Report: Security & Compliance Audit ---
        PdfTemplateManifest(
            id="report_security_audit",
            name="安全与合规审计评估报告 (Security & Compliance Audit)",
            category=PdfTemplateCategory.REPORT,
            version="1.0.0",
            description="用于网络安全合规审计、漏洞扫描评估与 SOC2/ISO27001 达标验收报告。",
            template_path=str(_TEMPLATES_DIR / "report_security_audit.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["report", "security", "audit", "compliance", "vulnerability"],
            variables=[
                PdfTemplateVariableSchema(
                    name="audit_title",
                    type="string",
                    description="审计报告标题",
                    example="2026 H1 核心生产环境安全与合规审计报告",
                ),
                PdfTemplateVariableSchema(
                    name="audit_summary",
                    type="string",
                    description="合规概括说明",
                    example="本次评估覆盖 4 个集群，整体合规度良好...",
                ),
                PdfTemplateVariableSchema(
                    name="compliance_score",
                    type="string",
                    description="综合合规得分",
                    example="92 / 100",
                ),
                PdfTemplateVariableSchema(
                    name="findings",
                    type="array",
                    description="缺陷与漏洞列表 (含 severity, category, description, remediation, deadline)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="recommendations",
                    type="array",
                    description="加固建议列表 (含 title, details)",
                    required=False,
                ),
            ],
        ),
        # --- 9. Report: Project Milestone & Delivery ---
        PdfTemplateManifest(
            id="report_project_milestone",
            name="项目阶段交付与里程碑验收报告 (Project Milestone & Delivery)",
            category=PdfTemplateCategory.REPORT,
            version="1.0.0",
            description="用于重大工程项目交付、里程碑进度核验与客户签署确认单。",
            template_path=str(_TEMPLATES_DIR / "report_project_milestone.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["report", "project", "milestone", "delivery", "acceptance"],
            variables=[
                PdfTemplateVariableSchema(
                    name="project_name",
                    type="string",
                    description="项目名称",
                    example="智能工作助手私有化部署项目",
                ),
                PdfTemplateVariableSchema(
                    name="progress_percent",
                    type="number",
                    description="总进度百分比",
                    example=85,
                ),
                PdfTemplateVariableSchema(
                    name="progress_summary", type="string", description="阶段进度说明"
                ),
                PdfTemplateVariableSchema(
                    name="milestones",
                    type="array",
                    description="里程碑完成列表 (含 name, planned_date, actual_date, status, deliverables)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="risks",
                    type="array",
                    description="风险应对项 (含 risk, mitigation)",
                    required=False,
                ),
            ],
        ),
        # --- 10. Report: Architecture Decision Record (ADR) ---
        PdfTemplateManifest(
            id="report_technical_analysis",
            name="技术选型与架构决策分析报告 (Technical Analysis & ADR)",
            category=PdfTemplateCategory.REPORT,
            version="1.0.0",
            description="用于重大技术方案评审、架构选型决策矩阵 (ADR) 与对比评估分析。",
            template_path=str(_TEMPLATES_DIR / "report_technical_analysis.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["report", "architecture", "adr", "technical", "decision"],
            variables=[
                PdfTemplateVariableSchema(
                    name="analysis_title",
                    type="string",
                    description="选型分析报告标题",
                    example="Agent 渲染引擎与 PDF 导出技术选型 ADR",
                ),
                PdfTemplateVariableSchema(
                    name="final_decision",
                    type="string",
                    description="最终决策结论",
                    example="采纳纯声明式 Jinja2 + Block 模块化架构",
                ),
                PdfTemplateVariableSchema(
                    name="decision_rationales",
                    type="string",
                    description="决策核心依据",
                ),
                PdfTemplateVariableSchema(
                    name="options",
                    type="array",
                    description="候选方案矩阵 (含 name, pros, cons, cost, score, score_level)",
                    required=False,
                ),
                PdfTemplateVariableSchema(
                    name="risks",
                    type="array",
                    description="架构风险与应对列表",
                    required=False,
                ),
            ],
        ),
    ]


class PdfTemplateRegistry:
    """Centralized Registry managing all available PDF templates in the framework."""

    def __init__(self, load_builtins: bool = True) -> None:
        self._templates: dict[str, PdfTemplateManifest] = {}
        if load_builtins:
            for manifest in _build_builtin_manifests():
                self.register(manifest)

    def register(
        self, manifest: PdfTemplateManifest, *, overwrite: bool = True
    ) -> None:
        """Register a new PDF template manifest."""
        if not overwrite and manifest.id in self._templates:
            raise ValueError(f"Template with id '{manifest.id}' is already registered.")
        self._templates[manifest.id] = manifest
        logger.debug(
            "PdfTemplateRegistry: registered template '%s' (%s)",
            manifest.id,
            manifest.name,
        )

    def unregister(self, template_id: str) -> bool:
        """Unregister a template by id."""
        return self._templates.pop(template_id, None) is not None

    def get_template(self, template_id: str) -> PdfTemplateManifest | None:
        """Retrieve a registered template by ID."""
        return self._templates.get(template_id)

    def list_templates(
        self,
        category: PdfTemplateCategory | str | None = None,
        tag: str | None = None,
    ) -> list[PdfTemplateManifest]:
        """List registered templates with optional category/tag filtering."""
        results: list[PdfTemplateManifest] = []
        target_cat = (
            category.value if isinstance(category, PdfTemplateCategory) else category
        )

        for tmpl in self._templates.values():
            if target_cat and tmpl.category.value != target_cat:
                continue
            if tag and tag.lower() not in [t.lower() for t in tmpl.tags]:
                continue
            results.append(tmpl)
        return results

    def search_templates(self, query: str) -> list[PdfTemplateManifest]:
        """Search templates by keyword matching against id, name, description, and tags."""
        q = query.strip().lower()
        if not q:
            return list(self._templates.values())

        matched: list[tuple[int, PdfTemplateManifest]] = []
        for tmpl in self._templates.values():
            score = 0
            if q in tmpl.id.lower():
                score += 10
            if q in tmpl.name.lower():
                score += 8
            if any(q in tag.lower() for tag in tmpl.tags):
                score += 5
            if q in tmpl.description.lower():
                score += 3
            if score > 0:
                matched.append((score, tmpl))

        matched.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in matched]


# Global singleton instance
_GLOBAL_REGISTRY: PdfTemplateRegistry | None = None


def get_pdf_template_registry() -> PdfTemplateRegistry:
    """Get or initialize the global PdfTemplateRegistry singleton."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = PdfTemplateRegistry(load_builtins=True)
    return _GLOBAL_REGISTRY
