"""[INPUT]
- None (pure domain model contract)

[OUTPUT]
- UiVariantStyle, UiVariant, VisualAnnotation, VisualContract

[POS]
Harness framework layer contracts for Multi-Turn UI Design Visual Alignment Workflow (Item 39 P0).
Follows Alibaba Qoder design alignment & high-fidelity code-first paradigm.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

UiVariantStyle = Literal[
    "modern_bento",
    "minimal_dark",
    "glassmorphism",
    "neo_brutalism",
    "custom",
]


@dataclass(slots=True)
class UiVariant:
    variant_id: str
    title: str
    style_theme: UiVariantStyle
    html_content: str
    css_tokens: dict[str, str] = field(default_factory=dict)
    description: str = ""
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class VisualAnnotation:
    annotation_id: str
    variant_id: str
    x: float  # Percentage 0.0 ~ 100.0
    y: float  # Percentage 0.0 ~ 100.0
    width: float  # Percentage 0.0 ~ 100.0
    height: float  # Percentage 0.0 ~ 100.0
    comment: str
    label: str = "visual_feedback"
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class VisualContract:
    contract_id: str
    session_id: str
    approved_variant_id: str
    style_theme: UiVariantStyle
    dom_outline: str
    design_tokens: dict[str, str]
    annotations: list[VisualAnnotation]
    enforcement_prompt: str
    finalized_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)
