"""Tests for PdfRenderEngine and LangChain tool factory."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.pdf_templates import (
    PdfRenderEngine,
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


@pytest.mark.asyncio
async def test_langchain_pdf_tools(tmp_path: Path) -> None:
    """Verify LangChain agent tools execution."""
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    assert "list_pdf_templates" in tools_map
    assert "get_pdf_template_schema" in tools_map
    assert "render_pdf_template" in tools_map

    # 1. list_pdf_templates
    list_res = tools_map["list_pdf_templates"].invoke({"query": "发票"})
    list_data = json.loads(list_res)
    assert list_data["total"] >= 1
    assert list_data["templates"][0]["template_id"] == "invoice_standard"

    # 2. get_pdf_template_schema
    schema_res = tools_map["get_pdf_template_schema"].invoke({"template_id": "invoice_standard"})
    schema_data = json.loads(schema_res)
    assert schema_data["template_id"] == "invoice_standard"
    assert "json_schema" in schema_data
    assert "invoice_no" in schema_data["json_schema"]["properties"]

    # 3. render_pdf_template (with fallback execution)
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
