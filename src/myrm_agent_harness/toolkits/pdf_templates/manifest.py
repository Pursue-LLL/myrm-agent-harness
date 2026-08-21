"""PDF Template Manifest data contracts.

[INPUT]
pydantic::BaseModel, Field (POS: data validation)
enum::Enum (POS: category enumeration)

[OUTPUT]
- PdfTemplateCategory: Template category enumeration
- PdfTemplateManifest: Template metadata and schema definition
- PdfTemplateRenderOptions: Options for PDF rendering
- PdfTemplateVariableSchema: Parameter schema definition for template variables

[POS]
Defines the single-source-of-truth contract for PDF templates in Myrm Agent Harness.
Each template registers metadata, description, required/optional parameter schemas,
and HTML/CSS template references.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class PdfTemplateCategory(str, Enum):
    """Category classification for PDF templates."""

    INVOICE = "invoice"
    REPORT = "report"
    RECEIPT = "receipt"
    CERTIFICATE = "certificate"
    DOCUMENT = "document"
    CUSTOM = "custom"


class PdfTemplateVariableSchema(BaseModel):
    """Schema descriptor for a single variable used in a PDF template."""

    name: str = Field(..., description="Variable identifier name")
    type: str = Field(
        default="string",
        description="JSON schema type: string, number, boolean, array, object",
    )
    description: str = Field(
        default="", description="Human and LLM readable description of the variable"
    )
    required: bool = Field(
        default=True, description="Whether this variable must be provided"
    )
    default: Any | None = Field(
        default=None, description="Default fallback value if not provided"
    )
    example: Any | None = Field(
        default=None, description="Example value for few-shot prompt guidance"
    )


class PdfTemplateRenderOptions(BaseModel):
    """Rendering options for PDF export."""

    page_size: str = Field(
        default="A4", description="Page size: A4, Letter, Legal, etc."
    )
    orientation: str = Field(
        default="portrait", description="Orientation: portrait or landscape"
    )
    margin_top: str = Field(default="15mm", description="Top page margin")
    margin_bottom: str = Field(default="15mm", description="Bottom page margin")
    margin_left: str = Field(default="15mm", description="Left page margin")
    margin_right: str = Field(default="15mm", description="Right page margin")
    print_background: bool = Field(
        default=True, description="Whether to print background graphics and colors"
    )
    display_header_footer: bool = Field(
        default=False, description="Whether to show native browser header/footer"
    )
    header_template: str = Field(
        default="", description="HTML template for native header"
    )
    footer_template: str = Field(
        default="", description="HTML template for native footer"
    )


class PdfTemplateManifest(BaseModel):
    """Single Source of Truth Manifest definition for a PDF template."""

    id: str = Field(
        ...,
        description="Unique template identifier, e.g. 'invoice_standard', 'business_report'",
    )
    name: str = Field(..., description="Human-readable template title")
    category: PdfTemplateCategory = Field(
        default=PdfTemplateCategory.DOCUMENT, description="Template category"
    )
    version: str = Field(
        default="1.0.0", description="Semantic version of the template"
    )
    description: str = Field(
        ..., description="Detailed description of when and how to use this template"
    )
    variables: list[PdfTemplateVariableSchema] = Field(
        default_factory=list,
        description="List of variable schemas accepted by the template",
    )
    template_html: str = Field(
        default="",
        description="Inline HTML/Jinja2 template string (optional if template_path is provided)",
    )
    template_path: str | None = Field(
        default=None,
        description="Relative or absolute file path to the template HTML file",
    )
    default_options: PdfTemplateRenderOptions = Field(
        default_factory=PdfTemplateRenderOptions,
        description="Default rendering options for this template",
    )
    tags: list[str] = Field(
        default_factory=list, description="Searchable tags, e.g. ['finance', 'billing']"
    )

    def get_json_schema(self) -> dict[str, Any]:
        """Generate a standard JSON Schema object representing the variables payload."""
        properties: dict[str, Any] = {}
        required_fields: list[str] = []

        for var in self.variables:
            prop: dict[str, Any] = {
                "type": var.type,
                "description": var.description,
            }
            if var.default is not None:
                prop["default"] = var.default
            if var.example is not None:
                prop["examples"] = [var.example]
            properties[var.name] = prop
            if var.required:
                required_fields.append(var.name)

        return {
            "type": "object",
            "title": f"{self.id}_payload",
            "description": f"Variables payload for PDF template: {self.name}",
            "properties": properties,
            "required": required_fields,
            "additionalProperties": True,
        }
