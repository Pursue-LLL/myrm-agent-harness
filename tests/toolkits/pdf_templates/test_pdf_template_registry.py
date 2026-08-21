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
    """Verify standard built-in templates are registered by default."""
    registry = get_pdf_template_registry()
    templates = registry.list_templates()
    template_ids = {t.id for t in templates}

    assert "invoice_standard" in template_ids
    assert "business_report" in template_ids
    assert "receipt_minimal" in template_ids


def test_template_filtering_and_search() -> None:
    """Verify category filtering, search keyword scoring, and empty query."""
    registry = PdfTemplateRegistry(load_builtins=True)

    # Empty search query returns all
    all_hits = registry.search_templates("")
    assert len(all_hits) >= 3

    invoices = registry.list_templates(category=PdfTemplateCategory.INVOICE)
    assert len(invoices) >= 1
    assert all(t.category == PdfTemplateCategory.INVOICE for t in invoices)

    reports = registry.list_templates(category="report")
    assert len(reports) >= 1
    assert all(t.category == PdfTemplateCategory.REPORT for t in reports)

    # Keyword search scoring across id, name, tags, description
    search_hits = registry.search_templates("发票")
    assert len(search_hits) >= 1
    assert search_hits[0].id == "invoice_standard"

    tag_search = registry.search_templates("financial")
    assert len(tag_search) >= 1

    desc_search = registry.search_templates("标准增值税")
    assert len(desc_search) >= 1

    id_search = registry.search_templates("business_report")
    assert len(id_search) >= 1

    tag_hits = registry.list_templates(tag="billing")
    assert len(tag_hits) >= 1

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
            PdfTemplateVariableSchema(name="title", type="string", description="证书标题", example="优秀开发者", default="证书"),
            PdfTemplateVariableSchema(name="recipient", type="string", description="获得者姓名", example="张三"),
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
