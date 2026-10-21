"""[INPUT]
- None (pure domain model contract)

[OUTPUT]
- DelightCategory, DelightTemplate, SingleFileSandboxContract, SandboxValidationResult

[POS]
Harness framework layer contracts for Zero-Code Hobbyist Delight Template & Single-File Sandbox Showcase (Item 40 P0).
Strictly under 120 lines. Zero `Any`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

DelightCategory = Literal[
    "celebration",      # Birthday, anniversary, festivals
    "interactive_fun",  # Casual physics, interactive canvas
    "romance_memory",   # Love confession, countdown, memory timeline
    "utility_tools",    # Lucky wheel, dice, decision maker
    "generative_art",   # Fireworks, particle waves, generative visuals
]


@dataclass(slots=True)
class DelightTemplate:
    template_id: str
    title: str
    category: DelightCategory
    description: str
    prompt_seed: str
    html_source: str
    tags: list[str] = field(default_factory=list)
    icon_name: str = "sparkles"
    is_featured: bool = True
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class SingleFileSandboxContract:
    contract_id: str
    session_id: str
    title: str
    html_content: str
    has_canvas: bool
    has_audio: bool
    has_tailwind: bool
    is_self_contained: bool
    compiled_html: str
    finalized_at_ms: float = field(default_factory=lambda: time.time() * 1000.0)


@dataclass(slots=True)
class SandboxValidationResult:
    is_valid: bool
    issues: list[str]
    has_canvas: bool
    has_audio: bool
    has_tailwind: bool
    compiled_html: str
