"""Main suite orchestrating Phase 1 semantic assembly and Phase 2 protocol conversion.

[INPUT]
- agent.context_management.session_tree_dag::SessionTreeEntry (POS: Immutable session tree DAG and branching
  exploration suite.)
- agent.context_management.two_stage_pipeline.pipeline_types::AssemblyAdjustmentDirective,
  LlmProviderProtocolKind, LogicalContextBundle, LogicalToolSpec, LogicalTurn, PipelineStageReceipt,
  ProviderPayloadResult (POS: Strong types and schemas for two-stage context assembly and provider protocol
  decoupling.)
- agent.context_management.two_stage_pipeline.protocol_transpiler::ProviderProtocolTranspiler (POS: Phase 2:
  Protocol conversion transpiling high-level logical context to provider-specific payloads.)

[OUTPUT]
- TwoStageContextPipelineAndProviderProtocolDecouplingSuite: Decouples business-facing semantic context
  assembly from wire-level LLM provider serialization.

[POS]
Main suite orchestrating Phase 1 semantic assembly and Phase 2 protocol conversion.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Dict, List, Optional, Tuple

from ..session_tree_dag import SessionTreeEntry
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


class TwoStageContextPipelineAndProviderProtocolDecouplingSuite:
    """Decouples business-facing semantic context assembly from wire-level LLM provider serialization."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._stage_receipts: List[PipelineStageReceipt] = []

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    def assemble_logical_context(
        self,
        system_prompts: List[str],
        workspace_rules: Optional[str] = None,
        tree_entries: Optional[List[SessionTreeEntry]] = None,
        manual_turns: Optional[List[LogicalTurn]] = None,
        tools: Optional[List[LogicalToolSpec]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        adjustment_directive: Optional[AssemblyAdjustmentDirective] = None,
    ) -> LogicalContextBundle:
        """Phase 1: Semantic assembly constructing high-level logical context independent of provider schema."""
        combined_directives: List[str] = []
        for prompt in system_prompts:
            clean_p = prompt.strip()
            if clean_p and clean_p not in combined_directives:
                combined_directives.append(clean_p)

        if workspace_rules and workspace_rules.strip():
            combined_directives.append(workspace_rules.strip())

        dialogue_turns: List[LogicalTurn] = []

        # Ingest from immutable tree entries if provided
        if tree_entries:
            for entry in tree_entries:
                role = entry.payload.get("role", "user")
                content = entry.payload.get("content", "")
                if not content:
                    continue
                dialogue_turns.append(
                    LogicalTurn(
                        turn_id=entry.entry_id,
                        role=role,
                        content=content,
                        metadata={"branch": entry.branch_name, "kind": entry.kind.value},
                    )
                )

        # Ingest manual turns
        if manual_turns:
            dialogue_turns.extend(manual_turns)

        # Handle reverse backchannel adjustment directive if present
        if adjustment_directive:
            if adjustment_directive.requires_inline_system and combined_directives:
                # Merge system directives into the first user turn instead of separate system section
                inlined_header = "\n\n".join(combined_directives)
                if dialogue_turns and dialogue_turns[0].role == "user":
                    first_turn = dialogue_turns[0]
                    new_content = f"{inlined_header}\n\n---\n{first_turn.content}"
                    dialogue_turns[0] = LogicalTurn(
                        turn_id=first_turn.turn_id,
                        role="user",
                        content=new_content,
                        metadata=first_turn.metadata,
                    )
                    combined_directives = []

            if adjustment_directive.strip_reasoning_traces:
                stripped_turns: List[LogicalTurn] = []
                for turn in dialogue_turns:
                    stripped_turns.append(
                        LogicalTurn(
                            turn_id=turn.turn_id,
                            role=turn.role,
                            content=turn.content,
                            tool_call_id=turn.tool_call_id,
                            tool_name=turn.tool_name,
                            reasoning_content=None,
                            metadata=turn.metadata,
                        )
                    )
                dialogue_turns = stripped_turns

        return LogicalContextBundle(
            session_id=self._session_id,
            system_directives=combined_directives,
            dialogue_turns=dialogue_turns,
            active_tools=list(tools or []),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def convert_to_provider_wire(
        self,
        logical_bundle: LogicalContextBundle,
        provider: LlmProviderProtocolKind,
    ) -> Tuple[ProviderPayloadResult, PipelineStageReceipt]:
        """Phase 2: Protocol conversion mapping logical bundle to exact provider wire payload."""
        payload_result, directive = ProviderProtocolTranspiler.transpile_to_provider(
            bundle=logical_bundle,
            provider=provider,
        )

        wire_bytes = len(json.dumps(payload_result.payload_dict, ensure_ascii=False).encode("utf-8"))
        pipeline_hash = hashlib.sha256(
            f"{self._session_id}:{provider.value}:{payload_result.payload_hash}:{wire_bytes}".encode("utf-8")
        ).hexdigest()[:16]

        receipt = PipelineStageReceipt(
            session_id=self._session_id,
            target_provider=provider,
            turns_count=len(logical_bundle.dialogue_turns),
            tools_count=len(logical_bundle.active_tools),
            system_directives_count=len(logical_bundle.system_directives),
            wire_payload_bytes=wire_bytes,
            pipeline_hash=pipeline_hash,
        )
        self._stage_receipts.append(receipt)

        return payload_result, receipt

    def run_end_to_end_pipeline(
        self,
        system_prompts: List[str],
        target_provider: LlmProviderProtocolKind,
        workspace_rules: Optional[str] = None,
        tree_entries: Optional[List[SessionTreeEntry]] = None,
        manual_turns: Optional[List[LogicalTurn]] = None,
        tools: Optional[List[LogicalToolSpec]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Tuple[ProviderPayloadResult, PipelineStageReceipt, LogicalContextBundle]:
        """Execute complete two-stage context transformation pipeline."""
        # Stage 1: Semantic assembly
        logical_bundle = self.assemble_logical_context(
            system_prompts=system_prompts,
            workspace_rules=workspace_rules,
            tree_entries=tree_entries,
            manual_turns=manual_turns,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Stage 2: Protocol conversion
        payload_result, receipt = self.convert_to_provider_wire(
            logical_bundle=logical_bundle,
            provider=target_provider,
        )

        return payload_result, receipt, logical_bundle

    def get_stage_receipts(self) -> List[PipelineStageReceipt]:
        """Retrieve all recorded pipeline stage receipts."""
        return list(self._stage_receipts)
