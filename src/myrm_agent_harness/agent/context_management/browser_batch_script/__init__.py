"""Package facade for browser automation batch processing and script synthesis.

[INPUT]
- agent.context_management.browser_batch_script.browser_batch_engine::BrowserBatchProcessingEngine (POS:
  Manages script synthesis, batch execution, and single-turn context aggregation.)
- agent.context_management.browser_batch_script.browser_batch_types::ArtifactFormatKind,
  BatchExecutionResult, BatchExtractionIntent, BatchFieldSpec, DashboardMetricCard,
  InteractiveDashboardSpec, PaginationStrategy, SynthesizedBrowserScript (POS: Data contracts for batch script
  generation, single-turn context distillation, and dashboard compilation.)
- agent.context_management.browser_batch_script.browser_script_synthesizer::synthesize_batch_crawling_script (POS:
  Autonomous browser automation script synthesizer for batch web processing.)

[OUTPUT]
- Re-exports: ArtifactFormatKind, BatchExecutionResult, BatchExtractionIntent, BatchFieldSpec,
  BrowserBatchProcessingEngine, DashboardMetricCard, InteractiveDashboardSpec, PaginationStrategy,
  SynthesizedBrowserScript, synthesize_batch_crawling_script

[POS]
Browser batch script synthesis, single-turn context distillation, and dashboard compilation facade.
"""

from __future__ import annotations

from .browser_batch_engine import BrowserBatchProcessingEngine
from .browser_batch_types import (
    ArtifactFormatKind,
    BatchExecutionResult,
    BatchExtractionIntent,
    BatchFieldSpec,
    DashboardMetricCard,
    InteractiveDashboardSpec,
    PaginationStrategy,
    SynthesizedBrowserScript,
)
from .browser_script_synthesizer import synthesize_batch_crawling_script

__all__ = [
    "ArtifactFormatKind",
    "BatchExecutionResult",
    "BatchExtractionIntent",
    "BatchFieldSpec",
    "BrowserBatchProcessingEngine",
    "DashboardMetricCard",
    "InteractiveDashboardSpec",
    "PaginationStrategy",
    "SynthesizedBrowserScript",
    "synthesize_batch_crawling_script",
]
