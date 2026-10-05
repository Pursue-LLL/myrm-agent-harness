"""Hebbian Fact Injection and Linear Memory Editing package.

Provides high-priority factual patch registries and projection interceptors
to defeat model pre-trained prior bias (inspired by Kimi KDA & Hebbian memory).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.fact_editing.interceptor import (
    FactProjectionInterceptor,
)
from myrm_agent_harness.toolkits.memory.fact_editing.models import (
    ConflictProbeReport,
    FactPatch,
    PatchMatchResult,
)
from myrm_agent_harness.toolkits.memory.fact_editing.registry import (
    FactPatchRegistry,
)

__all__ = [
    "ConflictProbeReport",
    "FactPatch",
    "FactPatchRegistry",
    "FactProjectionInterceptor",
    "PatchMatchResult",
]
