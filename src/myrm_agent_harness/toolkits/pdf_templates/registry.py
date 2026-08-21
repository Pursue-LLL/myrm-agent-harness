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
and built-in default templates (Invoices, Business Reports, Receipts).
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
    """Construct the standard built-in template manifests."""
    return [
        PdfTemplateManifest(
            id="invoice_standard",
            name="增值税标准发票 (Standard Invoice)",
            category=PdfTemplateCategory.INVOICE,
            version="1.0.0",
            description="用于企业向客户开具的标准增值税发票与对账单，包含销售方/购买方纳税人信息、明细列表、税率小计及银行结算信息。",
            template_path=str(_TEMPLATES_DIR / "invoice_standard.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="15mm",
                margin_bottom="15mm",
                margin_left="15mm",
                margin_right="15mm",
            ),
            tags=["finance", "invoice", "billing", "tax"],
            variables=[
                PdfTemplateVariableSchema(
                    name="invoice_no",
                    type="string",
                    description="发票/账单编号",
                    example="INV-20260820-001",
                ),
                PdfTemplateVariableSchema(
                    name="invoice_date",
                    type="string",
                    description="开票日期 (YYYY-MM-DD)",
                    example="2026-08-20",
                ),
                PdfTemplateVariableSchema(
                    name="seller_name",
                    type="string",
                    description="销售方公司名称",
                    example="MYRM AGENT LABS",
                ),
                PdfTemplateVariableSchema(
                    name="seller_tax_id",
                    type="string",
                    description="销售方税号/统一社会信用代码",
                    example="91310000XXXXXXXXXX",
                ),
                PdfTemplateVariableSchema(
                    name="seller_address",
                    type="string",
                    description="销售方地址/电话",
                    example="上海市徐汇区漕河泾科创中心 88 号",
                ),
                PdfTemplateVariableSchema(
                    name="seller_bank_name",
                    type="string",
                    description="销售方开户银行",
                    example="招商银行股份有限公司上海分行",
                ),
                PdfTemplateVariableSchema(
                    name="seller_bank_account",
                    type="string",
                    description="销售方银行账号",
                    example="6225 8888 9999 0001",
                ),
                PdfTemplateVariableSchema(
                    name="buyer_name",
                    type="string",
                    description="购买方公司/个人名称",
                    example="上海智能科技有限公司",
                ),
                PdfTemplateVariableSchema(
                    name="buyer_tax_id",
                    type="string",
                    description="购买方税号/统一社会信用代码",
                    example="91110000XXXXXXXXXX",
                ),
                PdfTemplateVariableSchema(
                    name="buyer_contact",
                    type="string",
                    description="购买方联系方式/地址",
                    example="北京市海淀区中关村南大街 1 号",
                ),
                PdfTemplateVariableSchema(
                    name="items",
                    type="array",
                    description="开票项目明细列表 (含 name, description, unit_price, quantity, amount)",
                ),
                PdfTemplateVariableSchema(
                    name="subtotal",
                    type="string",
                    description="金额小计",
                    example="¥12,800.00",
                ),
                PdfTemplateVariableSchema(
                    name="tax_rate",
                    type="string",
                    description="税率 (如 6%, 13%)",
                    example="6%",
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
                    name="remarks",
                    type="string",
                    description="备注说明",
                    required=False,
                    example="本账单已结清",
                ),
            ],
        ),
        PdfTemplateManifest(
            id="business_report",
            name="商业研究与季度分析报告 (Business Report)",
            category=PdfTemplateCategory.REPORT,
            version="1.0.0",
            description="用于输出高保真商业研究报告、项目周报/月报、行业竞品分析与总结，包含封面、执行摘要、KPI 卡片、表格及结论建议。",
            template_path=str(_TEMPLATES_DIR / "business_report.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A4",
                orientation="portrait",
                margin_top="18mm",
                margin_bottom="18mm",
                margin_left="18mm",
                margin_right="18mm",
            ),
            tags=["report", "business", "analysis", "weekly", "research"],
            variables=[
                PdfTemplateVariableSchema(
                    name="report_title",
                    type="string",
                    description="报告标题",
                    example="2026 年度企业数字化与 Agent 落地成效报告",
                ),
                PdfTemplateVariableSchema(
                    name="category_badge",
                    type="string",
                    description="报告类别徽标",
                    required=False,
                    example="RESEARCH & ANALYTICS",
                ),
                PdfTemplateVariableSchema(
                    name="author",
                    type="string",
                    description="作者/部门",
                    example="Myrm AI 战略研究部",
                ),
                PdfTemplateVariableSchema(
                    name="report_period",
                    type="string",
                    description="报告周期/时间段",
                    example="2026 Q3",
                ),
                PdfTemplateVariableSchema(
                    name="report_date",
                    type="string",
                    description="报告生成日期 (YYYY-MM-DD)",
                    example="2026-08-20",
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
                    description="KPI 指标卡片列表 (含 label, value, change, is_positive)",
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
                    description="结论与后续行动建议",
                    required=False,
                ),
            ],
        ),
        PdfTemplateManifest(
            id="receipt_minimal",
            name="极简收款收据 (Payment Receipt)",
            category=PdfTemplateCategory.RECEIPT,
            version="1.0.0",
            description="用于向客户快速出具轻量级收款凭据与交费收据，包含交款人、事由、大写金额与印章说明。",
            template_path=str(_TEMPLATES_DIR / "receipt_minimal.html"),
            default_options=PdfTemplateRenderOptions(
                page_size="A5",
                orientation="landscape",
                margin_top="12mm",
                margin_bottom="12mm",
                margin_left="12mm",
                margin_right="12mm",
            ),
            tags=["receipt", "payment", "voucher"],
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
                PdfTemplateVariableSchema(
                    name="cashier",
                    type="string",
                    description="收款出纳人",
                    required=False,
                    example="财务部系统出纳",
                ),
                PdfTemplateVariableSchema(
                    name="handler",
                    type="string",
                    description="经办人",
                    required=False,
                    example="项目管理组",
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
