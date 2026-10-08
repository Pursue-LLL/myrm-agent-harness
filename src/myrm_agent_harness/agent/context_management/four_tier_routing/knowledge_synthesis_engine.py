"""Tier 4: Multi-source Knowledge Synthesis Engine.

[INPUT]
- FourTierContextConfig, SynthesisInput, SynthesizedDirective from four_tier_types.

[OUTPUT]
- KnowledgeSynthesisEngine: Distills fragmented ADRs, documentation snippets, and historical bug
  postmortems into singular, unambiguous engineering directives before prompt assembly.

[POS]
Synthesis engine replacing raw document dumping with high-leverage architectural assertions.
"""

from __future__ import annotations

import hashlib
import re
from typing import List, Sequence

from .four_tier_types import (
    FourTierContextConfig,
    SynthesisInput,
    SynthesizedDirective,
)


class KnowledgeSynthesisEngine:
    """Pre-processes and synthesizes multi-source knowledge fragments into actionable directives."""

    def __init__(self, config: FourTierContextConfig | None = None) -> None:
        self._config = config or FourTierContextConfig()

    @property
    def config(self) -> FourTierContextConfig:
        return self._config

    def synthesize(self, input_data: SynthesisInput) -> SynthesizedDirective:
        """Synthesize disparate knowledge fragments into a consolidated directive."""
        # 1. Generate unique deterministic directive ID
        seed = f"{input_data.query}:{len(input_data.fragments)}:{len(input_data.adrs)}"
        dir_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
        directive_id = f"directive_{dir_hash}"

        # 2. Extract architectural rules from ADRs
        actionable: List[str] = []
        conflicts: List[str] = []

        for adr in input_data.adrs:
            cleaned = adr.strip()
            if not cleaned:
                continue
            # Look for decision statements or core constraints
            if "must" in cleaned.lower() or "shall" in cleaned.lower() or "prohibit" in cleaned.lower():
                actionable.append(f"[ADR Constraint]: {cleaned}")
            else:
                actionable.append(f"[ADR Standard]: {cleaned}")

        # 3. Extract caveats and pitfalls from bug postmortems
        for bug in input_data.bug_histories:
            cleaned = bug.strip()
            if not cleaned:
                continue
            conflicts.append(f"[Historical Bug Caution]: {cleaned}")

        # 4. Extract guidance from general documentation fragments
        for frag in input_data.fragments:
            cleaned = frag.strip()
            if not cleaned:
                continue
            # Shorten and extract first salient sentence
            sentences = re.split(r"(?<=[.!?])\s+", cleaned)
            first_salient = sentences[0] if sentences else cleaned
            if len(first_salient) > 160:
                first_salient = first_salient[:157] + "..."
            actionable.append(f"[Pattern Guidance]: {first_salient}")

        # Fallback if no specific guidelines extracted
        if not actionable:
            actionable.append(f"[General Directives]: Apply standard idiomatic patterns for '{input_data.query}'.")

        # Deduplicate and limit to configured maximum
        unique_actionable = list(dict.fromkeys(actionable))[: self._config.max_synthesis_directives * 2]
        unique_conflicts = list(dict.fromkeys(conflicts))[: self._config.max_synthesis_directives]

        summary_assertion = (
            f"Consolidated engineering assessment for query '{input_data.query}' across "
            f"{len(input_data.adrs)} ADRs, {len(input_data.bug_histories)} bug reports, and "
            f"{len(input_data.fragments)} documentation fragments."
        )

        return SynthesizedDirective(
            directive_id=directive_id,
            summary_assertion=summary_assertion,
            actionable_guidelines=unique_actionable,
            conflict_warnings=unique_conflicts,
        )

    def format_directive(self, directive: SynthesizedDirective) -> str:
        """Render a synthesized directive as a clean prompt section."""
        lines: List[str] = [
            f"### [ENGINEERING SYNTHESIS DIRECTIVE: {directive.directive_id}]",
            f"**ASSERTION**: {directive.summary_assertion}",
            "**ACTIONABLE GUIDELINES**:",
        ]
        for g in directive.actionable_guidelines:
            lines.append(f"- {g}")

        if directive.conflict_warnings:
            lines.append("**HISTORICAL PITFALLS & CONFLICTS**:")
            for w in directive.conflict_warnings:
                lines.append(f"- {w}")

        return "\n".join(lines)
