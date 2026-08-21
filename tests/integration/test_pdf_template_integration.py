"""Integration test for PdfTemplateRegistry and PdfRenderEngine toolchain.

Verifies end-to-end template listing, schema extraction, and PDF/HTML generation
across standard corporate templates (Invoice, Business Report, Receipt) without mocking
the underlying Jinja2 compilation and security sanitization pipelines.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.pdf_templates import (
    PdfTemplateCategory,
    PdfTemplateManifest,
    PdfTemplateVariableSchema,
    create_pdf_template_tools,
    get_pdf_template_registry,
)


@pytest.mark.asyncio
async def test_end_to_end_invoice_generation_flow(tmp_path: Path) -> None:
    """Verify complete flow: discover -> inspect schema -> render invoice document."""
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    # 1. Discover template
    discover_raw = tools_map["list_pdf_templates"].invoke({"query": "增值税"})
    discover_data = json.loads(discover_raw)
    assert discover_data["total"] >= 1
    tmpl_meta = next(
        t for t in discover_data["templates"] if t["template_id"] == "invoice_standard"
    )
    assert tmpl_meta["category"] == "invoice"

    # 2. Inspect schema
    schema_raw = tools_map["get_pdf_template_schema"].invoke(
        {"template_id": "invoice_standard"}
    )
    schema_data = json.loads(schema_raw)
    assert "properties" in schema_data["json_schema"]
    assert "invoice_no" in schema_data["json_schema"]["properties"]
    assert "seller_name" in schema_data["json_schema"]["properties"]

    # 3. Render real document
    out_pdf = tmp_path / "artifacts" / "invoice_2026.pdf"
    invoice_payload = {
        "invoice_no": "INV-2026-AUG-8899",
        "invoice_date": "2026-08-20",
        "seller_name": "Myrm Technology Co., Ltd.",
        "seller_tax_id": "91310000MA1FL88888",
        "seller_address": "Shanghai Pudong Tech Park Bldg 3",
        "seller_bank_name": "China Merchants Bank",
        "seller_bank_account": "6225 8888 1234 5678",
        "buyer_name": "Global Enterprise Client",
        "buyer_tax_id": "91110000MA1FL99999",
        "buyer_contact": "contact@client.example.com",
        "items": [
            {
                "name": "Myrm Agent SaaS Subscription",
                "description": "Annual enterprise tier license",
                "unit_price": "¥120,000.00",
                "quantity": "1",
                "amount": "¥120,000.00",
            },
            {
                "name": "Cloud Sandbox Orchestrator Dedicated Node",
                "description": "12 months reserved execution cluster",
                "unit_price": "¥30,000.00",
                "quantity": "1",
                "amount": "¥30,000.00",
            },
        ],
        "subtotal": "¥150,000.00",
        "tax_rate": "6%",
        "tax_amount": "¥9,000.00",
        "total_amount": "¥159,000.00",
        "notes": "Thank you for partnering with Myrm Agent Labs.",
    }

    render_raw = await tools_map["render_pdf_template"].ainvoke(
        {
            "template_id": "invoice_standard",
            "data_json": json.dumps(invoice_payload),
            "output_path": str(out_pdf),
        }
    )
    render_data = json.loads(render_raw)
    assert render_data["success"] is True
    assert Path(render_data["output_path"]).exists()

    # Verify intermediate HTML content integrity
    html_file = Path(render_data["output_path"]).with_suffix(".html")
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "INV-2026-AUG-8899" in html_content
    assert "Myrm Technology Co., Ltd." in html_content
    assert "Annual enterprise tier license" in html_content
    assert "¥159,000.00" in html_content


@pytest.mark.asyncio
async def test_end_to_end_business_report_generation_flow(tmp_path: Path) -> None:
    """Verify complete business report rendering with KPI cards and sections."""
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    out_pdf = tmp_path / "artifacts" / "q3_report.pdf"
    report_payload = {
        "report_title": "2026 Q3 智能体技术架构与交付成效全景报告",
        "category_badge": "ARCHITECTURAL REPORT",
        "author": "Myrm 架构评审委员会",
        "report_period": "2026 Q3",
        "report_date": "2026-08-20",
        "executive_summary": "本季度全面达成 PdfTemplateRegistryHarness 与多项工具链落地，系统提示词缓存命中率达 98.4%。",
        "kpis": [
            {
                "label": "Prompt Cache 命中率",
                "value": "98.4%",
                "change": "+12.3%",
                "is_positive": True,
            },
            {
                "label": "PDF 渲染周转耗时",
                "value": "320ms",
                "change": "-65.0%",
                "is_positive": True,
            },
            {
                "label": "架构越界依赖数",
                "value": "0",
                "change": "0",
                "is_positive": True,
            },
        ],
        "sections": [
            {
                "title": "一、架构演进与能力矩阵",
                "content": "通过引入统一的 Manifest SSOT 规范，实现声明式模板管理与零 Node 运行时依赖。",
                "table": {
                    "headers": ["模块名称", "分层归属", "单测覆盖率", "状态"],
                    "rows": [
                        [
                            "PdfTemplateRegistry",
                            "Harness Toolkits",
                            "100%",
                            "Production Ready",
                        ],
                        [
                            "PdfRenderEngine",
                            "Harness Toolkits",
                            "91%",
                            "Production Ready",
                        ],
                        [
                            "LangChain Tools",
                            "Harness Agent Surface",
                            "95%",
                            "Production Ready",
                        ],
                    ],
                },
            }
        ],
        "conclusion": "架构整体稳健，具备极高的扩展性与生产级可维护性。",
    }

    render_raw = await tools_map["render_pdf_template"].ainvoke(
        {
            "template_id": "business_report",
            "data_json": json.dumps(report_payload),
            "output_path": str(out_pdf),
        }
    )
    render_data = json.loads(render_raw)
    assert render_data["success"] is True

    html_file = Path(render_data["output_path"]).with_suffix(".html")
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")
    assert "智能体技术架构与交付成效全景报告" in html_content
    assert "ARCHITECTURAL REPORT" in html_content
    assert "Prompt Cache 命中率" in html_content
    assert "98.4%" in html_content
    assert "Production Ready" in html_content


@pytest.mark.asyncio
async def test_custom_template_dynamic_registration_flow(tmp_path: Path) -> None:
    """Verify dynamic external template registration and instant tool invocation."""
    registry = get_pdf_template_registry()
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    custom_id = "integration_badge_cert"
    custom_manifest = PdfTemplateManifest(
        id=custom_id,
        name="认证证书徽章 (Integration Certificate)",
        category=PdfTemplateCategory.CERTIFICATE,
        description="用于发放集成测试通过证书",
        template_html="<div class='cert'><h1>{{ cert_title }}</h1><p>颁发给：{{ student_name }}</p><span>得分：{{ score }}</span></div>",
        variables=[
            PdfTemplateVariableSchema(
                name="cert_title",
                type="string",
                description="证书标题",
                example="满分架构师认证",
            ),
            PdfTemplateVariableSchema(
                name="student_name",
                type="string",
                description="学员姓名",
                example="李四",
            ),
            PdfTemplateVariableSchema(
                name="score", type="string", description="考试得分", example="100"
            ),
        ],
        tags=["cert", "badge", "integration"],
    )

    registry.register(custom_manifest)
    try:
        # Introspect via tool
        schema_raw = tools_map["get_pdf_template_schema"].invoke(
            {"template_id": custom_id}
        )
        schema_data = json.loads(schema_raw)
        assert schema_data["template_id"] == custom_id
        assert "cert_title" in schema_data["json_schema"]["properties"]

        # Render via tool
        out_pdf = tmp_path / "custom_cert.pdf"
        render_raw = await tools_map["render_pdf_template"].ainvoke(
            {
                "template_id": custom_id,
                "data_json": json.dumps(
                    {
                        "cert_title": "顶级系统架构师认证证书",
                        "student_name": "张三",
                        "score": "100分",
                    }
                ),
                "output_path": str(out_pdf),
            }
        )
        render_data = json.loads(render_raw)
        assert render_data["success"] is True

        html_file = Path(render_data["output_path"]).with_suffix(".html")
        assert html_file.exists()
        html_content = html_file.read_text(encoding="utf-8")
        assert "顶级系统架构师认证证书" in html_content
        assert "张三" in html_content
        assert "100分" in html_content
    finally:
        registry.unregister(custom_id)


@pytest.mark.asyncio
async def test_concurrent_pdf_rendering_stress(tmp_path: Path) -> None:
    """Verify concurrent parallel execution of multiple PDF rendering jobs."""
    import asyncio

    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    async def render_job(index: int) -> dict[str, object]:
        payload = {
            "receipt_no": f"REC-CONCUR-{index:04d}",
            "receipt_date": "2026-08-20",
            "company_name": "Myrm Concurrent Testing Labs",
            "payer_name": f"Enterprise Client #{index}",
            "payment_reason": f"Parallel batch test stress item #{index}",
            "payment_method": "Auto Debit",
            "amount": f"¥{index * 1000 + 500:.2f}",
            "amount_in_words": "人民币整",
        }
        out_pdf = tmp_path / f"receipt_concurrent_{index}.pdf"
        res = await tools_map["render_pdf_template"].ainvoke(
            {
                "template_id": "receipt_minimal",
                "data_json": json.dumps(payload),
                "output_path": str(out_pdf),
            }
        )
        return json.loads(res)

    # Launch 10 concurrent render jobs
    tasks = [render_job(i) for i in range(10)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 10
    for i, res in enumerate(results):
        assert res["success"] is True
        assert Path(res["output_path"]).exists()
        html_path = Path(res["output_path"]).with_suffix(".html")
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert f"REC-CONCUR-{i:04d}" in content


@pytest.mark.asyncio
async def test_adversarial_security_injection_handling(tmp_path: Path) -> None:
    """Verify sanitization under XSS, SSRF, and injection attacks in dynamic variables."""
    tools = create_pdf_template_tools()
    tools_map = {t.name: t for t in tools}

    malicious_payload = {
        "invoice_no": 'INV-SEC-001"><script>alert("hacked")</script>',
        "seller_name": '<a href="javascript:document.cookie">Evil Seller</a>',
        "buyer_name": '<img src="file:///etc/passwd" onerror="alert(1)">',
        "items": [
            {
                "name": '<iframe src="gopher://127.0.0.1:6379">Dangerous Item</iframe>',
                "description": "<style>body{display:none;}</style>",
                "unit_price": "¥100.00",
                "quantity": "1",
                "amount": "¥100.00",
            }
        ],
        "total_amount": "¥100.00",
    }

    out_pdf = tmp_path / "sec_test.pdf"
    render_raw = await tools_map["render_pdf_template"].ainvoke(
        {
            "template_id": "invoice_standard",
            "data_json": json.dumps(malicious_payload),
            "output_path": str(out_pdf),
        }
    )
    render_data = json.loads(render_raw)
    assert render_data["success"] is True

    html_file = Path(render_data["output_path"]).with_suffix(".html")
    assert html_file.exists()
    sanitized_html = html_file.read_text(encoding="utf-8")

    # Critical security checks: dangerous protocols and scripts must be stripped / replaced
    assert "<script>" not in sanitized_html
    assert "file:///etc/passwd" not in sanitized_html
    assert "javascript:" not in sanitized_html
    assert "gopher://" not in sanitized_html
