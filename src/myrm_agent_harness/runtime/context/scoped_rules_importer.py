"""Hermes and OpenClaw scoped rules asset importer.

Parses external rule manifests (e.g. .hermes/ configs or raw markdown bundles)
and translates them into the native Myrm FiveLayerRuleMatrix.

[INPUT]
- runtime.context.multi_gateway_trust_types::FiveLayerRuleMatrix, RuleEntry, RuleLayerKind (POS: Strongly
  typed data contracts for Model-Harness orthogonal decoupling and multi-gateway trust.)

[OUTPUT]
- ScopedRulesImporter: Seamless migration adapter for Hermes and OpenClaw agent rule definitions.

[POS]
Hermes and OpenClaw scoped rules asset importer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.multi_gateway_trust_types import (
    FiveLayerRuleMatrix,
    RuleEntry,
    RuleLayerKind,
)


class ScopedRulesImporter:
    """Seamless migration adapter for Hermes and OpenClaw agent rule definitions."""

    @staticmethod
    def _extract_rules_from_markdown(
        content: str,
        layer: RuleLayerKind,
        category_hint: str,
    ) -> list[RuleEntry]:
        """Parse bulleted rule items from markdown text into RuleEntry objects."""
        rules: list[RuleEntry] = []
        lines = content.strip().splitlines()
        idx = 0

        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            # Match standard markdown list bullets (-, *, 1.)
            bullet_match = re.match(r"^[-*•]\s+(.*)$|^\d+\.\s+(.*)$", line_str)
            if bullet_match:
                item_text = (bullet_match.group(1) or bullet_match.group(2) or "").strip()
                if item_text:
                    idx += 1
                    # Extract bracketed prefix [Category] if present
                    bracket_match = re.match(r"^\[(.*?)\]\s*(.*)$", item_text)
                    if bracket_match:
                        cat = bracket_match.group(1).strip()
                        body = bracket_match.group(2).strip()
                    else:
                        cat = category_hint
                        body = item_text

                    rules.append(
                        RuleEntry(
                            rule_id=f"{layer.value}_{idx}",
                            layer=layer,
                            category=cat,
                            content=body,
                            is_ephemeral=False,
                            tags=(category_hint,),
                        )
                    )
            elif not line_str.startswith("```"):
                # Standalone sentence fallback
                idx += 1
                rules.append(
                    RuleEntry(
                        rule_id=f"{layer.value}_{idx}",
                        layer=layer,
                        category=category_hint,
                        content=line_str,
                        is_ephemeral=False,
                        tags=(category_hint,),
                    )
                )

        return rules

    def import_from_file_bundle(
        self,
        file_map: Mapping[str, str],
    ) -> FiveLayerRuleMatrix:
        """Translate a map of filenames to markdown contents into FiveLayerRuleMatrix.

        Keys can be filenames like 'SOUL.md', 'AGENTS.md', 'CONTEXT.md',
        'VOICE.md', 'Corrections.md', or Hermes-style directory paths.
        """
        soul_rules: list[RuleEntry] = []
        agents_rules: list[RuleEntry] = []
        context_rules: list[RuleEntry] = []
        voice_rules: list[RuleEntry] = []
        corrections_rules: list[RuleEntry] = []

        for name, text in file_map.items():
            base = name.upper().split("/")[-1]
            if "SOUL" in base:
                soul_rules.extend(
                    self._extract_rules_from_markdown(text, RuleLayerKind.SOUL, "soul")
                )
            elif "AGENT" in base:
                agents_rules.extend(
                    self._extract_rules_from_markdown(text, RuleLayerKind.AGENTS, "engineering")
                )
            elif "CONTEXT" in base:
                context_rules.extend(
                    self._extract_rules_from_markdown(text, RuleLayerKind.CONTEXT, "domain_context")
                )
            elif "VOICE" in base:
                voice_rules.extend(
                    self._extract_rules_from_markdown(text, RuleLayerKind.VOICE, "tone")
                )
            elif "CORRECTION" in base:
                corrections_rules.extend(
                    self._extract_rules_from_markdown(text, RuleLayerKind.CORRECTIONS, "bugfix_lesson")
                )

        return FiveLayerRuleMatrix(
            soul_rules=tuple(soul_rules),
            agents_rules=tuple(agents_rules),
            context_rules=tuple(context_rules),
            voice_rules=tuple(voice_rules),
            corrections_rules=tuple(corrections_rules),
        )
