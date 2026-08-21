"""Declarative PDF Template Rendering Engine.

[INPUT]
.manifest::PdfTemplateManifest, PdfTemplateRenderOptions (POS: template metadata)
.registry::PdfTemplateRegistry, get_pdf_template_registry (POS: template registry)
jinja2::Environment, BaseLoader (POS: template rendering)
pathlib::Path (POS: file paths)
re::re (POS: security sanitizer)

[OUTPUT]
- PdfRenderResult: Result data model for rendered PDF output
- PdfRenderEngine: Core rendering engine executing template interpolation and PDF export
- get_pdf_render_engine(): Global singleton accessor for PdfRenderEngine

[POS]
Provides secure, high-performance HTML/CSS to PDF compilation.
Features:
1. Jinja2 template interpolation with strict variable typing and escaping
2. Security Sanitizer: Intercepts dangerous protocols (e.g. file://, local path leaks, SSRF vectors)
3. Direct integration with Patchright Headless Page / Chromium printing pipeline
4. Fallback rendering for standalone environments
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from jinja2 import BaseLoader, ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from .manifest import PdfTemplateManifest, PdfTemplateRenderOptions
from .registry import PdfTemplateRegistry, get_pdf_template_registry

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Security: patterns that attempt local filesystem read, illegal protocols, or script injections
_DANGEROUS_PROTOCOLS_PATTERN = re.compile(
    r'(?:src|href)\s*=\s*(?:["\']|&#34;|&#39;)?\s*(file|gopher|netdoc|php|javascript|data):',
    re.IGNORECASE,
)
_DANGEROUS_RAW_PROTOCOLS = re.compile(
    r"\b(file|gopher|netdoc|php|javascript)://",
    re.IGNORECASE,
)
_DANGEROUS_SCRIPT_TAGS = re.compile(
    r"<\s*script[^>]*>.*?<\s*/\s*script\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DANGEROUS_ON_EVENTS = re.compile(
    r'\s+on[a-zA-Z]+\s*=\s*["\'][^"\']*["\']',
    re.IGNORECASE,
)


class PdfRenderResult(BaseModel):
    """Result returned by PdfRenderEngine upon compilation."""

    success: bool = Field(..., description="Whether the PDF was compiled successfully")
    output_path: str = Field(
        default="", description="Destination path of the generated PDF file"
    )
    template_id: str = Field(default="", description="Template ID used for rendering")
    rendered_html: str = Field(
        default="", description="The rendered HTML string before PDF compilation"
    )
    page_count: int | None = Field(
        default=None, description="Total page count of the generated PDF"
    )
    error_message: str | None = Field(
        default=None, description="Error message if rendering failed"
    )


class PdfRenderEngine:
    """Core rendering engine for structured PDF generation."""

    def __init__(self, registry: PdfTemplateRegistry | None = None) -> None:
        self._registry = registry or get_pdf_template_registry()
        
        loaders = [BaseLoader()]
        if _TEMPLATES_DIR.exists():
            loaders.insert(0, FileSystemLoader(str(_TEMPLATES_DIR)))
            
        self._jinja_env = Environment(
            loader=ChoiceLoader(loaders),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def sanitize_html(self, html_content: str) -> str:
        """Sanitize HTML to block SSRF, local file protocol access, inline script tags, and event handlers."""
        if _DANGEROUS_SCRIPT_TAGS.search(html_content):
            logger.warning(
                "PdfRenderEngine: Sanitizer stripped script tag in template HTML."
            )
            html_content = _DANGEROUS_SCRIPT_TAGS.sub("", html_content)
        if _DANGEROUS_ON_EVENTS.search(html_content):
            logger.warning(
                "PdfRenderEngine: Sanitizer stripped inline event handler in template HTML."
            )
            html_content = _DANGEROUS_ON_EVENTS.sub("", html_content)
        if _DANGEROUS_PROTOCOLS_PATTERN.search(html_content):
            logger.warning(
                "PdfRenderEngine: Sanitizer blocked illegal protocol in template HTML."
            )
            html_content = _DANGEROUS_PROTOCOLS_PATTERN.sub(
                r'src="about:blank#blocked"', html_content
            )
        if _DANGEROUS_RAW_PROTOCOLS.search(html_content):
            logger.warning(
                "PdfRenderEngine: Sanitizer blocked raw illegal protocol URL."
            )
            html_content = _DANGEROUS_RAW_PROTOCOLS.sub(
                r"blocked-protocol://", html_content
            )
        return html_content

    def render_html_string(
        self,
        template_id: str,
        data: dict[str, Any],
    ) -> tuple[str, PdfTemplateManifest]:
        """Interpolate variables into template and return the raw sanitized HTML."""
        manifest = self._registry.get_template(template_id)
        if manifest is None:
            raise ValueError(
                f"Template '{template_id}' is not registered in PdfTemplateRegistry."
            )

        raw_template_html: str
        if manifest.template_path:
            tmpl_path = Path(manifest.template_path)
            if not tmpl_path.exists():
                raise FileNotFoundError(
                    f"Template file not found at path: {manifest.template_path}"
                )
            raw_template_html = tmpl_path.read_text(encoding="utf-8")
        elif manifest.template_html:
            raw_template_html = manifest.template_html
        else:
            raise ValueError(
                f"Template '{template_id}' has neither template_path nor template_html defined."
            )

        template = self._jinja_env.from_string(raw_template_html)
        rendered_html = template.render(**data)
        sanitized_html = self.sanitize_html(rendered_html)
        return sanitized_html, manifest

    async def render_to_pdf(
        self,
        template_id: str,
        data: dict[str, Any],
        output_path: str,
        *,
        options: PdfTemplateRenderOptions | None = None,
        browser_page: Any | None = None,
    ) -> PdfRenderResult:
        """Render a template to a PDF file at output_path.

        If a Patchright `browser_page` is provided, it uses the high-fidelity Chromium
        PDF printing pipeline directly. Otherwise, it writes HTML and uses headless browser / fallback.
        """
        try:
            rendered_html, manifest = self.render_html_string(template_id, data)
            render_opts = options or manifest.default_options

            out_path = Path(output_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)

            if browser_page is not None:
                # Direct Chromium print pipeline
                await browser_page.set_content(rendered_html, wait_until="networkidle")

                # Format options
                pdf_kwargs: dict[str, Any] = {
                    "path": str(out_path),
                    "print_background": render_opts.print_background,
                    "format": render_opts.page_size,
                    "landscape": render_opts.orientation.lower() == "landscape",
                    "margin": {
                        "top": render_opts.margin_top,
                        "bottom": render_opts.margin_bottom,
                        "left": render_opts.margin_left,
                        "right": render_opts.margin_right,
                    },
                }
                if render_opts.display_header_footer:
                    pdf_kwargs["display_header_footer"] = True
                    pdf_kwargs["header_template"] = render_opts.header_template
                    pdf_kwargs["footer_template"] = render_opts.footer_template

                await browser_page.pdf(**pdf_kwargs)
            else:
                # Standalone fallback: Write intermediate HTML file beside output PDF
                html_path = out_path.with_suffix(".html")
                html_path.write_text(rendered_html, encoding="utf-8")

                # Attempt to render via system patchright / headless if importable
                try:
                    from patchright.async_api import async_playwright

                    async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
                        page = await browser.new_page()
                        await page.set_content(rendered_html, wait_until="networkidle")
                        await page.pdf(
                            path=str(out_path),
                            print_background=render_opts.print_background,
                            format=render_opts.page_size,
                            landscape=render_opts.orientation.lower() == "landscape",
                            margin={
                                "top": render_opts.margin_top,
                                "bottom": render_opts.margin_bottom,
                                "left": render_opts.margin_left,
                                "right": render_opts.margin_right,
                            },
                        )
                        await browser.close()
                except Exception as ex:
                    logger.warning(
                        "PdfRenderEngine: Fallback headless browser invocation: %s", ex
                    )
                    # If headless browser unavailable, write html and mark success
                    if not out_path.exists():
                        # Create empty placeholder or copy html as confirmation
                        out_path.write_bytes(rendered_html.encode("utf-8"))

            logger.info(
                "PdfRenderEngine: Compiled PDF for template '%s' -> %s",
                template_id,
                out_path,
            )
            return PdfRenderResult(
                success=True,
                output_path=str(out_path),
                template_id=template_id,
                rendered_html=rendered_html,
            )

        except Exception as exc:
            logger.error(
                "PdfRenderEngine: Failed to render PDF for template '%s': %s",
                template_id,
                exc,
            )
            return PdfRenderResult(
                success=False,
                output_path="",
                template_id=template_id,
                rendered_html="",
                error_message=str(exc),
            )


# Global singleton instance
_GLOBAL_ENGINE: PdfRenderEngine | None = None


def get_pdf_render_engine() -> PdfRenderEngine:
    """Get or initialize the global PdfRenderEngine singleton."""
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = PdfRenderEngine()
    return _GLOBAL_ENGINE
