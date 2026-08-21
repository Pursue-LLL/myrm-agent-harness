"""Architecture and design for PDF templates toolkit.

# pdf_templates/

## Overview
Provides a framework-agnostic, single-source-of-truth PDF template registry and declarative
rendering engine for structured business document exports (invoices, business reports, receipts).

## Key Components
1. `manifest.py`: `PdfTemplateManifest`, `PdfTemplateCategory`, `PdfTemplateRenderOptions`, `PdfTemplateVariableSchema`.
2. `registry.py`: `PdfTemplateRegistry` (singleton SSOT with search, filter, JSON schema generation, built-in templates).
3. `engine.py`: `PdfRenderEngine` (safe Jinja2 template interpolation, SSRF protocol sanitizer, Headless Chromium print integration).
4. `pdf_templates_agent_tools.py`: LangChain tool factory (`create_pdf_template_tools`) exposing `list_pdf_templates`, `get_pdf_template_schema`, and `render_pdf_template`.
5. `templates/`: Baseline declarative Jinja2/HTML templates with embedded CSS Paged Media (`@page`, `page-break-inside: avoid`) and responsive typography.

## Architecture Boundaries
- Absolutely zero imports from `agent/`, `runtime/`, or `backends/`.
- Zero node/npm runtime lock.
- Prompt cache friendly (only schemas exposed to LLM; template sources remain in python engine).
"""
