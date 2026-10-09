"""Renderer transforming preflight estimates into honest send action specs and chip copy.

[INPUT]
- compact_chip_types: CompactActionPreference, CompactChipVerdict,
  CompactPreflightEstimate, SendButtonDisplaySpec.

[OUTPUT]
- SendActionLabelRenderer: Formats tokens and generates SendButtonDisplaySpec.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.compact_chip
- Module: send_action_label_renderer.py
"""

from myrm_agent_harness.agent.context_management.compact_chip.compact_chip_types import (
    CompactActionPreference,
    CompactChipVerdict,
    CompactPreflightEstimate,
    SendButtonDisplaySpec,
)


class SendActionLabelRenderer:
    """Renders honest send button labels, tooltips, and compact chip display metadata."""

    @staticmethod
    def format_tokens(count: int) -> str:
        """Formats integer token count into compact human readable label (e.g. 42k, 1.2M)."""
        if count < 1000:
            return str(count)
        if count < 1_000_000:
            val = count / 1000.0
            return f"{val:.1f}k" if val < 10.0 else f"{int(round(val))}k"
        val = count / 1_000_000.0
        return f"{val:.1f}M" if val < 10.0 else f"{int(round(val))}M"

    def render_display_spec(
        self,
        estimate: CompactPreflightEstimate,
        preference: CompactActionPreference,
        will_compact: bool,
    ) -> SendButtonDisplaySpec:
        """Resolves full button label, tooltip, and chip specification.

        Args:
            estimate: Evaluated context estimate.
            preference: User's action preference toggle.
            will_compact: Decided compaction execution outcome.

        Returns:
            SendButtonDisplaySpec governing composer UI state.
        """
        compressible = estimate.estimated_compressible_tokens
        if compressible == 0 and will_compact:
            compressible = int(estimate.total_tokens * 0.65)
        formatted_tokens = self.format_tokens(compressible)

        if will_compact:
            verdict = (
                CompactChipVerdict.MANUAL_COMPACT_REQUESTED
                if preference == CompactActionPreference.FORCE_COMPACT
                else CompactChipVerdict.COMPACT_WILL_TRIGGER
            )
            return SendButtonDisplaySpec(
                verdict=verdict,
                will_compact=True,
                primary_send_label="Compact and send",
                tooltip=(
                    f"Next send compacts ~{formatted_tokens} tokens of history first. "
                    "Click chip to keep full history."
                ),
                chip_visible=True,
                chip_text=f"Compact ~{formatted_tokens} tokens",
                estimated_tokens=compressible,
            )

        if preference == CompactActionPreference.FORCE_KEEP_FULL and (
            estimate.is_stale or estimate.is_pressured
        ):
            return SendButtonDisplaySpec(
                verdict=CompactChipVerdict.KEEP_FULL_OVERRIDDEN,
                will_compact=False,
                primary_send_label="Send",
                tooltip="Keeping full history without preflight compaction. Click chip to restore auto-compact.",
                chip_visible=True,
                chip_text="Full history kept",
                estimated_tokens=0,
            )

        return SendButtonDisplaySpec(
            verdict=CompactChipVerdict.HIDDEN,
            will_compact=False,
            primary_send_label="Send",
            tooltip="Send message",
            chip_visible=False,
            chip_text="",
            estimated_tokens=0,
        )
