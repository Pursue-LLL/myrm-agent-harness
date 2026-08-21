"""LangChain tools adapter for PDF Template Toolkit.

[INPUT]
langchain_core.tools::tool (POS: LangChain tool decorator)
.registry::PdfTemplateRegistry, get_pdf_template_registry (POS: template registry)
.engine::PdfRenderEngine, get_pdf_render_engine (POS: template renderer)
.manifest::PdfTemplateCategory (POS: category enum)

[OUTPUT]
- create_pdf_template_tools(): factory creating LangChain tools for Agent PDF generation
- list_pdf_templates_tool: query template catalog
- get_pdf_template_schema_tool: inspect required variables schema
- render_pdf_template_tool: compile structured JSON payload into PDF

[POS]
Provides agent-facing LangChain StructuredTools for PDF templates.
Follows toolkits/_ARCH.md conventions: zero imports from agent runtime,
zero session binding at construction, pure factory over the generic engine.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from langchain_core.tools import tool

from .engine import PdfRenderEngine, get_pdf_render_engine
from .manifest import PdfTemplateCategory
from .registry import PdfTemplateRegistry, get_pdf_template_registry


def create_pdf_template_tools(
    registry: PdfTemplateRegistry | None = None,
    engine: PdfRenderEngine | None = None,
) -> list[Any]:
    """Factory creating the 3 agent-callable LangChain tools for PDF template generation."""
    reg = registry or get_pdf_template_registry()
    eng = engine or get_pdf_render_engine()

    @tool
    def list_pdf_templates(
        category: Annotated[
            str | None,
            "Optional category filter: 'invoice', 'report', 'receipt', 'document'",
        ] = None,
        query: Annotated[
            str | None,
            "Optional search keyword matching template name, tags, or description",
        ] = None,
    ) -> str:
        """List and discover available standard PDF templates in the framework.

        Use this tool when you need to find a suitable template for generating
        invoices, receipts, weekly reports, business analysis, or summaries.
        """
        if query:
            templates = reg.search_templates(query)
            if category:
                templates = [t for t in templates if t.category.value == category]
        else:
            templates = reg.list_templates(category=category)

        if not templates:
            return "No PDF templates found matching the criteria."

        items: list[dict[str, Any]] = []
        for t in templates:
            items.append(
                {
                    "template_id": t.id,
                    "name": t.name,
                    "category": t.category.value,
                    "description": t.description,
                    "tags": t.tags,
                    "variables_count": len(t.variables),
                }
            )
        return json.dumps(
            {"templates": items, "total": len(items)}, ensure_ascii=False, indent=2
        )

    @tool
    def get_pdf_template_schema(
        template_id: Annotated[
            str,
            "The ID of the template to inspect (e.g. 'invoice_standard', 'business_report', 'receipt_minimal')",
        ],
    ) -> str:
        """Get the detailed JSON Schema and required variables for a specific PDF template.

        Always call this tool before generating a PDF to inspect the exact field names,
        data types, and example values expected by the template.
        """
        tmpl = reg.get_template(template_id)
        if tmpl is None:
            return json.dumps(
                {
                    "error": f"Template '{template_id}' not found.",
                    "available_templates": [t.id for t in reg.list_templates()],
                },
                ensure_ascii=False,
            )

        schema = tmpl.get_json_schema()
        return json.dumps(
            {
                "template_id": tmpl.id,
                "name": tmpl.name,
                "category": tmpl.category.value,
                "description": tmpl.description,
                "json_schema": schema,
                "options": tmpl.default_options.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        )

    @tool
    async def render_pdf_template(
        template_id: Annotated[
            str,
            "The ID of the template to use (e.g. 'invoice_standard', 'business_report')",
        ],
        data_json: Annotated[
            str,
            "JSON string containing all the template variables matching the template schema",
        ],
        output_path: Annotated[
            str,
            "Destination file path for the exported PDF (e.g. 'artifacts/weekly_report.pdf')",
        ],
    ) -> str:
        """Render a structured PDF document from a template and JSON data payload.

        Renders high-fidelity, printable PDF with embedded CJK fonts, page break control,
        and standard corporate styles. The resulting PDF file can be previewed or downloaded.
        """
        try:
            payload = json.loads(data_json) if isinstance(data_json, str) else data_json
            if not isinstance(payload, dict):
                return json.dumps(
                    {"error": "data_json must be a valid JSON object dictionary"},
                    ensure_ascii=False,
                )
        except Exception as e:
            return json.dumps(
                {"error": f"Invalid JSON format in data_json: {e}"}, ensure_ascii=False
            )

        res = await eng.render_to_pdf(
            template_id=template_id, data=payload, output_path=output_path
        )
        if not res.success:
            return json.dumps(
                {
                    "success": False,
                    "error": res.error_message,
                    "template_id": template_id,
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "success": True,
                "output_path": res.output_path,
                "template_id": template_id,
                "message": f"Successfully compiled PDF document using template '{template_id}' to {res.output_path}",
            },
            ensure_ascii=False,
            indent=2,
        )

    return [list_pdf_templates, get_pdf_template_schema, render_pdf_template]
