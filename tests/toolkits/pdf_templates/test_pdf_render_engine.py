"""Tests for PdfRenderEngine and LangChain tool factory."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.pdf_templates import (
    PdfRenderEngine,
    PdfTemplateCategory,
    PdfTemplateManifest,
    create_pdf_template_tools,
    get_pdf_render_engine,
    get_pdf_template_registry,
)


def test_html_interpolation_and_sanitization() -> None:
    """Verify Jinja2 template interpolation and SSRF protocol sanitization."""
    engine = get_pdf_render_engine()

    data = {
        "invoice_no": "INV-TEST-999",
        "seller_name": "Test Seller Co.",
        "buyer_name": "Test Buyer Co.",
        "items": [
            {"name": "Consulting", "description": "AI Audit", "unit_price": "¥5,000", "quantity": "1", "amount": "¥5,000"}
        ],
        "total_amount": "¥5,300.00",
    }

    html, manifest = engine.render_html_string("invoice_standard", data)
    assert "INV-TEST-999" in html
    assert "Test Seller Co." in html
    assert "Test Buyer Co." in html
    assert "Consulting" in html

    # Test dangerous protocol sanitization
    dirty_html = '<img src="file:///etc/passwd"><a href="javascript:alert(1)">link</a>'
    clean_html = engine.sanitize_html(dirty_html)
    assert "file://" not in clean_html
    assert "javascript:" not in clean_html
    assert "about:blank#blocked" in clean_html


@pytest.mark.asyncio
async def test_render_to_pdf_mock_browser(tmp_path: Path) -> None:
    """Verify rendering pipeline when browser page is provided."""
    engine = PdfRenderEngine()
    mock_page = MagicMock()
    mock_page.set_content = AsyncMock()
    mock_page.pdf = AsyncMock()

    out_file = tmp_path / "test_invoice.pdf"
    data = {
        "invoice_no": "INV-2026-001",
        "total_amount": "¥100.00",
    }

    res = await engine.render_to_pdf(
        template_id="invoice_standard",
        data=data,
        output_path=str(out_file),
        browser_page=mock_page,
    )

    assert res.success is True
    assert res.output_path == str(out_file.resolve())
    assert "INV-2026-001" in res.rendered_html
    mock_page.set_content.assert_called_once()
    mock_page.pdf.assert_called_once()

    # Test error during render_to_pdf
    mock_page_failing = MagicMock()
    mock_page_failing.set_content = AsyncMock(side_effect=RuntimeError("Browser crashed"))
    fail_res = await engine.render_to_pdf(
        template_id="invoice_standard",
        data=data,
        output_path=str(out_file),
        browser_page=mock_page_failing,
    )
    assert fail_res.success is False
    assert "Browser crashed" in (fail_res.error_message or "")


@pytest.mark.asyncio
async def test_langchain_pdf_tools(tmp_path: Path) -> None:
    """Verify LangChain agent tools execution."""
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    assert "list_pdf_templates" in tools_map
    assert "get_pdf_template_schema" in tools_map
    assert "render_pdf_template" in tools_map

    # 1. list_pdf_templates
    list_res = tools_map["list_pdf_templates"].invoke({"query": "发票", "category": "invoice"})
    list_data = json.loads(list_res)
    assert list_data["total"] >= 1
    assert list_data["templates"][0]["template_id"] == "invoice_standard"

    # Empty filter match
    empty_res = tools_map["list_pdf_templates"].invoke({"query": "nonexistent_keyword_xyz"})
    assert "No PDF templates found" in empty_res

    # 2. get_pdf_template_schema
    schema_res = tools_map["get_pdf_template_schema"].invoke({"template_id": "invoice_standard"})
    schema_data = json.loads(schema_res)
    assert schema_data["template_id"] == "invoice_standard"
    assert "json_schema" in schema_data
    assert "invoice_no" in schema_data["json_schema"]["properties"]

    # Not found template schema
    not_found_schema = json.loads(tools_map["get_pdf_template_schema"].invoke({"template_id": "not_existing_id"}))
    assert "error" in not_found_schema

    # 3. render_pdf_template (with fallback execution & invalid json handling)
    invalid_json_res = await tools_map["render_pdf_template"].ainvoke({
        "template_id": "receipt_minimal",
        "data_json": "invalid-json-string{",
        "output_path": str(tmp_path / "dummy.pdf"),
    })
    assert "Invalid JSON" in invalid_json_res

    not_dict_json_res = await tools_map["render_pdf_template"].ainvoke({
        "template_id": "receipt_minimal",
        "data_json": "[1, 2, 3]",
        "output_path": str(tmp_path / "dummy.pdf"),
    })
    assert "must be a valid JSON object" in not_dict_json_res

    out_file = tmp_path / "output_receipt.pdf"
    payload = {
        "receipt_no": "REC-9999",
        "amount": "¥8,888.00",
        "payer_name": "Test Client",
    }
    render_res = await tools_map["render_pdf_template"].ainvoke({
        "template_id": "receipt_minimal",
        "data_json": json.dumps(payload),
        "output_path": str(out_file),
    })
    render_data = json.loads(render_res)
    assert render_data["success"] is True
    assert render_data["template_id"] == "receipt_minimal"


def test_render_engine_error_and_edge_cases(tmp_path: Path) -> None:
    """Verify error branches in engine: missing template, missing file, etc."""
    engine = PdfRenderEngine()

    # 1. Non-existent template id
    with pytest.raises(ValueError, match="is not registered"):
        engine.render_html_string("non_existent_tmpl", {})

    # 2. Template file not found
    custom_missing_file = PdfTemplateManifest(
        id="missing_file_tmpl",
        name="Missing File",
        category=PdfTemplateCategory.CUSTOM,
        description="Missing file test",
        template_path="/path/to/definitely/non/existent/template.html",
    )
    engine._registry.register(custom_missing_file)
    with pytest.raises(FileNotFoundError, match="Template file not found"):
        engine.render_html_string("missing_file_tmpl", {})

    # 3. Template with neither path nor html
    custom_empty = PdfTemplateManifest(
        id="empty_tmpl",
        name="Empty Template",
        category=PdfTemplateCategory.CUSTOM,
        description="Empty test",
    )
    engine._registry.register(custom_empty)
    with pytest.raises(ValueError, match="neither template_path nor template_html"):
        engine.render_html_string("empty_tmpl", {})

    # 4. Inline template html rendering
    custom_inline = PdfTemplateManifest(
        id="inline_tmpl",
        name="Inline HTML",
        category=PdfTemplateCategory.CUSTOM,
        description="Inline test",
        template_html="<h1>Hello {{ name }}</h1>",
    )
    engine._registry.register(custom_inline)
    html, _ = engine.render_html_string("inline_tmpl", {"name": "World"})
    assert "<h1>Hello World</h1>" in html
