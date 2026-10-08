"""Two-stage context pipeline and provider protocol decoupling package.

[INPUT]
- agent.context_management.two_stage_pipeline.pipeline_types::AssemblyAdjustmentDirective,
  LlmProviderProtocolKind, LogicalContextBundle, LogicalToolSpec, LogicalTurn, PipelineStageReceipt,
  ProviderPayloadResult (POS: Strong types and schemas for two-stage context assembly and provider protocol
  decoupling.)
- agent.context_management.two_stage_pipeline.protocol_transpiler::ProviderProtocolTranspiler (POS: Phase 2:
  Protocol conversion transpiling high-level logical context to provider-specific payloads.)
-
  agent.context_management.two_stage_pipeline.two_stage_pipeline_suite::TwoStageContextPipelineAndProviderProtocolDecouplingSuite
  (POS: Main suite orchestrating Phase 1 semantic assembly and Phase 2 protocol conversion.)

[OUTPUT]
- Re-exports: AssemblyAdjustmentDirective, LlmProviderProtocolKind, LogicalContextBundle, LogicalToolSpec,
  LogicalTurn, PipelineStageReceipt, ProviderPayloadResult, ProviderProtocolTranspiler,
  TwoStageContextPipelineAndProviderProtocolDecouplingSuite

[POS]
Two-stage context pipeline and provider protocol decoupling package.
"""

from __future__ import annotations

from .pipeline_types import (
    AssemblyAdjustmentDirective,
    LlmProviderProtocolKind,
    LogicalContextBundle,
    LogicalToolSpec,
    LogicalTurn,
    PipelineStageReceipt,
    ProviderPayloadResult,
)
from .protocol_transpiler import ProviderProtocolTranspiler
from .two_stage_pipeline_suite import (
    TwoStageContextPipelineAndProviderProtocolDecouplingSuite,
)

__all__ = [
    "AssemblyAdjustmentDirective",
    "LlmProviderProtocolKind",
    "LogicalContextBundle",
    "LogicalToolSpec",
    "LogicalTurn",
    "PipelineStageReceipt",
    "ProviderPayloadResult",
    "ProviderProtocolTranspiler",
    "TwoStageContextPipelineAndProviderProtocolDecouplingSuite",
]
