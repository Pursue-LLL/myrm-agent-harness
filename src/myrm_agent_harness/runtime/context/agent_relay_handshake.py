"""Heterogeneous Agent Context Handshake and Relay Protocol Bridge.

[INPUT]
- utils.text_utils::get_token_count, truncate_text_to_tokens (POS: Token estimation)

[OUTPUT]
- AgentProfileDescriptor: Spec for source and target agent vendor/window capabilities
- RelayStatePayload: Standardized Intermediate Representation (JSON IR) of in-flight work
- HandshakeResult: Handshake verification and hydrated handover prompt block
- AgentRelayPacketBuilder: Builder constructing standardized relay state IR
- ContextBudgetAdaptiveAligner: Adapts state budget to target agent window constraints
- AgentRelayHandshakeBridge: Executes handshake and returns seamless handover context

[POS]
Harness runtime context layer. Bridges heterogeneous AI agents (Claude, Codex, DeepSeek)
enabling zero-restatement handoffs without window overflow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from myrm_agent_harness.utils.text_utils import (
    get_token_count,
    truncate_text_to_tokens,
)


@dataclass(slots=True, frozen=True)
class AgentProfileDescriptor:
    """Capability specification for an agent participant in relay."""

    agent_id: str
    model_name: str
    vendor: str
    context_window_tokens: int
    specialties: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class RelayStatePayload:
    """Standardized Intermediate Representation (IR) of in-flight agent state."""

    relay_id: str
    source_agent: AgentProfileDescriptor
    target_agent: AgentProfileDescriptor
    session_id: str
    task_objective: str
    pending_goal: str
    recent_file_modifications: list[str] = field(default_factory=list)
    key_artifacts_produced: list[str] = field(default_factory=list)
    technical_conclusions: list[str] = field(default_factory=list)
    active_blockers: list[str] = field(default_factory=list)
    distilled_summary: str = ""
    created_at_iso: str = ""


@dataclass(slots=True, frozen=True)
class HandshakeResult:
    """Result of heterogeneous agent context relay handshake."""

    handshake_id: str
    status: str
    source_agent_id: str
    target_agent_id: str
    injected_context_prompt: str
    context_tokens_consumed: int
    is_compressed: bool


class AgentRelayPacketBuilder:
    """Builder for constructing validated RelayStatePayload instances."""

    @classmethod
    def create_payload(
        cls,
        source_agent: AgentProfileDescriptor,
        target_agent: AgentProfileDescriptor,
        session_id: str,
        task_objective: str,
        pending_goal: str,
        recent_file_modifications: list[str] | None = None,
        key_artifacts_produced: list[str] | None = None,
        technical_conclusions: list[str] | None = None,
        active_blockers: list[str] | None = None,
        distilled_summary: str = "",
    ) -> RelayStatePayload:
        """Create a standardized relay state payload with fresh ID and timestamp."""
        relay_id = f"relay_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()

        return RelayStatePayload(
            relay_id=relay_id,
            source_agent=source_agent,
            target_agent=target_agent,
            session_id=session_id,
            task_objective=task_objective,
            pending_goal=pending_goal,
            recent_file_modifications=list(recent_file_modifications or []),
            key_artifacts_produced=list(key_artifacts_produced or []),
            technical_conclusions=list(technical_conclusions or []),
            active_blockers=list(active_blockers or []),
            distilled_summary=distilled_summary,
            created_at_iso=now_iso,
        )


class ContextBudgetAdaptiveAligner:
    """Adapts and aligns state content tokens to match target agent window capacity."""

    @classmethod
    def calculate_safe_budget(cls, target_agent: AgentProfileDescriptor) -> int:
        """Calculate safe maximum tokens for the handoff context."""
        # Allocate up to 8% of target window, bounded between 500 and 3,500 tokens
        fractional = int(target_agent.context_window_tokens * 0.08)
        return max(500, min(3500, fractional))

    @classmethod
    def align_content(
        cls,
        raw_text: str,
        target_agent: AgentProfileDescriptor,
    ) -> tuple[str, bool]:
        """Compress or truncate handoff block if exceeding target agent's budget."""
        budget = cls.calculate_safe_budget(target_agent)
        current_tokens = get_token_count(raw_text)

        if current_tokens <= budget:
            return raw_text, False

        compressed = truncate_text_to_tokens(raw_text, budget)
        banner = "\n<!-- [Note: Prior context condensed to align with target agent window budget] -->\n"
        return f"{compressed}{banner}", True


class AgentRelayHandshakeBridge:
    """Executes state handshake and generates seamless handoff context prompt."""

    def __init__(
        self,
        aligner: type[ContextBudgetAdaptiveAligner] | None = None,
    ) -> None:
        self._aligner = aligner or ContextBudgetAdaptiveAligner

    def execute_handshake(self, payload: RelayStatePayload) -> HandshakeResult:
        """Validate relay payload, adapt budget, and generate prompt injection block."""
        handshake_id = f"hs_{uuid.uuid4().hex[:12]}"

        # Render structured handover prompt block
        raw_prompt = self._render_prompt_block(payload)

        # Budget adaptive alignment
        final_prompt, is_compressed = self._aligner.align_content(
            raw_prompt,
            payload.target_agent,
        )

        consumed_tokens = get_token_count(final_prompt)

        return HandshakeResult(
            handshake_id=handshake_id,
            status="success",
            source_agent_id=payload.source_agent.agent_id,
            target_agent_id=payload.target_agent.agent_id,
            injected_context_prompt=final_prompt,
            context_tokens_consumed=consumed_tokens,
            is_compressed=is_compressed,
        )

    @classmethod
    def _render_prompt_block(cls, payload: RelayStatePayload) -> str:
        """Render standardized XML handoff block for the incoming target agent."""
        lines: list[str] = [
            '<agent_relay_handoff mode="seamless_continuation">',
            f'  <source_agent id="{payload.source_agent.agent_id}" model="{payload.source_agent.model_name}" vendor="{payload.source_agent.vendor}"/>',
            f'  <target_agent id="{payload.target_agent.agent_id}" model="{payload.target_agent.model_name}"/>',
            f"  <session_id>{payload.session_id}</session_id>",
            f"  <task_objective>{payload.task_objective}</task_objective>",
            f"  <pending_goal>{payload.pending_goal}</pending_goal>",
        ]

        if payload.recent_file_modifications:
            lines.append("  <recent_modifications>")
            for fpath in payload.recent_file_modifications:
                lines.append(f"    <file>{fpath}</file>")
            lines.append("  </recent_modifications>")

        if payload.key_artifacts_produced:
            lines.append("  <artifacts_produced>")
            for art in payload.key_artifacts_produced:
                lines.append(f"    <artifact>{art}</artifact>")
            lines.append("  </artifacts_produced>")

        if payload.technical_conclusions:
            lines.append("  <technical_conclusions>")
            for item in payload.technical_conclusions:
                lines.append(f"    <item>{item}</item>")
            lines.append("  </technical_conclusions>")

        if payload.active_blockers:
            lines.append("  <active_blockers>")
            for b in payload.active_blockers:
                lines.append(f"    <blocker>{b}</blocker>")
            lines.append("  </active_blockers>")

        if payload.distilled_summary:
            lines.append(f"  <distilled_context>{payload.distilled_summary}</distilled_context>")

        lines.extend([
            "  <instruction>",
            "    You are inheriting this work session directly from the source agent without user re-statement.",
            "    Continue executing toward <pending_goal> immediately using the technical conclusions above.",
            "  </instruction>",
            "</agent_relay_handoff>",
        ])

        return "\n".join(lines)
