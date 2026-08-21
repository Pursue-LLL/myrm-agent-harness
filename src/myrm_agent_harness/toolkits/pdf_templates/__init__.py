"""PDF Template Toolkit.

[INPUT]
- manifest::PdfTemplateCategory, PdfTemplateManifest, PdfTemplateRenderOptions, PdfTemplateVariableSchema
- registry::PdfTemplateRegistry, get_pdf_template_registry
- engine::PdfRenderEngine, PdfRenderResult, get_pdf_render_engine
- pdf_templates_agent_tools::create_pdf_template_tools

[OUTPUT]
- PdfTemplateCategory, PdfTemplateManifest, PdfTemplateRenderOptions, PdfTemplateVariableSchema: Data contracts
- PdfTemplateRegistry, get_pdf_template_registry: Registry SSOT
- PdfRenderEngine, PdfRenderResult, get_pdf_render_engine: Render engine
- create_pdf_template_tools: Agent tool factory

[POS]
PDF Template toolkit entry point. Re-exports the template registry,
rendering engine, data contracts, and LangChain tool factory.
"""

from __future__ import annotations

from .engine import (
    PdfRenderEngine,
    PdfRenderResult,
    get_pdf_render_engine,
)
from .manifest import (
    PdfTemplateCategory,
    PdfTemplateManifest,
    PdfTemplateRenderOptions,
    PdfTemplateVariableSchema,
)
from .pdf_templates_agent_tools import create_pdf_template_tools
from .registry import (
    PdfTemplateRegistry,
    get_pdf_template_registry,
)

__all__ = [
    "PdfRenderEngine",
    "PdfRenderResult",
    "PdfTemplateCategory",
    "PdfTemplateManifest",
    "PdfTemplateRegistry",
    "PdfTemplateRenderOptions",
    "PdfTemplateVariableSchema",
    "create_pdf_template_tools",
    "get_pdf_render_engine",
    "get_pdf_template_registry",
]
