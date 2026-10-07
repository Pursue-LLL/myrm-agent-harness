# [POS]: myrm_agent_harness.toolkits.memory.authoritative_conclusions.anchor
# [INPUT]: models.py
# [OUTPUT]: ConclusionContextAnchor

"""Context anchor formatter for authoritative conclusions.

P0 delivery for Item 111 in topic_01 memory roadmap.
Formats active confirmed conclusions into high-salience prompt anchor blocks
to eliminate decision dilution across long-horizon agent trajectories.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.authoritative_conclusions.models import (
    AuthoritativeConclusion,
    ConclusionAnchorProjection,
    ConclusionStatus,
)

logger = logging.getLogger(__name__)


class ConclusionContextAnchor:
    """Formatter that aggregates confirmed conclusions into anti-dilution prompt blocks."""

    def format_anchor_block(
        self,
        conclusions: list[AuthoritativeConclusion],
    ) -> ConclusionAnchorProjection:
        """Render active confirmed conclusions grouped by domain scope."""
        active = [c for c in conclusions if c.status == ConclusionStatus.CONFIRMED]
        if not active:
            return ConclusionAnchorProjection(
                formatted_prompt_block="",
                total_active_conclusions=0,
                token_estimate=0,
            )

        # Group by scope_tag
        grouped: dict[str, list[AuthoritativeConclusion]] = {}
        for c in active:
            grouped.setdefault(c.scope_tag, []).append(c)

        lines: list[str] = [
            "[AUTHORITATIVE ARCHITECTURAL & BUSINESS CONCLUSIONS]",
            "The following normative decisions are explicitly confirmed and binding:",
        ]

        for scope, items in sorted(grouped.items()):
            lines.append(f"- Scope [{scope.upper()}]:")
            for item in items:
                lines.append(
                    f"  * {item.content} (by @{item.peer_id}, id: {item.conclusion_id})"
                )

        rendered = "\n".join(lines)
        token_estimate = max(1, len(rendered) // 4)

        logger.debug(
            "Rendered conclusion anchor: %d conclusions, ~%d tokens",
            len(active),
            token_estimate,
        )
        return ConclusionAnchorProjection(
            formatted_prompt_block=rendered,
            total_active_conclusions=len(active),
            token_estimate=token_estimate,
        )
