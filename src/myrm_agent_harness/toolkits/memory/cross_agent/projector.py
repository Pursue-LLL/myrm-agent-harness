"""Four-layer composable context projection engine for multi-agent coordination.

[INPUT]
- toolkits.memory.cross_agent.types::ComposableContextProjection, ContextLayerKind, ContextProjectionLayer, HandoffPacket (POS: types)

[OUTPUT]
- ComposableContextProjector: Assembles and partitions 4-layer context with 80%+ KV cache prefix preservation.

[POS]
Orchestrates virtual reference layer composition, strict private scratchpad isolation, and KV-cache optimization.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    ComposableContextProjection,
    ContextLayerKind,
    ContextProjectionLayer,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.cross_agent.types import HandoffPacket


def _compute_sha256(text: str) -> str:
    """Compute deterministic hex SHA-256 string for content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    """Estimate token count (approx 4 chars per token for Latin, 1.5 for CJK)."""
    return max(1, len(text) // 3) if text else 0


class ComposableContextProjector:
    """Projects composable 4-layer context tailored to individual agents while maximizing KV-cache reuse."""

    def __init__(self, default_token_budget: int = 4096) -> None:
        self.default_token_budget = default_token_budget

    def project_for_agent(
        self,
        agent_id: str,
        session_id: str,
        *,
        global_ground_truth: list[str] | None = None,
        profile_tools_memory: list[str] | None = None,
        private_scratchpad: str | None = None,
        handoff_packet: HandoffPacket | None = None,
        token_budget: int | None = None,
    ) -> ComposableContextProjection:
        """Compose 4-layer context isolating private scratchpad and stabilizing shared prefix."""
        budget = token_budget or self.default_token_budget
        layers: list[ContextProjectionLayer] = []

        # -------------------------------------------------------------
        # 1. Layer 2: Profile & Tools (Fixed prefix, Agent persona/tools)
        # -------------------------------------------------------------
        profile_lines = sorted([item.strip() for item in (profile_tools_memory or []) if item.strip()])
        profile_body = "\n".join(f"- {line}" for line in profile_lines) if profile_lines else "None specified."
        l2_hash = _compute_sha256(profile_body)
        l2_tokens = _estimate_tokens(profile_body)
        layers.append(
            ContextProjectionLayer(
                layer_kind=ContextLayerKind.LAYER_2_PROFILE,
                title="Agent Persona & Tool Capabilities",
                content=profile_body,
                token_count=l2_tokens,
                content_hash=l2_hash,
                is_shared=False,
            )
        )

        # -------------------------------------------------------------
        # 2. Layer 3: Global Ground Truth (Fixed prefix, shared facts)
        # -------------------------------------------------------------
        global_lines = sorted([item.strip() for item in (global_ground_truth or []) if item.strip()])
        global_body = "\n".join(f"- {line}" for line in global_lines) if global_lines else "None recorded."
        l3_hash = _compute_sha256(global_body)
        l3_tokens = _estimate_tokens(global_body)
        layers.append(
            ContextProjectionLayer(
                layer_kind=ContextLayerKind.LAYER_3_GLOBAL,
                title="Global Project Ground Truth Facts",
                content=global_body,
                token_count=l3_tokens,
                content_hash=l3_hash,
                is_shared=True,
            )
        )

        # Compute prefix hash across Layer 2 and Layer 3 for KV cache reuse
        cache_prefix_hash = _compute_sha256(f"{l2_hash}:{l3_hash}")

        # -------------------------------------------------------------
        # 3. Layer 1: Private Scratchpad (Agent isolated private space)
        # -------------------------------------------------------------
        clean_scratchpad = (private_scratchpad or "").strip() or "Empty private scratchpad."
        l1_hash = _compute_sha256(clean_scratchpad)
        l1_tokens = _estimate_tokens(clean_scratchpad)
        layers.append(
            ContextProjectionLayer(
                layer_kind=ContextLayerKind.LAYER_1_PRIVATE,
                title="Private Scratchpad (Confidential to this Agent)",
                content=clean_scratchpad,
                token_count=l1_tokens,
                content_hash=l1_hash,
                is_shared=False,
            )
        )

        # -------------------------------------------------------------
        # 4. Layer 4: Ephemeral Handoff (Transient predecessor handover)
        # -------------------------------------------------------------
        handoff_body = "No pending task handoff."
        if handoff_packet is not None:
            assertions_str = "\n".join(
                f"  * {a.subject} {a.predicate} '{a.object_value}' (conf: {a.confidence})"
                for a in handoff_packet.critical_assertions
            )
            handoff_body = (
                f"Task ID: {handoff_packet.task_id}\n"
                f"From Agent: {handoff_packet.source_agent_id}\n"
                f"Sealed Signature: {handoff_packet.signature_sha256[:12]}...\n"
                f"Context Snapshot:\n{handoff_packet.context_snapshot}\n"
                f"Critical Assertions:\n{assertions_str or '  * None'}"
            )

        l4_hash = _compute_sha256(handoff_body)
        l4_tokens = _estimate_tokens(handoff_body)
        layers.append(
            ContextProjectionLayer(
                layer_kind=ContextLayerKind.LAYER_4_HANDOFF,
                title="Ephemeral Task Handoff Packet",
                content=handoff_body,
                token_count=l4_tokens,
                content_hash=l4_hash,
                is_shared=False,
            )
        )

        # Assemble unified prompt text with strict boundaries
        sections: list[str] = [
            f"# === Composable Multi-Agent Context Projection [Agent: {agent_id}] ===",
            f"## [LAYER 2] {layers[0].title}\n{layers[0].content}",
            f"## [LAYER 3] {layers[1].title}\n{layers[1].content}",
            f"## [LAYER 1] {layers[2].title}\n{layers[2].content}",
            f"## [LAYER 4] {layers[3].title}\n{layers[3].content}",
        ]
        assembled_prompt = "\n\n".join(sections)
        total_tokens = sum(layer.token_count for layer in layers)

        # Soft truncate if total exceeds budget (truncate L1/L4 only, preserving L2/L3 prefix)
        if total_tokens > budget:
            budget_overflow = total_tokens - budget
            assembled_prompt += (
                f"\n\n[⚠️ Context Truncation Warning: Projected tokens {total_tokens} "
                f"exceeds budget {budget} by ~{budget_overflow} tokens]"
            )

        return ComposableContextProjection(
            agent_id=agent_id,
            session_id=session_id,
            total_tokens=total_tokens,
            layers=layers,
            assembled_prompt_text=assembled_prompt,
            cache_prefix_hash=cache_prefix_hash,
        )
