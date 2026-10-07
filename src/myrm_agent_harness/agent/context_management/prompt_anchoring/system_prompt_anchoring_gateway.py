# ============================================================================
# System Prompt Static Prefix Anchoring & Tail Redirector Gateway (Item 168)
# Strict dual-layer system prompt decoupling: Immutable Static Anchor Layer A at
# position 0, dynamic Ephemeral Metadata Layer B redirected to message tail.
# ============================================================================

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .prompt_anchoring_types import (
    AnchoredPromptBundle,
    EphemeralRuntimeMetadata,
    PrefixCacheDriftVerification,
    StaticAnchorBlueprint,
)

logger = logging.getLogger(__name__)


def _compute_sha256(text: str) -> str:
    """Compute deterministic SHA-256 hex digest for text string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SystemPromptAnchoringGateway:
    """Gateway orchestrating dual-layer system prompt assembly and tail redirection."""

    def format_layer_a_static_prefix(self, blueprint: StaticAnchorBlueprint) -> str:
        """Format immutable Layer A static anchor text guaranteed identical across turns."""
        sections: list[str] = [
            "# SYSTEM INSTRUCTIONS\n" + blueprint.system_instructions.strip(),
            "# SAFETY GUIDELINES\n" + blueprint.safety_guidelines.strip(),
            "# TOOL CALLING PROTOCOLS\n" + blueprint.tool_protocols.strip(),
        ]
        if blueprint.domain_knowledge.strip():
            sections.append("# DOMAIN CONSTRAINTS\n" + blueprint.domain_knowledge.strip())

        return "\n\n".join(sections)

    def format_layer_b_ephemeral_tail(self, meta: EphemeralRuntimeMetadata) -> str:
        """Format dynamic Layer B environment metadata into structured XML tail block."""
        lines: list[str] = [
            "<ephemeral_runtime_environment>",
            f'  <current_time timezone="{meta.timezone_name}">{meta.timestamp_iso}</current_time>',
            f"  <session_id>{meta.session_id}</session_id>",
            f"  <workspace_cwd>{meta.workspace_cwd}</workspace_cwd>",
        ]
        for k in sorted(meta.additional_variables.keys()):
            v = meta.additional_variables[k]
            lines.append(f'  <variable name="{k}">{v}</variable>')
        lines.append("</ephemeral_runtime_environment>")
        return "\n".join(lines)

    def build_anchored_prompt(
        self,
        static_blueprint: StaticAnchorBlueprint,
        ephemeral_metadata: EphemeralRuntimeMetadata,
        redirect_to_user_tail: bool = True,
    ) -> AnchoredPromptBundle:
        """Assemble dual-layer prompt separating static prefix from ephemeral metadata."""
        layer_a_text = self.format_layer_a_static_prefix(static_blueprint)
        layer_a_hash = _compute_sha256(layer_a_text)

        layer_b_text = self.format_layer_b_ephemeral_tail(ephemeral_metadata)
        layer_b_hash = _compute_sha256(layer_b_text)

        # Estimate tokens conservatively (1 token ~= 4 chars)
        prefix_tokens_estimate = max(1, len(layer_a_text) // 4)

        if redirect_to_user_tail:
            # Optimal practice: System message is 100% pristine Layer A
            combined_system = layer_a_text
        else:
            # Fallback: Layer B appended strictly at the very end of System message
            combined_system = f"{layer_a_text}\n\n# RUNTIME CONTEXT\n{layer_b_text}"

        logger.info(
            "Built Anchored Prompt: Layer A sha=%s (~%d tokens), redirect_tail=%s",
            layer_a_hash[:10],
            prefix_tokens_estimate,
            redirect_to_user_tail,
        )

        return AnchoredPromptBundle(
            layer_a_static_prefix=layer_a_text,
            layer_a_sha256=layer_a_hash,
            layer_b_tail_injection=layer_b_text,
            layer_b_sha256=layer_b_hash,
            combined_system_prompt=combined_system,
            redirect_to_user_message=redirect_to_user_tail,
            prefix_tokens_estimate=prefix_tokens_estimate,
        )

    def verify_prefix_invariance(
        self,
        bundle_1: AnchoredPromptBundle,
        bundle_2: AnchoredPromptBundle,
    ) -> PrefixCacheDriftVerification:
        """Verify that dynamic temporal changes in Layer B do not cause Layer A prefix drift."""
        static_match = bundle_1.layer_a_sha256 == bundle_2.layer_a_sha256
        tail_changed = bundle_1.layer_b_sha256 != bundle_2.layer_b_sha256

        if static_match:
            is_stable = True
            drift_detected = False
            notes = (
                "Static Layer A prefix hash is 100% identical. Ephemeral tail variations "
                "safely isolated to message tail without invalidating prefix cache."
            )
        else:
            is_stable = False
            drift_detected = True
            notes = (
                f"CRITICAL: Static Layer A prefix hash altered! Prev: {bundle_1.layer_a_sha256[:8]}, "
                f"Curr: {bundle_2.layer_a_sha256[:8]}. Prompt prefix cache broken."
            )

        return PrefixCacheDriftVerification(
            is_prefix_stable=is_stable,
            layer_a_prefix_hash=bundle_1.layer_a_sha256,
            drift_detected_in_static=drift_detected,
            ephemeral_tail_changed=tail_changed,
            diagnostic_notes=notes,
        )

    def inject_into_messages(
        self,
        messages: Sequence[BaseMessage],
        bundle: AnchoredPromptBundle,
    ) -> tuple[BaseMessage, ...]:
        """Inject anchored system prompt at position 0 and redirect ephemeral tail if configured."""
        result: list[BaseMessage] = []

        # 1. Ensure SystemMessage at index 0 has combined_system_prompt
        has_system = any(isinstance(m, SystemMessage) for m in messages)
        system_msg = SystemMessage(content=bundle.combined_system_prompt)

        if not has_system:
            result.append(system_msg)
            result.extend(messages)
        else:
            replaced_first_system = False
            for m in messages:
                if isinstance(m, SystemMessage) and not replaced_first_system:
                    result.append(system_msg)
                    replaced_first_system = True
                else:
                    result.append(m)

        # 2. If configured to redirect to user tail, append Layer B to final HumanMessage
        if bundle.redirect_to_user_message and result:
            # Find last HumanMessage index
            last_human_idx = -1
            for idx in range(len(result) - 1, -1, -1):
                if isinstance(result[idx], HumanMessage):
                    last_human_idx = idx
                    break

            if last_human_idx >= 0:
                old_human = result[last_human_idx]
                updated_content = (
                    f"{old_human.content}\n\n{bundle.layer_b_tail_injection}"
                )
                result[last_human_idx] = HumanMessage(
                    content=updated_content,
                    additional_kwargs=dict(old_human.additional_kwargs),
                )

        return tuple(result)
