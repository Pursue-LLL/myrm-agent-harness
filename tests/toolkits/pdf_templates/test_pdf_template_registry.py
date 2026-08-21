"""Tests for PdfTemplateRegistry and Manifest contracts."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.pdf_templates import (
    PdfTemplateCategory,
    PdfTemplateManifest,
    PdfTemplateRegistry,
    PdfTemplateVariableSchema,
    get_pdf_template_registry,
)


def test_builtin_templates_loaded() -> None:
    """Verify 10 standard built-in templates are registered by default."""
    registry = get_pdf_template_registry()
    templates = registry.list_templates()
    template_ids = {t.id for t in templates}

    assert len(templates) >= 10
    # 6 Finance
    assert "invoice_vat_standard" in template_ids
    assert "invoice_commercial_b2b" in template_ids
    assert "invoice_subscription_saas" in template_ids
    assert "receipt_payment_minimal" in template_ids
    assert "settlement_consulting_fee" in template_ids
    assert "expense_travel_reimbursement" in template_ids
    # 4 Reports
    assert "report_executive_summary" in template_ids
    assert "report_security_audit" in template_ids
    assert "report_project_milestone" in template_ids
    assert "report_technical_analysis" in template_ids


def test_all_ten_templates_render_without_error() -> None:
    """Verify all 10 built-in templates render cleanly with default or empty data."""
    from myrm_agent_harness.toolkits.pdf_templates import (
        PdfTemplateRegistry,
        get_pdf_render_engine,
    )

    # Fresh isolated registry with only builtins
    local_registry = PdfTemplateRegistry(load_builtins=True)
    engine = get_pdf_render_engine()

    sample_items = [
        {
            "name": "Cloud Computing Resource A",
            "spec": "Standard-4C8G",
            "unit_price": "¥1,000.00",
            "quantity": 2,
            "amount": "¥2,000.00",
        }
    ]

    for tmpl in local_registry.list_templates():
        html, manifest = engine.render_html_string(
            tmpl.id,
            {
                "title": f"Test Document for {tmpl.id}",
                "doc_no": "TEST-NO-001",
                "items": sample_items,
                "total_amount": "¥2,000.00",
                "watermark_text": "SAMPLE DRAFT",
            },
        )
        assert len(html) > 50
        assert (
            tmpl.name in html
            or tmpl.id in html
            or "TEST-NO-001" in html
            or "Test Document" in html
            or "SAMPLE DRAFT" in html
            or "报告" in html
            or "单" in html
            or "发票" in html
            or "收据" in html
        )


def test_template_filtering_and_search() -> None:
    """Verify category filtering, search keyword scoring, and empty query."""
    registry = PdfTemplateRegistry(load_builtins=True)

    # Empty search query returns all
    all_hits = registry.search_templates("")
    assert len(all_hits) >= 10

    invoices = registry.list_templates(category=PdfTemplateCategory.INVOICE)
    assert len(invoices) >= 4
    assert all(t.category == PdfTemplateCategory.INVOICE for t in invoices)

    reports = registry.list_templates(category="report")
    assert len(reports) >= 4
    assert all(t.category == PdfTemplateCategory.REPORT for t in reports)

    receipts = registry.list_templates(category=PdfTemplateCategory.RECEIPT)
    assert len(receipts) >= 2

    # Keyword search scoring across id, name, tags, description
    search_hits = registry.search_templates("发票")
    assert len(search_hits) >= 3
    assert search_hits[0].id.startswith("invoice_")

    tag_search = registry.search_templates("finance")
    assert len(tag_search) >= 6

    desc_search = registry.search_templates("标准增值税")
    assert len(desc_search) >= 1

    id_search = registry.search_templates("report_executive_summary")
    assert len(id_search) >= 1

    tag_hits = registry.list_templates(tag="billing")
    assert len(tag_hits) >= 2

    # Overwrite check
    custom_m = PdfTemplateManifest(
        id="overwrite_test",
        name="Overwrite Test",
        category=PdfTemplateCategory.CUSTOM,
        description="Testing duplicate registration error",
        template_html="<div>Test</div>",
    )
    registry.register(custom_m)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(custom_m, overwrite=False)
    registry.unregister("overwrite_test")


def test_custom_template_registration() -> None:
    """Verify custom template registration and unregistration."""
    registry = PdfTemplateRegistry(load_builtins=False)

    manifest = PdfTemplateManifest(
        id="custom_cert",
        name="荣誉证书 (Certificate)",
        category=PdfTemplateCategory.CERTIFICATE,
        description="用于颁发用户认证证书",
        template_html="<h1>{{ title }}</h1><p>{{ recipient }}</p>",
        variables=[
            PdfTemplateVariableSchema(
                name="title",
                type="string",
                description="证书标题",
                example="优秀开发者",
                default="证书",
            ),
            PdfTemplateVariableSchema(
                name="recipient",
                type="string",
                description="获得者姓名",
                example="张三",
            ),
        ],
        tags=["certificate", "award"],
    )

    registry.register(manifest)
    assert registry.get_template("custom_cert") is not None
    assert len(registry.list_templates()) == 1

    schema = manifest.get_json_schema()
    assert schema["type"] == "object"
    assert "title" in schema["properties"]
    assert "recipient" in schema["properties"]
    assert "title" in schema["required"]

    unreg_ok = registry.unregister("custom_cert")
    assert unreg_ok is True
    assert registry.get_template("custom_cert") is None
