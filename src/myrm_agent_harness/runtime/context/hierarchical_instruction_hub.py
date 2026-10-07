"""Project-Specific Goosehints and Hierarchical Instruction Hub.

Coordinates multi-tier project hints (.goosehints, AGENT.md, SOUL.md, .cursorrules),
performs deep invisible Unicode sanitization to neutralize prompt injection,
and orchestrates scoping inheritance across global, workspace, and subpackage tiers.

[INPUT]
- runtime.context.hierarchical_instruction_hub_types::HierarchicalInstructionBlock,
  InheritanceResolutionStrategy, InstructionRuleEntry, InstructionTierKind (POS: Type definitions for
  Project-Specific Goosehints and Hierarchical Instruction Hub.)

[OUTPUT]
- HierarchicalInstructionHub: Aggregates and formats multi-tier instruction rules into KV-cache friendly
  prompt blocks.
- HierarchicalInstructionResolver: Resolves hierarchical instructions according to scoping and inheritance
  strategies.
- InvisibleUnicodeSanitizer: Detects and strips deceptive invisible Unicode and bidirectional override
  characters.

[POS]
Project-Specific Goosehints and Hierarchical Instruction Hub.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.hierarchical_instruction_hub_types import (
    HierarchicalInstructionBlock,
    InheritanceResolutionStrategy,
    InstructionRuleEntry,
    InstructionTierKind,
)

__all__ = [
    "HierarchicalInstructionBlock",
    "HierarchicalInstructionHub",
    "HierarchicalInstructionResolver",
    "InheritanceResolutionStrategy",
    "InstructionRuleEntry",
    "InstructionTierKind",
    "InvisibleUnicodeSanitizer",
]


class InvisibleUnicodeSanitizer:
    """Detects and strips deceptive invisible Unicode and bidirectional override characters."""

    # Zero-width spaces, bidi trojan controls, soft hyphens, and Unicode tag blocks
    _INVISIBLE_UNICODE_PATTERN: re.Pattern[str] = re.compile(
        r"[\u200B\u200C\u200D\uFEFF\u00AD"
        r"\u202A-\u202E\u2066-\u2069"
        r"\U000E0000-\U000E007F]"
    )

    @classmethod
    def sanitize(cls, text: str) -> tuple[str, int]:
        """Strips hidden characters and returns (cleaned_text, stripped_count)."""
        stripped_count = len(cls._INVISIBLE_UNICODE_PATTERN.findall(text))
        if stripped_count == 0:
            return text, 0
        cleaned = cls._INVISIBLE_UNICODE_PATTERN.sub("", text)
        return cleaned, stripped_count


class HierarchicalInstructionResolver:
    """Resolves hierarchical instructions according to scoping and inheritance strategies."""

    @classmethod
    def resolve_rules(
        cls,
        rules: Sequence[InstructionRuleEntry],
        strategy: InheritanceResolutionStrategy = InheritanceResolutionStrategy.APPEND_INHERIT,
    ) -> tuple[InstructionRuleEntry, ...]:
        """Resolves ordering and overrides across hierarchical instruction rules."""
        if strategy == InheritanceResolutionStrategy.APPEND_INHERIT:
            # Maintain natural hierarchy order: Global -> Workspace -> Subdirectory
            tier_order = {
                InstructionTierKind.GLOBAL_USER: 0,
                InstructionTierKind.WORKSPACE_ROOT: 1,
                InstructionTierKind.SUBDIRECTORY_PACKAGE: 2,
            }
            return tuple(sorted(rules, key=lambda r: tier_order.get(r.tier, 99)))

        # SCOPING_OVERRIDE: Descendants override ancestors with the identical rule_name
        rule_map: dict[str, InstructionRuleEntry] = {}
        # Traverse in ascending priority order so higher tiers overwrite lower tiers
        tier_priority = {
            InstructionTierKind.GLOBAL_USER: 0,
            InstructionTierKind.WORKSPACE_ROOT: 1,
            InstructionTierKind.SUBDIRECTORY_PACKAGE: 2,
        }
        sorted_candidates = sorted(rules, key=lambda r: tier_priority.get(r.tier, 0))
        for r in sorted_candidates:
            rule_map[r.rule_name] = r

        return tuple(rule_map.values())


class HierarchicalInstructionHub:
    """Aggregates and formats multi-tier instruction rules into KV-cache friendly prompt blocks."""

    _RECOGNIZED_HINT_FILES: tuple[str, ...] = (
        ".goosehints",
        "goosehints",
        "AGENT.md",
        "AGENTS.md",
        "SOUL.md",
        "MEMORY.md",
        "CLAUDE.md",
        ".cursorrules",
    )

    @classmethod
    def create_rule_entry(
        cls,
        *,
        tier: InstructionTierKind,
        source_path: str,
        content: str,
        rule_name: str | None = None,
    ) -> InstructionRuleEntry:
        """Sanitizes content and creates an immutable instruction rule entry."""
        cleaned_content, stripped_count = InvisibleUnicodeSanitizer.sanitize(content)
        name = rule_name or os.path.basename(source_path)
        return InstructionRuleEntry(
            tier=tier,
            source_path=source_path,
            rule_name=name,
            content=cleaned_content.strip(),
            char_count=len(cleaned_content.strip()),
            stripped_invisible_chars_count=stripped_count,
        )

    @classmethod
    def scan_directory_hints(
        cls,
        dir_path: str,
        tier: InstructionTierKind,
    ) -> list[InstructionRuleEntry]:
        """Scans a specific directory for recognized hint files and loads them."""
        entries: list[InstructionRuleEntry] = []
        if not os.path.isdir(dir_path):
            return entries

        for filename in cls._RECOGNIZED_HINT_FILES:
            full_path = os.path.join(dir_path, filename)
            if os.path.isfile(full_path):
                try:
                    with open(full_path, encoding="utf-8", errors="replace") as f:
                        raw_text = f.read()
                    if raw_text.strip():
                        entries.append(
                            cls.create_rule_entry(
                                tier=tier,
                                source_path=full_path,
                                content=raw_text,
                                rule_name=filename,
                            )
                        )
                except OSError:
                    continue
        return entries

    @classmethod
    def compose_instruction_block(
        cls,
        rules: Sequence[InstructionRuleEntry],
        strategy: InheritanceResolutionStrategy = InheritanceResolutionStrategy.APPEND_INHERIT,
    ) -> HierarchicalInstructionBlock:
        """Assembles resolved rules into a structured XML system prompt block."""
        resolved = HierarchicalInstructionResolver.resolve_rules(rules, strategy=strategy)

        tier_counts: dict[str, int] = {}
        for r in resolved:
            tier_key = r.tier.value
            tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1

        total_chars = sum(r.char_count for r in resolved)

        xml_lines: list[str] = [
            '<hierarchical_project_instructions version="1.0">',
            f'  <summary total_rules="{len(resolved)}" total_chars="{total_chars}" strategy="{strategy.value}" />',
        ]

        # Group by tier for clean KV cache prefix locality
        for tier_kind in (
            InstructionTierKind.GLOBAL_USER,
            InstructionTierKind.WORKSPACE_ROOT,
            InstructionTierKind.SUBDIRECTORY_PACKAGE,
        ):
            tier_rules = [r for r in resolved if r.tier == tier_kind]
            if not tier_rules:
                continue

            xml_lines.append(f'  <tier name="{tier_kind.value}">')
            for r in tier_rules:
                xml_lines.append(f'    <rule name="{r.rule_name}" source="{r.source_path}">')
                xml_lines.append(f"      {r.content}")
                xml_lines.append("    </rule>")
            xml_lines.append("  </tier>")

        xml_lines.append("</hierarchical_project_instructions>")
        rendered_xml = "\n".join(xml_lines)

        return HierarchicalInstructionBlock(
            resolved_rules=resolved,
            rendered_xml=rendered_xml,
            total_chars=total_chars,
            tier_counts=tier_counts,
        )
