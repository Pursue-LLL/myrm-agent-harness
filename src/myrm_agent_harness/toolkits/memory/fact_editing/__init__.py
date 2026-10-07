"""Hebbian Fact Injection and Linear Memory Editing package.

Provides high-priority factual patch registries and projection interceptors
to defeat model pre-trained prior bias (inspired by Kimi KDA & Hebbian memory).

[INPUT]
- toolkits.memory.fact_editing.interceptor::FactProjectionInterceptor (POS: Forward attention modulation
  gate suppressing model pre-trained prior bias.)
- toolkits.memory.fact_editing.models::ConflictProbeReport, FactPatch, PatchMatchResult (POS: Foundational
  contracts for direct fact editing and pre-trained prior bias elimination.)
- toolkits.memory.fact_editing.registry::FactPatchRegistry (POS: Authoritative repository for overriding
  stubborn pre-trained model prior biases.)

[OUTPUT]
- Package facade re-exporting 5 public names: ConflictProbeReport, FactPatch, FactPatchRegistry,
  FactProjectionInterceptor, PatchMatchResult

[POS]
Hebbian Fact Injection and Linear Memory Editing package.
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
