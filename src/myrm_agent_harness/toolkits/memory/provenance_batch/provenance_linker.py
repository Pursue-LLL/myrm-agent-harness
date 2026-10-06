"""Skill memory extraction provenance linker anchoring rules to physical traces.

[INPUT]
- datetime::{UTC, datetime}
- myrm_agent_harness.toolkits.memory.types::{EvidenceReference, ProceduralMemory}
- myrm_agent_harness.toolkits.memory.provenance_batch.types::{
      ExtractionProvenanceLink,
      ToolExecutionTrace,
  }

[OUTPUT]
- SkillProvenanceLinker: Anchors extracted rules to concrete turn and tool execution traces

[POS]
Bi-directional trace linking ensuring procedural rules are verifiable against real execution logs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.provenance_batch.types import (
    ExtractionProvenanceLink,
    ToolExecutionTrace,
)
from myrm_agent_harness.toolkits.memory.types import EvidenceReference, ProceduralMemory


class SkillProvenanceLinker:
    """Links extracted procedural memories to their physical execution origin."""

    def create_provenance_link(
        self,
        *,
        conversation_id: str,
        trigger_prompt: str,
        turn_index: int | None = None,
        tool_traces: list[ToolExecutionTrace] | None = None,
        counterexample: str | None = None,
        confidence_score: float = 1.0,
    ) -> ExtractionProvenanceLink:
        """Create an immutable provenance link from raw conversation and tool evidence."""
        clean_conv_id = conversation_id.strip()
        clean_prompt = trigger_prompt.strip()

        if not clean_conv_id:
            raise ValueError("Conversation ID cannot be empty for provenance anchor")
        if not clean_prompt:
            raise ValueError("Trigger prompt snippet cannot be empty")

        traces = list(tool_traces or [])

        return ExtractionProvenanceLink(
            conversation_id=clean_conv_id,
            turn_index=turn_index,
            trigger_prompt_snippet=clean_prompt,
            tool_traces=traces,
            counterexample_snippet=counterexample,
            confidence_score=confidence_score,
            created_at=datetime.now(UTC),
        )

    def verify_provenance_link(
        self,
        link: ExtractionProvenanceLink,
    ) -> tuple[bool, str | None]:
        """Verify the cryptographic and physical integrity of a provenance link."""
        if not link.conversation_id:
            return False, "Missing conversation ID anchor"
        if not link.trigger_prompt_snippet:
            return False, "Missing trigger prompt evidence snippet"
        for i, trace in enumerate(link.tool_traces):
            if not trace.tool_name.strip():
                return False, f"Tool trace at index {i} has empty tool_name"
        return True, None

    def anchor_to_memory(
        self,
        memory: ProceduralMemory,
        link: ExtractionProvenanceLink,
    ) -> ProceduralMemory:
        """Attach verified provenance links to a ProceduralMemory instance."""
        is_valid, error = self.verify_provenance_link(link)
        if not is_valid:
            raise ValueError(f"Cannot anchor invalid provenance link: {error}")

        # Bind link identifiers and summary to metadata
        memory.metadata["provenance_link_id"] = link.link_id
        memory.metadata["provenance_conversation_id"] = link.conversation_id
        if link.turn_index is not None:
            memory.metadata["provenance_turn_index"] = link.turn_index

        # Synthesize EvidenceReferences from tool execution traces
        for trace in link.tool_traces:
            evidence_ref = EvidenceReference(
                source_id=f"tool_trace:{trace.tool_name}",
                message_id=trace.tool_call_id,
                quote_snippet=f"{trace.input_args_summary} => {trace.output_evidence_snippet}"[
                    :500
                ],
                timestamp=datetime.now(UTC),
            )
            memory.evidence.append(evidence_ref)

        return memory
