"""Architecture and design for PDF templates toolkit.

# pdf_templates/

## Overview
Provides a framework-agnostic, single-source-of-truth PDF template registry and declarative
rendering engine for structured business document exports (invoices, business reports, receipts).

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports registry, engine, manifests, and tools | — |
| `manifest.py` | Types | Template manifest, schema, options, and category descriptors | ✅ |
| `registry.py` | Core | Singleton template registry with category filtering and schema generators | ✅ |
| `engine.py` | Engine | Safe Jinja2 interpolation, sanitization, and PDF rendering engine | ✅ |
| `pdf_templates_agent_tools.py` | Tools | LangChain tool bindings (`list_pdf_templates`, `render_pdf_template`, etc.) | ✅ |
| `_ARCH.md` | Doc | Architectural reference and template inventory | — |

## Key Components
1. `manifest.py`: `PdfTemplateManifest`, `PdfTemplateCategory`, `PdfTemplateRenderOptions`, `PdfTemplateVariableSchema`.
2. `registry.py`: `PdfTemplateRegistry` (singleton SSOT with search, filter, JSON schema generation, built-in 10 enterprise templates).
3. `engine.py`: `PdfRenderEngine` (safe Jinja2 template interpolation with ChoiceLoader, SSRF protocol sanitizer, inline event handler stripper, Headless Chromium print integration).
4. `pdf_templates_agent_tools.py`: LangChain tool factory (`create_pdf_template_tools`) exposing `list_pdf_templates`, `get_pdf_template_schema`, and `render_pdf_template`.
5. `templates/`: Baseline declarative Jinja2/HTML templates with embedded CSS Paged Media (`@page`, `page-break-inside: avoid`) and responsive typography.
6. `templates/blocks/`: Modular reusable partials and Jinja2 vector SVG chart macros (`header_block.html`, `party_info_block.html`, `items_table_block.html`, `tax_summary_block.html`, `signature_seal_block.html`, `svg_charts.html`).

## Built-in Templates (10 Industrial Standards)
- **Finance & Settlement (6)**: `invoice_vat_standard`, `invoice_commercial_b2b`, `invoice_subscription_saas`, `receipt_payment_minimal`, `settlement_consulting_fee`, `expense_travel_reimbursement`.
- **Reports & Audits (4)**: `report_executive_summary`, `report_security_audit`, `report_project_milestone`, `report_technical_analysis`.

## Architecture Boundaries
- Absolutely zero imports from `agent/`, `runtime/`, or `backends/`.
- Zero node/npm runtime lock.
- Prompt cache friendly (only schemas exposed to LLM; template sources remain in python engine).
"""
